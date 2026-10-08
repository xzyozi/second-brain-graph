#!/usr/bin/env python3
"""
tools/doctor.py - プロジェクト受入態勢診断＆一発修復ツール (Issue #83)

サテライトプロジェクトの受入態勢（レジストリ、project.json、tasks.md、.venv、.gitignore、
Issue仕様書、GitHub標準ラベル）を一括診断し、--fix で不足している構成要素を自動生成・修復します。

使用例:
  uv run python tools/doctor.py TFG
  uv run python tools/doctor.py https://github.com/xzyozi/test_file_grep/issues/5
  uv run python tools/doctor.py --fix
  uv run python tools/doctor.py --all
"""

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.metadata_store import (  # noqa: E402
    load_project_registry,
    resolve_project_from_cwd,
    resolve_target_spec,
    self_heal_satellite_project_json,
)
from tools.run_task import ensure_satellite_gitignore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("doctor")

STANDARD_LABELS: Dict[str, Dict[str, str]] = {
    "stage:ideation": {"color": "D4C5F9", "description": "アイデア・壁打ち検討中"},
    "stage:ready": {"color": "0E8A16", "description": "実装準備完了"},
    "stage:in-progress": {"color": "FBCA04", "description": "自律実装進行中"},
    "stage:done": {"color": "1D76DB", "description": "実装・マージ完了"},
    "stage:abandoned": {"color": "666666", "description": "見送り・中断"},
    "priority:high": {"color": "B60205", "description": "高優先度"},
    "priority:medium": {"color": "FBCA04", "description": "中優先度"},
    "priority:low": {"color": "0E8A16", "description": "低優先度"},
}


@dataclass
class CheckResult:
    name: str
    status: str  # "OK", "WARN", "FAIL", "FIXED"
    message: str
    fixable: bool = False


def check_registry(
    project_key: str, project_root: Path
) -> Tuple[CheckResult, Optional[Dict[str, Any]]]:
    """1. 母艦 .project-registry.json 登録整合性チェック"""
    reg = load_project_registry(project_root)
    if project_key not in reg:
        return (
            CheckResult(
                name="Registry Entry",
                status="FAIL",
                message=f".project-registry.json にキー '{project_key}' が見つかりません。",
                fixable=False,
            ),
            None,
        )
    pdata = reg[project_key]
    dir_rel = pdata.get("dir")
    if not dir_rel:
        return (
            CheckResult(
                name="Registry Entry",
                status="FAIL",
                message=f"キー '{project_key}' に 'dir' フィールドが定義されていません。",
                fixable=False,
            ),
            pdata,
        )
    return (
        CheckResult(
            name="Registry Entry",
            status="OK",
            message=f".project-registry.json に登録済み (dir: {dir_rel})",
        ),
        pdata,
    )


def check_satellite_dir(sat_dir: Path) -> CheckResult:
    """サテライトディレクトリおよび .git の存在チェック"""
    if not sat_dir.exists():
        return CheckResult(
            name="Satellite Directory",
            status="FAIL",
            message=f"サテライトディレクトリが存在しません: {sat_dir}",
            fixable=False,
        )
    git_dir = sat_dir / ".git"
    if not git_dir.exists():
        return CheckResult(
            name="Git Repository",
            status="FAIL",
            message=f"Git リポジトリ (.git) が存在しません: {sat_dir}",
            fixable=False,
        )
    return CheckResult(
        name="Satellite Directory",
        status="OK",
        message=f"実在する Git リポジトリ: {sat_dir}",
    )


def check_project_json(
    project_key: str,
    sat_dir: Path,
    proj_entry: Dict[str, Any],
    project_root: Path,
    fix: bool = False,
) -> CheckResult:
    """2. サテライト docs/project.json の存在と key 一致チェック"""
    pjson_path = sat_dir / "docs" / "project.json"
    if not pjson_path.exists():
        if fix:
            healed = self_heal_satellite_project_json(
                project_key, proj_entry, project_root=project_root
            )
            if healed and healed.exists():
                return CheckResult(
                    name="Satellite project.json",
                    status="FIXED",
                    message="docs/project.json が欠落していましたが、レジストリから自動自己修復しました。",
                )
            return CheckResult(
                name="Satellite project.json",
                status="FAIL",
                message="docs/project.json の自己修復に失敗しました。",
                fixable=True,
            )
        return CheckResult(
            name="Satellite project.json",
            status="FAIL",
            message=f"docs/project.json が存在しません (修バック可能: --fix)。パス: {pjson_path}",
            fixable=True,
        )

    try:
        data = json.loads(pjson_path.read_text(encoding="utf-8"))
        if data.get("key") != project_key:
            return CheckResult(
                name="Satellite project.json",
                status="WARN",
                message=f"docs/project.json の key ('{data.get('key')}') が母艦のキー ('{project_key}') と異なります。",
                fixable=False,
            )
        return CheckResult(
            name="Satellite project.json",
            status="OK",
            message=f"docs/project.json 存在・key一致 ({project_key})",
        )
    except Exception as e:
        return CheckResult(
            name="Satellite project.json",
            status="FAIL",
            message=f"docs/project.json の読み込みに失敗しました: {e}",
            fixable=False,
        )


def check_tasks_md(
    sat_dir: Path,
    project_key: str,
    fix: bool = False,
) -> CheckResult:
    """3. サテライト docs/tasks.md の存在チェック"""
    tasks_file = sat_dir / "docs" / "tasks.md"
    if not tasks_file.exists():
        if fix:
            tasks_file.parent.mkdir(parents=True, exist_ok=True)
            tasks_file.write_text(
                f"# Tasks for {project_key}\n\n<!-- タスク一覧 -->\n", encoding="utf-8"
            )
            return CheckResult(
                name="Tasks Backlog",
                status="FIXED",
                message="docs/tasks.md を新規作成しました。",
            )
        return CheckResult(
            name="Tasks Backlog",
            status="FAIL",
            message="docs/tasks.md が存在しません (修復可能: --fix)",
            fixable=True,
        )

    try:
        content = tasks_file.read_text(encoding="utf-8")
        task_count = len(re.findall(rf"\[{project_key}-\d{{4}}", content))
        return CheckResult(
            name="Tasks Backlog",
            status="OK",
            message=f"docs/tasks.md 存在 (登録タスク数: {task_count} 件)",
        )
    except Exception as e:
        return CheckResult(
            name="Tasks Backlog",
            status="WARN",
            message=f"docs/tasks.md の解析中にエラーが発生しました: {e}",
            fixable=False,
        )


def check_venv(sat_dir: Path, fix: bool = False) -> CheckResult:
    """4. サテライト .venv 仮想環境の存在と Python 実行可能性チェック"""
    venv_dir = sat_dir / ".venv"
    if sys.platform == "win32":
        py_bin = venv_dir / "Scripts" / "python.exe"
    else:
        py_bin = venv_dir / "bin" / "python"

    if not py_bin.exists():
        if fix:
            try:
                # 1. uv venv を試行
                res = subprocess.run(
                    ["uv", "venv"],
                    cwd=str(sat_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and py_bin.exists():
                    return CheckResult(
                        name="Virtual Environment",
                        status="FIXED",
                        message="uv venv により .venv 仮想環境を作成しました。",
                    )
                # 2. フォールバックで python -m venv
                res2 = subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    cwd=str(sat_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res2.returncode == 0 and py_bin.exists():
                    return CheckResult(
                        name="Virtual Environment",
                        status="FIXED",
                        message="python -m venv により .venv 仮想環境を作成しました。",
                    )
            except Exception as e:
                return CheckResult(
                    name="Virtual Environment",
                    status="FAIL",
                    message=f".venv の作成に失敗しました: {e}",
                    fixable=True,
                )
        return CheckResult(
            name="Virtual Environment",
            status="FAIL",
            message=f".venv 仮想環境が見つかりません (修復可能: --fix)。パス: {py_bin}",
            fixable=True,
        )

    # 実行可能性テスト
    try:
        ver_proc = subprocess.run(
            [str(py_bin), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if ver_proc.returncode == 0:
            ver_str = ver_proc.stdout.strip() or ver_proc.stderr.strip()
            return CheckResult(
                name="Virtual Environment",
                status="OK",
                message=f".venv 仮想環境 有効 ({ver_str})",
            )
        else:
            return CheckResult(
                name="Virtual Environment",
                status="WARN",
                message=f".venv の Python がエラーコード {ver_proc.returncode} で終了しました。",
                fixable=False,
            )
    except Exception as e:
        return CheckResult(
            name="Virtual Environment",
            status="WARN",
            message=f".venv 実行テスト失敗: {e}",
            fixable=False,
        )


def check_gitignore(sat_dir: Path, fix: bool = False) -> CheckResult:
    """サテライトの .gitignore 設定チェック"""
    gitignore_file = sat_dir / ".gitignore"
    content = ""
    if gitignore_file.exists():
        content = gitignore_file.read_text(encoding="utf-8")

    needs_venv = ".venv" not in content
    needs_aider = ".aider" not in content

    if needs_venv or needs_aider:
        if fix:
            ensure_satellite_gitignore(str(sat_dir))
            return CheckResult(
                name="Git Ignore",
                status="FIXED",
                message=".gitignore に .venv/ および .aider* を追記しました。",
            )
        missing_entries = []
        if needs_venv:
            missing_entries.append(".venv/")
        if needs_aider:
            missing_entries.append(".aider*")
        return CheckResult(
            name="Git Ignore",
            status="WARN",
            message=f".gitignore に {', '.join(missing_entries)} が未設定です (修復可能: --fix)",
            fixable=True,
        )

    return CheckResult(
        name="Git Ignore",
        status="OK",
        message=".gitignore に .venv/ および .aider* が設定済み",
    )


def check_issue_specs(sat_dir: Path, project_key: str) -> CheckResult:
    """6. 未完了タスクに対応する仕様書 (docs/issues/*.md) の整合性チェック"""
    tasks_file = sat_dir / "docs" / "tasks.md"
    if not tasks_file.exists():
        return CheckResult(
            name="Issue Specifications",
            status="OK",
            message="tasks.md が存在しないためスキップ",
        )

    content = tasks_file.read_text(encoding="utf-8")
    ready_tasks = re.findall(
        rf"-\s*\[\s*\]\s*\[({project_key}-\d{{4}}(?:-[A-Z])?)\].*?stage:ready",
        content,
    )
    if not ready_tasks:
        ready_tasks = re.findall(
            rf"-\s*\[\s*\]\s*\[({project_key}-\d{{4}}(?:-[A-Z])?)\]",
            content,
        )

    if not ready_tasks:
        return CheckResult(
            name="Issue Specifications",
            status="OK",
            message="未完了タスクなし (または仕様書チェック対象なし)",
        )

    issues_dir = sat_dir / "docs" / "issues"
    missing_specs = []
    for tid in ready_tasks:
        spec_path = issues_dir / f"{tid}.md"
        if not spec_path.exists():
            missing_specs.append(tid)

    if missing_specs:
        return CheckResult(
            name="Issue Specifications",
            status="WARN",
            message=f"仕様書が未作成のタスクがあります: {', '.join(missing_specs[:5])}{'...' if len(missing_specs) > 5 else ''}",
            fixable=False,
        )

    return CheckResult(
        name="Issue Specifications",
        status="OK",
        message=f"未完了タスク {len(ready_tasks)} 件の仕様書 (docs/issues/*.md) が全て存在",
    )


def check_github_labels(github_repo: Optional[str], fix: bool = False) -> CheckResult:
    """5. GitHub リポジトリ上の標準ラベルチェック"""
    if not github_repo:
        return CheckResult(
            name="GitHub Labels",
            status="WARN",
            message="github_repo が未設定のため GitHub ラベルの確認をスキップしました。",
        )

    if not shutil.which("gh"):
        return CheckResult(
            name="GitHub Labels",
            status="WARN",
            message="GitHub CLI (gh) がインストールされていないため確認をスキップしました。",
        )

    try:
        proc = subprocess.run(
            ["gh", "label", "list", "--repo", github_repo, "--json", "name", "--limit", "100"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return CheckResult(
                name="GitHub Labels",
                status="WARN",
                message=f"gh label list 実行失敗: {proc.stderr.strip()[:100]}",
            )

        existing_data = json.loads(proc.stdout)
        existing_names = {lbl["name"] for lbl in existing_data if "name" in lbl}

        missing_labels = [name for name in STANDARD_LABELS if name not in existing_names]

        if missing_labels:
            if fix:
                created = []
                for lbl_name in missing_labels:
                    info = STANDARD_LABELS[lbl_name]
                    create_cmd = [
                        "gh",
                        "label",
                        "create",
                        lbl_name,
                        "--repo",
                        github_repo,
                        "--color",
                        info["color"],
                        "--description",
                        info["description"],
                    ]
                    c_res = subprocess.run(
                        create_cmd,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if c_res.returncode == 0:
                        created.append(lbl_name)
                if created:
                    return CheckResult(
                        name="GitHub Labels",
                        status="FIXED",
                        message=f"不足していた標準ラベル {len(created)} 件 ({', '.join(created)}) を作成しました。",
                    )
            return CheckResult(
                name="GitHub Labels",
                status="WARN",
                message=f"未作成の標準ラベルがあります: {', '.join(missing_labels)} (修復可能: --fix)",
                fixable=True,
            )

        return CheckResult(
            name="GitHub Labels",
            status="OK",
            message=f"必須標準ラベル {len(STANDARD_LABELS)}/{len(STANDARD_LABELS)} 件 設定済み",
        )
    except Exception as e:
        return CheckResult(
            name="GitHub Labels",
            status="WARN",
            message=f"GitHub ラベルチェック中にエラー: {e}",
        )


def diagnose_project(
    project_key: str,
    project_root: Path,
    fix: bool = False,
) -> List[CheckResult]:
    """1つのプロジェクトに対して全診断を実行する。"""
    results: List[CheckResult] = []

    # 1. レジストリチェック
    reg_res, pdata = check_registry(project_key, project_root)
    results.append(reg_res)
    if not pdata or reg_res.status == "FAIL":
        return results

    dir_rel = pdata.get("dir", f"projects/{pdata.get('name', '')}")
    sat_dir = project_root / dir_rel
    github_repo = pdata.get("github_repo")

    # サテライトディレクトリ & .git チェック
    dir_res = check_satellite_dir(sat_dir)
    results.append(dir_res)
    if dir_res.status == "FAIL":
        return results

    # 2. docs/project.json チェック
    results.append(
        check_project_json(
            project_key, sat_dir, pdata, project_root=project_root, fix=fix
        )
    )

    # 3. docs/tasks.md チェック
    results.append(check_tasks_md(sat_dir, project_key, fix=fix))

    # 4. .venv 仮想環境チェック
    results.append(check_venv(sat_dir, fix=fix))

    # .gitignore チェック
    results.append(check_gitignore(sat_dir, fix=fix))

    # 5. Issue 仕様書チェック
    results.append(check_issue_specs(sat_dir, project_key))

    # 6. GitHub ラベルチェック
    results.append(check_github_labels(github_repo, fix=fix))

    return results


def print_doctor_report(project_key: str, results: List[CheckResult]) -> bool:
    """診断結果を整形してコンソールに出力する。"""
    print(f"\n=== Doctor Report: [{project_key}] ===")
    status_icons = {
        "OK": "[✓]",
        "FIXED": "[+]",
        "WARN": "[!]",
        "FAIL": "[✗]",
    }

    errors = 0
    warnings = 0
    fixed = 0

    for r in results:
        icon = status_icons.get(r.status, "[?]")
        print(f"{icon} {r.name}: {r.message}")
        if r.status == "FAIL":
            errors += 1
        elif r.status == "WARN":
            warnings += 1
        elif r.status == "FIXED":
            fixed += 1

    print("-" * 50)
    if errors == 0 and warnings == 0:
        if fixed > 0:
            print(f"Result: ALL FIXED & HEALTHY ({fixed} 件修復)")
        else:
            print("Result: ALL HEALTHY (問題なし)")
        return True
    elif errors == 0:
        print(f"Result: HEALTHY WITH WARNINGS ({warnings} 件の警告, {fixed} 件修復)")
        return True
    else:
        print(f"Result: UNHEALTHY ({errors} 件のエラー, {warnings} 件の警告)")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="プロジェクト受入態勢診断＆一発修復ツール (Second Brain OS Doctor)"
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="対象プロジェクトキー（例: TFG）、Issue URL、または Issue ID。省略時は CWD または全プロジェクト",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="レジストリに登録された全プロジェクトを一括診断する",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="検出された問題を可能な限り自動修復する",
    )

    args = parser.parse_args()
    project_root = PROJECT_ROOT

    # 診断対象プロジェクトキーの決定
    target_keys: List[str] = []

    if args.all:
        registry = load_project_registry(project_root)
        target_keys = list(registry.keys())
        if not target_keys:
            logger.error(".project-registry.json に登録されているプロジェクトがありません。")
            sys.exit(1)
    elif args.target:
        resolved = resolve_target_spec(
            args.target,
            cwd=Path.cwd(),
            project_root=project_root,
        )
        resolved_key = resolved.get("project_key")
        if resolved_key:
            target_keys = [resolved_key]
        else:
            # target そのものが project_key の可能性
            target_keys = [args.target]
    else:
        # 省略時: CWD から判定
        cwd_key = resolve_project_from_cwd(Path.cwd(), project_root)
        if cwd_key:
            target_keys = [cwd_key]
        else:
            # CWD から判定できない場合は全プロジェクト
            registry = load_project_registry(project_root)
            target_keys = list(registry.keys())
            if not target_keys:
                logger.error("診断対象プロジェクトを特定できませんでした。")
                sys.exit(1)

    all_passed = True
    for pkey in target_keys:
        results = diagnose_project(pkey, project_root, fix=args.fix)
        passed = print_doctor_report(pkey, results)
        if not passed:
            all_passed = False

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()

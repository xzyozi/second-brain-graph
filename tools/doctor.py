#!/usr/bin/env python3
"""
tools/doctor.py - プロジェクト受入態勢診断＆一発修復ツール (Issue #83)

サテライトプロジェクトの受入態勢（レジストリ、project.json、レガシーファイル有無、.venv、.gitignore、
GitHub Issues 疎通、GitHub標準ラベル）を一括診断し、--fix で不足している構成要素を自動生成・修復します。

使用例:
  uv run python tools/doctor.py TFG
  uv run python tools/doctor.py https://github.com/xzyozi/test_file_grep/issues/5
  uv run python tools/doctor.py --fix
  uv run python tools/doctor.py --all
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.workspace.metadata_store import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    get_gitignore_entries_for_language,
    load_project_registry,
    resolve_project_from_cwd,
    resolve_target_spec,
    self_heal_satellite_project_json,
)

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
        if "allowed_new_file_globs" in data:
            globs = data["allowed_new_file_globs"]
            if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
                return CheckResult(
                    name="Satellite project.json",
                    status="WARN",
                    message=f"docs/project.json の allowed_new_file_globs は文字列の配列である必要があります: {globs}",
                    fixable=False,
                )
        lang = data.get("language", "python")
        if not isinstance(lang, str) or lang.strip().lower() not in SUPPORTED_LANGUAGES:
            return CheckResult(
                name="Satellite project.json",
                status="WARN",
                message=f"docs/project.json の language ('{lang}') はサポート対象外または不正です (サポート: {', '.join(SUPPORTED_LANGUAGES)})",
                fixable=False,
            )
        if "test_command" in data and not isinstance(data["test_command"], str):
            return CheckResult(
                name="Satellite project.json",
                status="WARN",
                message=f"docs/project.json の test_command は文字列である必要があります: {data['test_command']}",
                fixable=False,
            )
        msg_extra = f", language: {lang}"
        if data.get("test_command"):
            msg_extra += f", test_cmd: {data['test_command']}"
        return CheckResult(
            name="Satellite project.json",
            status="OK",
            message=f"docs/project.json 存在・key一致 ({project_key}{msg_extra})",
        )
    except Exception as e:
        return CheckResult(
            name="Satellite project.json",
            status="FAIL",
            message=f"docs/project.json の読み込みに失敗しました: {e}",
            fixable=False,
        )


def check_legacy_local_files(sat_dir: Path) -> CheckResult:
    """3. 非推奨となったレガシーローカルファイル (docs/tasks.md, docs/issues/) の残存チェック"""
    legacy_items: List[str] = []
    if (sat_dir / "docs" / "tasks.md").exists():
        legacy_items.append("docs/tasks.md")
    issues_dir = sat_dir / "docs" / "issues"
    if issues_dir.exists() and any(issues_dir.iterdir()):
        legacy_items.append("docs/issues/")

    if legacy_items:
        return CheckResult(
            name="Legacy Local Files",
            status="WARN",
            message=(
                f"非推奨のレガシーファイルが残存しています: {', '.join(legacy_items)} "
                "(GitHub Issues SSOT 移行後は削除可能です)"
            ),
            fixable=False,
        )

    return CheckResult(
        name="Legacy Local Files",
        status="OK",
        message="GitHub Issues SSOT 準拠 (レガシー tasks.md / docs/issues なし)",
    )


def check_environment(sat_dir: Path, language: str = "python", fix: bool = False) -> CheckResult:
    """4. サテライト実行環境（Python .venv, Node.js package.json, Rust Cargo.toml）の存在と実行可能性チェック (Issue #168)"""
    norm_lang = (language or "python").strip().lower()

    if norm_lang == "python":
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

    elif norm_lang in ("typescript", "javascript"):
        pkg_json = sat_dir / "package.json"
        if not pkg_json.exists():
            return CheckResult(
                name="Node.js Environment",
                status="FAIL",
                message=f"package.json が見つかりません: {pkg_json}",
                fixable=False,
            )

        node_bin = shutil.which("node")
        npm_bin = shutil.which("npm")
        if not node_bin:
            return CheckResult(
                name="Node.js Environment",
                status="WARN",
                message="システム PATH に Node.js (node) が見つかりません。",
                fixable=False,
            )

        # node version check
        try:
            n_res = subprocess.run(
                [node_bin, "--version"], capture_output=True, text=True, timeout=5, check=False
            )
            node_ver = n_res.stdout.strip() or "v?"
        except Exception:
            node_ver = "unknown"

        node_modules = sat_dir / "node_modules"
        if not node_modules.exists() or not any(node_modules.iterdir()):
            if fix and npm_bin:
                try:
                    inst_res = subprocess.run(
                        [npm_bin, "install"],
                        cwd=str(sat_dir),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if inst_res.returncode == 0:
                        return CheckResult(
                            name="Node.js Environment",
                            status="FIXED",
                            message=f"npm install により依存関係をセットアップしました (Node {node_ver})",
                        )
                except Exception as ex:
                    logger.debug(f"npm install failed during fix: {ex}")
            return CheckResult(
                name="Node.js Environment",
                status="WARN",
                message=f"node_modules が未作成です (Node {node_ver}, 修復可能: --fix)",
                fixable=bool(npm_bin),
            )

        return CheckResult(
            name="Node.js Environment",
            status="OK",
            message=f"Node.js 環境 有効 (Node {node_ver}, package.json / node_modules 存在)",
        )

    elif norm_lang == "rust":
        cargo_toml = sat_dir / "Cargo.toml"
        if not cargo_toml.exists():
            return CheckResult(
                name="Rust Environment",
                status="FAIL",
                message=f"Cargo.toml が見つかりません: {cargo_toml}",
                fixable=False,
            )

        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            return CheckResult(
                name="Rust Environment",
                status="WARN",
                message="システム PATH に Cargo (cargo) が見つかりません。",
                fixable=False,
            )

        try:
            c_res = subprocess.run(
                [cargo_bin, "--version"], capture_output=True, text=True, timeout=5, check=False
            )
            cargo_ver = c_res.stdout.strip() if c_res.returncode == 0 else "cargo"
            return CheckResult(
                name="Rust Environment",
                status="OK",
                message=f"Rust 環境 有効 ({cargo_ver}, Cargo.toml 存在)",
            )
        except Exception as e:
            return CheckResult(
                name="Rust Environment",
                status="WARN",
                message=f"Cargo 実行テスト失敗: {e}",
                fixable=False,
            )

    return CheckResult(
        name="Language Environment",
        status="OK",
        message=f"言語 '{norm_lang}' の基本検証スキップ",
    )


def check_venv(sat_dir: Path, fix: bool = False) -> CheckResult:
    """後方互換用エイリアス: Python .venv の検証"""
    return check_environment(sat_dir, language="python", fix=fix)


def _missing_gitignore_for_lang(content: str, language: str = "python") -> List[str]:
    """サテライトの .gitignore 内で言語別に未設定の生成物パターンを算出する (Issue #168)"""
    lines = {
        line.strip().rstrip("/")
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    entries = get_gitignore_entries_for_language(language)
    missing = []
    for entry in entries:
        norm = entry.strip().rstrip("/")
        if norm in lines:
            continue
        if norm.endswith("*"):
            prefix = norm[:-1]
            if any(line_item.startswith(prefix) for line_item in lines):
                continue
        missing.append(entry)
    return missing


def check_gitignore(sat_dir: Path, language: str = "python", fix: bool = False) -> CheckResult:
    """サテライトの .gitignore 設定チェック (言語別対応 Issue #168)"""
    gitignore_file = sat_dir / ".gitignore"
    if not gitignore_file.exists():
        return CheckResult(
            name="Git Ignore",
            status="WARN",
            message=".gitignore が存在しません (自動作成は行いません。手動で作成してください)",
            fixable=False,
        )

    content = gitignore_file.read_text(encoding="utf-8")
    missing_entries = _missing_gitignore_for_lang(content, language=language)

    if missing_entries:
        if fix:
            try:
                new_content = (
                    content.rstrip()
                    + f"\n\n# Autonomous worker ignores ({language})\n"
                    + "\n".join(missing_entries)
                    + "\n"
                )
                gitignore_file.write_text(new_content, encoding="utf-8")
                return CheckResult(
                    name="Git Ignore",
                    status="FIXED",
                    message=f".gitignore に {', '.join(missing_entries)} を追記しました。",
                )
            except Exception as ex:
                return CheckResult(
                    name="Git Ignore",
                    status="FAIL",
                    message=f".gitignore 追記失敗: {ex}",
                    fixable=True,
                )
        return CheckResult(
            name="Git Ignore",
            status="WARN",
            message=f".gitignore に {', '.join(missing_entries)} が未設定です (修復可能: --fix)",
            fixable=True,
        )

    return CheckResult(
        name="Git Ignore",
        status="OK",
        message=f".gitignore に生成物パターン ({language}) が設定済み",
    )


def check_github_issues_access(github_repo: Optional[str]) -> CheckResult:
    """6. GitHub CLI / GitHub Issues (SSOT) 疎通チェック"""
    if not github_repo:
        return CheckResult(
            name="GitHub Issues Access",
            status="WARN",
            message="github_repo が未設定のため GitHub Issues 疎通確認をスキップしました。",
        )

    if not shutil.which("gh"):
        return CheckResult(
            name="GitHub Issues Access",
            status="WARN",
            message="GitHub CLI (gh) がインストールされていないため疎通確認をスキップしました。",
        )

    try:
        proc = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                github_repo,
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "number",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return CheckResult(
                name="GitHub Issues Access",
                status="WARN",
                message=f"GitHub Issues 疎通失敗 ({github_repo}): {proc.stderr.strip()[:100]}",
            )
        return CheckResult(
            name="GitHub Issues Access",
            status="OK",
            message=f"GitHub Issues (SSOT) 疎通正常: {github_repo}",
        )
    except Exception as e:
        return CheckResult(
            name="GitHub Issues Access",
            status="WARN",
            message=f"GitHub Issues 疎通確認中にエラー: {e}",
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


def check_reviewdog() -> CheckResult:
    """Reviewdog の導入チェック (任意の依存。未導入でもパイプラインは動作するため WARN 止まり)"""
    path = shutil.which("reviewdog")
    if path is None:
        return CheckResult(
            name="Reviewdog",
            status="WARN",
            message=(
                "reviewdog が未導入です (任意: 導入すると差分レビューの補助に使われます。"
                "未導入の間は reviewdog 連携をスキップします)"
            ),
        )
    return CheckResult(name="Reviewdog", status="OK", message=f"reviewdog 導入済み: {path}")


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
        check_project_json(project_key, sat_dir, pdata, project_root=project_root, fix=fix)
    )

    # 言語メタデータの抽出 (Issue #168)
    satellite_lang = "python"
    pjson_path = sat_dir / "docs" / "project.json"
    if pjson_path.exists():
        try:
            pjson_data = json.loads(pjson_path.read_text(encoding="utf-8"))
            satellite_lang = pjson_data.get("language", "python")
        except Exception:
            pass
    elif "language" in pdata:
        satellite_lang = pdata["language"]

    # 3. レガシーローカルファイル (docs/tasks.md / docs/issues) チェック
    results.append(check_legacy_local_files(sat_dir))

    # 4. 実行環境チェック (言語別ディスパッチ)
    results.append(check_environment(sat_dir, language=satellite_lang, fix=fix))

    # .gitignore チェック (言語別ディスパッチ)
    results.append(check_gitignore(sat_dir, language=satellite_lang, fix=fix))

    # 5. GitHub Issues (SSOT) 疎通チェック
    results.append(check_github_issues_access(github_repo))

    # 6. GitHub ラベルチェック
    results.append(check_github_labels(github_repo, fix=fix))

    # 7. Reviewdog 導入チェック (任意)
    results.append(check_reviewdog())

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

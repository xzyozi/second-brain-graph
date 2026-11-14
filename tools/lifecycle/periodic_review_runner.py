#!/usr/bin/env python3
"""periodic_review_runner: サテライト定周期巡回＆GitHub Issues状態評価＆インクリメンタル自律レビューツール.

【責務と設計原則】
1. GitHub Issues (SSOT) の最新ステータス（Open/Closed/Labels）を取得・評価（ローカル tasks.md 同期は行わない）。
2. 前回のレビュー完了コミットからの差分（git diff）を検知。
3. コード変更がある場合のみ、差分ファイルを対象に run_review.py を実行し、GitHub Issue 起票を自動実行。
4. 最新コミットハッシュを記録・更新。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.workspace.github_issues import extract_stage_label
from tools.workspace.github_issues import fetch_remote_issues as _fetch_remote_issues_ssot

# ロガー設定: 標準出力を汚さないよう sys.stderr に出力（ユーザーグローバルルール準拠）
logger = logging.getLogger("periodic_reviewer")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".js",
    ".go",
    ".rs",
    ".sh",
    ".bash",
    ".ps1",
    ".json",
    ".yaml",
    ".yml",
}


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """CLI 引数をパースする."""
    parser = argparse.ArgumentParser(
        description="サテライト定周期巡回＆GitHub Issues状態評価＆インクリメンタル自律レビューツール"
    )
    parser.add_argument(
        "--target",
        default="",
        help="対象サテライト名（省略時は metadata/.project-registry.json に登録された全サテライトを巡回）",
    )
    parser.add_argument(
        "--theme",
        choices=["security", "edge_cases", "architecture", "all"],
        default="all",
        help="レビューテーマ（デフォルト: all = 全テーマ順次）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="コミット差分がなくても強制的に新規レビューを実行する",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="コード差分レビューは行わず、GitHub Issues のステータス取得・評価のみを実行する",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="agys レビュー実行のタイムアウト秒数（デフォルト: 240）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の Issue 起票やレビュー状態キャッシュの更新を行わずプレビューする",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細デバッグログを出力する",
    )
    return parser.parse_args(args)


def load_project_registry(root_dir: Path) -> dict[str, Any]:
    """metadata/.project-registry.json を読み込む."""
    reg_path = root_dir / "metadata" / ".project-registry.json"
    if not reg_path.is_file():
        logger.warning(f"プロジェクトレジストリが見つかりません: {reg_path}")
        return {}
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"レジストリ読み込み失敗: {e}")
        return {}


def get_cache_file_path(root_dir: Path) -> Path:
    """review_state.json のパスを返す."""
    cache_dir = root_dir / "tools" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "review_state.json"


def load_review_state(cache_file: Path) -> dict[str, Any]:
    """review_state.json を読み込む."""
    if not cache_file.is_file():
        return {}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_review_state(cache_file: Path, state: dict[str, Any]) -> None:
    """review_state.json にアトミック保存する."""
    try:
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_file.replace(cache_file)
    except Exception as e:
        logger.error(f"キャッシュ保存失敗: {e}")


def get_current_head_commit(repo_dir: Path) -> str:
    """リポジトリの現在の HEAD コミットハッシュを取得する."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"git rev-parse HEAD 失敗 ({repo_dir}): {e.stderr}")
        return ""


def detect_code_diff_files(repo_dir: Path, last_commit: str, current_head: str) -> list[str]:
    """2つのコミット間の差分からコードファイルのみを抽出する."""
    if not last_commit or last_commit == current_head:
        return []

    try:
        res = subprocess.run(
            ["git", "diff", "--name-only", last_commit, current_head],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        diff_lines = [
            line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()
        ]
        code_files = [f for f in diff_lines if Path(f).suffix.lower() in CODE_EXTENSIONS]
        return sorted(code_files)
    except subprocess.CalledProcessError as e:
        logger.warning(f"git diff 失敗 (last={last_commit}, head={current_head}): {e.stderr}")
        return []


def fetch_remote_issues(repo: str) -> list[dict[str, Any]]:
    """GitHub から全 Issue（Open/Closed）を取得する."""
    return _fetch_remote_issues_ssot(
        repo,
        state="all",
        limit=200,
        fields=["number", "title", "state", "labels", "body"],
    )


def evaluate_remote_issue_statuses(repo: str) -> dict[str, int]:
    """GitHub Issues (SSOT) の最新ステータス・stage ラベルを集計して評価する."""
    issues = fetch_remote_issues(repo)
    summary: dict[str, int] = {
        "total": len(issues),
        "open": 0,
        "closed": 0,
        "stage:ideation": 0,
        "stage:ready": 0,
        "stage:in-progress": 0,
        "stage:done": 0,
        "other_stage": 0,
    }
    for issue in issues:
        state = str(issue.get("state") or "OPEN").upper()
        if state == "CLOSED":
            summary["closed"] += 1
        else:
            summary["open"] += 1

        stage = extract_stage_label(issue)
        if stage in summary:
            summary[stage] += 1
        elif stage:
            summary["other_stage"] += 1

    logger.info(
        f"[{repo}] GitHub Issues 状態評価 (SSOT): total={summary['total']}, "
        f"open={summary['open']}, closed={summary['closed']}, "
        f"ready={summary['stage:ready']}, in_progress={summary['stage:in-progress']}, "
        f"ideation={summary['stage:ideation']}, done={summary['stage:done']}"
    )
    return summary


def execute_satellite_review(
    root_dir: Path,
    target_name: str,
    theme: str,
    files: list[str] | None,
    timeout: int,
    dry_run: bool,
) -> bool:
    """run_review.py を呼び出して自律レビューと GitHub Issue 起票を実行する."""
    reviewer_script = (
        root_dir
        / ".gemini"
        / "skills"
        / "satellite-ideation-reviewer"
        / "scripts"
        / "run_review.py"
    )

    cmd = [
        sys.executable,
        str(reviewer_script),
        "--target",
        target_name,
        "--theme",
        theme,
        "--timeout",
        str(timeout),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if files:
        cmd.append("--files")
        cmd.extend(files)

    logger.info(
        f"自律レビュー実行: ターゲット={target_name}, テーマ={theme}, 対象ファイル数={len(files) if files else '全走査'}"
    )

    try:
        proc = subprocess.run(cmd, cwd=root_dir, check=False)
        return proc.returncode == 0
    except Exception as e:
        logger.error(f"run_review 実行失敗: {e}")
        return False


def process_satellite(
    root_dir: Path,
    proj_key: str,
    proj_info: dict[str, Any],
    theme: str,
    force: bool,
    status_only: bool,
    timeout: int,
    dry_run: bool,
    cache_state: dict[str, Any],
) -> None:
    """1つのサテライトに対する定周期巡回処理を実行する."""
    sat_name = proj_info.get("name", "")
    sat_rel_dir = proj_info.get("dir", "")
    repo = proj_info.get("github_repo", "")
    sat_dir = root_dir / sat_rel_dir

    if not sat_dir.is_dir():
        logger.warning(f"サテライトディレクトリが存在しません: {sat_dir}")
        return

    logger.info(f"\n{'=' * 50}\nサテライト処理開始: {sat_name} (KEY: {proj_key})\n{'=' * 50}")

    # Step 1: GitHub Issues 状態の取得・評価（コード差分の有無に関わらず実行、ローカルファイル書き込みなし）
    if repo:
        evaluate_remote_issue_statuses(repo)

    if status_only:
        logger.info(f"[{sat_name}] --status-only 指定のため、レビュー処理はスキップします。")
        return

    # Step 2: コミット差分検知
    current_head = get_current_head_commit(sat_dir)
    if not current_head:
        logger.warning(f"[{sat_name}] コミットハッシュを取得できませんでした。スキップします。")
        return

    sat_state = cache_state.get(sat_name, {})
    last_commit = sat_state.get("last_reviewed_commit", "")

    logger.info(
        f"[{sat_name}] HEAD: {current_head[:8]} | 前回レビュー: {last_commit[:8] or '(初回)'}"
    )

    diff_files: list[str] = []
    if last_commit and not force:
        if last_commit == current_head:
            logger.info(
                f"[{sat_name}] コミットに変更はありません。新規レビューをスキップします (0秒)。"
            )
            return
        diff_files = detect_code_diff_files(sat_dir, last_commit, current_head)
        if not diff_files:
            logger.info(
                f"[{sat_name}] コミットは進みましたがコードファイルの変更はありません。ハッシュを更新します。"
            )
            if not dry_run:
                sat_state["last_reviewed_commit"] = current_head
                sat_state["last_reviewed_at"] = datetime.datetime.now().isoformat()
                cache_state[sat_name] = sat_state
            return

        logger.info(
            f"[{sat_name}] 変更コードファイルを検知しました ({len(diff_files)} 件): {', '.join(diff_files[:5])}"
        )

    # Step 3: レビュー実行
    themes_to_run = ["security", "edge_cases", "architecture"] if theme == "all" else [theme]

    review_success = True
    for th in themes_to_run:
        ok = execute_satellite_review(
            root_dir=root_dir,
            target_name=sat_name,
            theme=th,
            files=diff_files if (diff_files and not force) else None,
            timeout=timeout,
            dry_run=dry_run,
        )
        if not ok:
            review_success = False

    # Step 4: キャッシュハッシュ更新
    if review_success and not dry_run:
        sat_state["last_reviewed_commit"] = current_head
        sat_state["last_reviewed_at"] = datetime.datetime.now().isoformat()
        cache_state[sat_name] = sat_state


def main(args: list[str] | None = None) -> int:
    """メイン実行フロー."""
    opts = parse_args(args)
    if opts.verbose:
        logger.setLevel(logging.DEBUG)

    root_dir = Path(__file__).resolve().parents[1]
    registry = load_project_registry(root_dir)
    projects = registry.get("projects", {})

    if not projects:
        logger.error("登録されているサテライトプロジェクトがありません。")
        return 1

    cache_file = get_cache_file_path(root_dir)
    cache_state = load_review_state(cache_file)

    target_projects = {}
    if opts.target:
        for k, v in projects.items():
            if v.get("name") == opts.target or k == opts.target:
                target_projects[k] = v
                break
        if not target_projects:
            logger.error(f"指定されたサテライトが見つかりません: {opts.target}")
            return 1
    else:
        target_projects = projects

    for proj_key, proj_info in target_projects.items():
        process_satellite(
            root_dir=root_dir,
            proj_key=proj_key,
            proj_info=proj_info,
            theme=opts.theme,
            force=opts.force,
            status_only=opts.status_only,
            timeout=opts.timeout,
            dry_run=opts.dry_run,
            cache_state=cache_state,
        )

    if not opts.dry_run:
        save_review_state(cache_file, cache_state)

    logger.info("\n全サテライトの定周期巡回処理が正常終了しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
tools/run_task.py - 衛星リポジトリのクリーンアップおよび Issue 自動実行ラッパースクリプト

ワンライナーで衛星プロダクトの git クリーンアップ (checkout, reset, clean) を行い、
オーケストレーター (orchestrator_graph.py) を安全・確実に起動します。

使用例:
  uv run python tools/run_task.py TFG-0006 --clean --fresh
  uv run python tools/run_task.py TFG-0006 --resume
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s %(levelname)s: %(message)s'
)
logger = logging.getLogger("run_task")

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.orchestrator_graph import (  # noqa: E402
    resolve_project_context,
    validate_project_consistency,
)


def run_command(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """サブプロセス実行ヘルパー関数"""
    logger.info(f"Running: {' '.join(cmd)} (cwd: {cwd or '.'})")
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=check)


def clean_satellite_repository(cwd: str, base_branch: str = "develop") -> None:
    """衛星プロダクトリポジトリの変更を破棄し、クリーンな初期状態にセットアップする"""
    logger.info(f"Cleaning satellite repository at '{cwd}' (base_branch: {base_branch})...")

    # 1. base_branch へ強制チェックアウト
    try:
        run_command(["git", "checkout", "-f", base_branch], cwd=cwd)
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to checkout {base_branch}: {e.stderr}. Trying git checkout -f main...")
        try:
            run_command(["git", "checkout", "-f", "main"], cwd=cwd)
            base_branch = "main"
        except subprocess.CalledProcessError as e2:
            logger.error(f"Failed to checkout base branch: {e2.stderr}")
            raise e2

    # 2. リモート追跡ブランチまたはローカル HEAD へのリセット
    try:
        run_command(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=cwd)
    except subprocess.CalledProcessError:
        logger.warning(f"origin/{base_branch} not found. Falling back to git reset --hard HEAD")
        run_command(["git", "reset", "--hard", "HEAD"], cwd=cwd)

    # 3. 未追跡ファイル・フォルダの完全クリーニング
    run_command(["git", "clean", "-fd"], cwd=cwd)
    logger.info("Satellite repository cleaning completed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean satellite repository and execute orchestrator task."
    )
    parser.add_argument(
        "issue_id",
        nargs="?",
        help="Target Issue ID (e.g. TFG-0006)",
    )
    parser.add_argument(
        "--issue-id",
        dest="issue_id_opt",
        help="Target Issue ID (alternative to positional argument)",
    )
    parser.add_argument(
        "--project-key",
        help="Target Project Key (Resolved from Issue ID if omitted)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Clean satellite repository before execution (default: True)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_false",
        dest="clean",
        help="Skip satellite repository cleanup",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        default=False,
        help="Delete existing work branch and create clean branch from base_branch",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=False,
        help="Resume existing work branch and continue work on top of previous commits",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print planned operations without executing commands",
    )

    args = parser.parse_args()

    target_issue_id = args.issue_id or args.issue_id_opt
    if not target_issue_id:
        logger.error("Error: issue_id is required. Usage: python tools/run_task.py TFG-0006")
        sys.exit(1)

    project_key = args.project_key
    if not project_key and "-" in target_issue_id:
        project_key = target_issue_id.split("-")[0]

    if not project_key:
        logger.error("Error: Could not resolve project_key from issue_id.")
        sys.exit(1)

    # 1. プロジェクトの一貫性を検証
    try:
        validate_project_consistency(target_issue_id, project_key, project_root=PROJECT_ROOT)
    except Exception as e:
        logger.error(f"Project consistency validation failed: {e}")
        sys.exit(1)

    # 2. 衛星リポジトリのコンテキスト（cwd, base_branch など）を動的解決
    ctx = resolve_project_context(project_key, project_root=PROJECT_ROOT)
    if not ctx.get("valid") or not ctx.get("cwd"):
        logger.error(f"Could not resolve satellite repository context for project '{project_key}'.")
        sys.exit(1)

    satellite_cwd = ctx["cwd"]
    base_branch = ctx.get("base_branch", "develop")

    logger.info(f"Target Issue: {target_issue_id} | Project: {project_key} | CWD: {satellite_cwd}")

    if args.dry_run:
        logger.info("[DRY RUN] Would execute satellite cleanup:")
        logger.info(f"  - git checkout -f {base_branch}")
        logger.info(f"  - git reset --hard origin/{base_branch}")
        logger.info("  - git clean -fd")
        orch_cmd = [sys.executable, "tools/orchestrator_graph.py", "execute", "--issue-id", target_issue_id, "--project-key", project_key]
        if args.fresh:
            orch_cmd.append("--fresh")
        if args.resume:
            orch_cmd.append("--resume")
        logger.info(f"[DRY RUN] Would execute orchestrator command: {' '.join(orch_cmd)}")
        return

    # 3. 衛星リポジトリのクリーンアップの実行 (--resume 指定時は変更を維持するためスキップ)
    should_clean = args.clean and not args.resume
    if should_clean:
        try:
            clean_satellite_repository(satellite_cwd, base_branch=base_branch)
        except Exception as e:
            logger.error(f"Satellite cleanup failed: {e}")
            sys.exit(1)

    # 4. オーケストレーターの実行
    exec_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "orchestrator_graph.py"),
        "execute",
        "--issue-id",
        target_issue_id,
        "--project-key",
        project_key,
    ]
    if args.fresh:
        exec_cmd.append("--fresh")
    if args.resume:
        exec_cmd.append("--resume")

    logger.info(f"Starting orchestrator execution for {target_issue_id}...")
    res = subprocess.run(exec_cmd, cwd=str(PROJECT_ROOT))
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()

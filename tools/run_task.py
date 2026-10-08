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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# ロガー設定
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("run_task")

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.metadata_store import resolve_target_spec  # noqa: E402
from tools.orchestrator_graph import (  # noqa: E402
    ensure_satellite_environment,
    resolve_project_context,
    validate_project_consistency,
)


class DirtyWorkingTreeError(RuntimeError):
    """未コミット変更や未追跡ファイルが検出された場合のエラー"""

    pass


def run_command(
    cmd: List[str], cwd: Optional[str] = None, check: bool = True
) -> subprocess.CompletedProcess:
    """サブプロセス実行ヘルパー関数"""
    logger.info(f"Running: {' '.join(cmd)} (cwd: {cwd or '.'})")
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=check)


def check_and_safeguard_working_tree(
    cwd: str,
    auto_stash: bool = False,
    force: bool = False,
    issue_id: Optional[str] = None,
) -> bool:
    """衛星リポジトリの作業ツリーの未コミット変更を検知し、安全に退避またはエラーを発生させる。

    返り値: stash を実行した場合は True、それ以外は False
    """
    status_res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if status_res.returncode != 0:
        logger.warning(f"Failed to inspect git status in '{cwd}': {status_res.stderr}")
        return False

    dirty_output = status_res.stdout.strip()
    if not dirty_output:
        return False

    logger.warning(f"Uncommitted changes or untracked files detected in '{cwd}':\n{dirty_output}")

    if force:
        logger.warning(
            "--force flag specified. Proceeding without safeguarding uncommitted changes."
        )
        return False

    if auto_stash:
        stash_msg = f"run_task: auto-stash before {issue_id or 'task'}"
        logger.info(f"Auto-stashing uncommitted changes in '{cwd}' (message: '{stash_msg}')...")
        stash_res = run_command(
            ["git", "stash", "push", "-u", "-m", stash_msg], cwd=cwd, check=False
        )
        if stash_res.returncode != 0:
            raise RuntimeError(f"Failed to auto-stash uncommitted changes: {stash_res.stderr}")
        logger.info("Auto-stash completed successfully.")
        return True

    error_msg = (
        f"Dirty working tree detected in satellite repository '{cwd}'.\n"
        "To prevent accidental loss of work, execution was aborted.\n"
        "Options:\n"
        "  1. Commit or stash your changes manually.\n"
        "  2. Re-run with '--auto-stash' to automatically stash changes before execution.\n"
        "  3. Re-run with '--force' to discard all uncommitted changes."
    )
    raise DirtyWorkingTreeError(error_msg)


def backup_critical_metadata(cwd: str) -> dict[str, str]:
    """docs/project.json などの重要構成ファイルをメモリに退避する。"""
    backup: dict[str, str] = {}
    pjson = Path(cwd) / "docs" / "project.json"
    if pjson.exists():
        try:
            backup["project.json"] = pjson.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not backup {pjson}: {e}")
    return backup


def restore_critical_metadata(cwd: str, backup: dict[str, str]) -> None:
    """退避した重要構成ファイルを復元する（git clean -fd 等で消去された場合の自己修復）。"""
    if "project.json" in backup:
        pjson = Path(cwd) / "docs" / "project.json"
        if not pjson.exists():
            pjson.parent.mkdir(parents=True, exist_ok=True)
            pjson.write_text(backup["project.json"], encoding="utf-8")
            logger.info(f"Self-healed: restored {pjson} after git clean.")


def ensure_satellite_base_branch(cwd: str, base_branch: str = "develop") -> str:
    """base_branch (develop) が存在しない場合、リモート default branch (main 等) から作成する。"""
    # 1. ローカル base_branch が存在するか確認
    chk_local = subprocess.run(
        ["git", "rev-parse", "--verify", base_branch],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if chk_local.returncode == 0:
        run_command(["git", "checkout", "-f", base_branch], cwd=cwd)
        return base_branch

    # 2. リモート origin/{base_branch} が存在するか確認
    chk_remote = subprocess.run(
        ["git", "rev-parse", "--verify", f"origin/{base_branch}"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if chk_remote.returncode == 0:
        run_command(
            ["git", "checkout", "-f", "-b", base_branch, f"origin/{base_branch}"],
            cwd=cwd,
        )
        return base_branch

    # 3. develop がローカルにもリモートにも無い場合: main / default branch から develop を作成
    default_branch = "main"
    for candidate in ["origin/main", "origin/master", "main", "master"]:
        chk_def = subprocess.run(
            ["git", "rev-parse", "--verify", candidate],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if chk_def.returncode == 0:
            default_branch = candidate
            break

    logger.warning(
        f"base_branch '{base_branch}' not found in '{cwd}'. Creating '{base_branch}' from '{default_branch}'..."
    )
    run_command(["git", "checkout", "-b", base_branch, default_branch], cwd=cwd)
    logger.info(f"Successfully created base_branch '{base_branch}' from '{default_branch}'.")
    return base_branch


def sync_base_branch(cwd: str, base_branch: str = "develop") -> None:
    """ベースブランチをリモートの最新状態と同期する (git fetch origin {base_branch})"""
    logger.info(f"Fetching latest origin/{base_branch} for '{cwd}'...")
    fetch_res = subprocess.run(
        ["git", "fetch", "origin", base_branch],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if fetch_res.returncode == 0:
        logger.info(f"Successfully fetched origin/{base_branch}.")
    else:
        logger.warning(
            f"git fetch origin {base_branch} failed (offline or branch not found): {fetch_res.stderr.strip()}"
        )


def ensure_satellite_gitignore(cwd: str) -> None:
    """サテライトの .gitignore に .venv/ および .aider* が含まれていることを保証する (自己修復)."""
    gi_path = Path(cwd) / ".gitignore"
    if not gi_path.exists():
        return
    try:
        content = gi_path.read_text(encoding="utf-8")
        needed = []
        if ".venv" not in content:
            needed.append(".venv/")
        if ".aider" not in content:
            needed.append(".aider*")
        if needed:
            logger.info(f"Adding {needed} to {gi_path}")
            new_content = (
                content.rstrip() + "\n\n# Autonomous worker ignores\n" + "\n".join(needed) + "\n"
            )
            gi_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to inspect/update {gi_path}: {e}")


def clean_satellite_repository(
    cwd: str,
    base_branch: str = "develop",
    auto_stash: bool = False,
    force: bool = False,
    issue_id: Optional[str] = None,
) -> None:
    """衛星プロダクトリポジトリの変更を破棄または退避し、クリーンな初期状態にセットアップする"""
    logger.info(f"Cleaning satellite repository at '{cwd}' (base_branch: {base_branch})...")

    # 重要メタデータの事前退避
    metadata_backup = backup_critical_metadata(cwd)

    # 0. .gitignore の自己修復 (.venv, .aider*)
    ensure_satellite_gitignore(cwd)

    # 1. 未コミット変更の事前チェック & 退避/停止
    check_and_safeguard_working_tree(cwd, auto_stash=auto_stash, force=force, issue_id=issue_id)

    # 2. リモートベースブランチの同期
    sync_base_branch(cwd, base_branch=base_branch)

    # 3. base_branch へ強制チェックアウト（未存在時は main から作成）
    ensure_satellite_base_branch(cwd, base_branch=base_branch)

    # 4. リモート追跡ブランチまたはローカル HEAD へのリセット
    try:
        run_command(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=cwd)
    except subprocess.CalledProcessError:
        logger.warning(f"origin/{base_branch} not found. Falling back to git reset --hard HEAD")
        run_command(["git", "reset", "--hard", "HEAD"], cwd=cwd)

    # 5. 未追跡ファイル・フォルダの完全クリーニング
    run_command(["git", "clean", "-fd"], cwd=cwd)

    # 5.5 .aider 関連の過去履歴・キャッシュの完全削除（コンテキスト4万トークン肥大化防止）
    for aider_artifact in Path(cwd).glob(".aider*"):
        try:
            if aider_artifact.is_file():
                aider_artifact.unlink()
            elif aider_artifact.is_dir():
                shutil.rmtree(aider_artifact)
        except Exception as e:
            logger.warning(f"Failed to clean aider artifact {aider_artifact}: {e}")

    # 6. 未追跡だった重要メタデータが消去された場合は自己修復復元
    restore_critical_metadata(cwd, metadata_backup)

    # 7. サテライト仮想環境 (.venv) の事前検証・自動セットアップ
    ensure_satellite_environment(cwd)

    logger.info("Satellite repository cleaning completed successfully.")


def reset_task_environment(
    target_issue_id: str,
    project_key: str,
    satellite_cwd: str,
    base_branch: str = "develop",
    auto_stash: bool = False,
    force: bool = False,
    project_root: Optional[Path] = None,
) -> None:
    """指定 Issue の実行状態を完全に初期化（リセット）する (Issue #80)。

    処理手順:
    1. state.json から該当 Issue のエントリを削除 (reset_task_state)
    2. サテライト作業ツリーの未コミット変更を退避または確認
    3. 作業ブランチ (sbos/<ISSUE_ID>) を削除し、base_branch (develop) へ切り替え
    4. サテライトの未追跡残骸 (git clean -fd) のクリーンアップ
    5. 過去の失敗レポート (FAILURE_REPORT_<ISSUE_ID>.md) のクリーンアップ
    6. プロジェクトロック (.lock) の解放 (残留時)
    """
    logger.info(
        f"=== Resetting task environment for '{target_issue_id}' (Project: {project_key}) ==="
    )
    from tools.metadata_store import force_unlock_project, reset_task_state

    root = project_root or PROJECT_ROOT

    # 1. state.json のエントリ初期化
    reset_ok = reset_task_state(project_key, target_issue_id)
    if reset_ok:
        logger.info(f"Task state cleared from state.json for {target_issue_id}.")
    else:
        logger.info(f"No existing state entry found for {target_issue_id} in state.json.")

    # 2. サテライト作業ツリーの安全確認と作業ブランチの削除
    if satellite_cwd and Path(satellite_cwd).exists():
        check_and_safeguard_working_tree(
            satellite_cwd, auto_stash=auto_stash, force=force, issue_id=target_issue_id
        )

        metadata_backup = backup_critical_metadata(satellite_cwd)

        # 3. base_branch への切り替えと作業ブランチの削除
        work_branch = f"sbos/{target_issue_id}"
        logger.info(f"Checking out base branch '{base_branch}' in satellite repository...")
        ensure_satellite_base_branch(satellite_cwd, base_branch=base_branch)

        # ローカル作業ブランチの削除
        chk_branch = subprocess.run(
            ["git", "rev-parse", "--verify", work_branch],
            cwd=satellite_cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if chk_branch.returncode == 0:
            logger.info(f"Deleting leftover local work branch '{work_branch}'...")
            del_res = subprocess.run(
                ["git", "branch", "-D", work_branch],
                cwd=satellite_cwd,
                text=True,
                capture_output=True,
                check=False,
            )
            if del_res.returncode == 0:
                logger.info(f"Deleted work branch '{work_branch}'.")
            else:
                logger.warning(f"Failed to delete branch '{work_branch}': {del_res.stderr}")

        # サテライトのクリーンアップ (git reset & clean)
        logger.info(f"Cleaning satellite repository at '{satellite_cwd}'...")
        try:
            run_command(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=satellite_cwd)
        except subprocess.CalledProcessError:
            run_command(["git", "reset", "--hard", "HEAD"], cwd=satellite_cwd)
        run_command(["git", "clean", "-fd"], cwd=satellite_cwd)
        restore_critical_metadata(satellite_cwd, metadata_backup)
        ensure_satellite_gitignore(satellite_cwd)
        ensure_satellite_environment(satellite_cwd)

    # 4. 失敗レポートのクリーンアップ
    failure_report_candidates = [
        root
        / "metadata"
        / "projects"
        / project_key
        / "issues"
        / f"FAILURE_REPORT_{target_issue_id}.md",
        root / "metadata" / "projects" / project_key / f"FAILURE_REPORT_{target_issue_id}.md",
    ]
    if satellite_cwd:
        failure_report_candidates.append(
            Path(satellite_cwd) / "docs" / "issues" / f"FAILURE_REPORT_{target_issue_id}.md"
        )
    for rep in failure_report_candidates:
        if rep and rep.exists():
            try:
                rep.unlink()
                logger.info(f"Removed failure report: {rep}")
            except Exception as e:
                logger.warning(f"Failed to remove failure report {rep}: {e}")

    # 5. プロジェクトロックの解放 (もし残留していれば)
    try:
        force_unlock_project(project_key)
    except Exception:
        pass

    logger.info(f"=== Reset completed successfully for '{target_issue_id}' ===")


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
        "--auto-stash",
        action="store_true",
        default=True,
        help="Automatically stash uncommitted changes in satellite repository before execution (default: True)",
    )
    parser.add_argument(
        "--no-auto-stash",
        "--no-stash",
        action="store_false",
        dest="auto_stash",
        help="Disable automatic stashing of uncommitted changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force cleanup of uncommitted changes in satellite repository without safeguarding",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Reset task state in state.json, remove work branch, and clean satellite workspace without re-running",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        default=False,
        help="Reset task state and satellite branch cleanly, then immediately re-run with --fresh",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print planned operations without executing commands",
    )

    args = parser.parse_args()

    raw_target = args.issue_id or args.issue_id_opt
    if not raw_target:
        logger.error(
            "Error: issue_id is required. Usage: python tools/run_task.py TFG-0006 or <GitHub Issue URL>"
        )
        sys.exit(1)

    spec_res = resolve_target_spec(
        raw_target,
        project_hint=args.project_key,
        cwd=Path.cwd(),
        project_root=PROJECT_ROOT,
    )

    project_key = args.project_key or spec_res.get("project_key")
    target_issue_id = spec_res.get("task_id") or raw_target

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
        if args.reset or args.retry:
            logger.info("[DRY RUN] Would reset task environment:")
            logger.info(f"  - Clear state.json entry for '{target_issue_id}'")
            logger.info(f"  - Delete work branch 'sbos/{target_issue_id}' in '{satellite_cwd}'")
            logger.info(f"  - Reset satellite to origin/{base_branch} and git clean -fd")
            logger.info(f"  - Remove failure report for '{target_issue_id}'")
            if args.reset:
                return

        logger.info("[DRY RUN] Would execute satellite cleanup:")
        if args.auto_stash:
            logger.info("  - git stash push -u (auto-stash)")
        logger.info(f"  - git fetch origin {base_branch}")
        logger.info(f"  - git checkout -f {base_branch}")
        logger.info(f"  - git reset --hard origin/{base_branch}")
        logger.info("  - git clean -fd")
        orch_cmd = [
            sys.executable,
            "tools/orchestrator_graph.py",
            "execute",
            "--issue-id",
            target_issue_id,
            "--project-key",
            project_key,
        ]
        if args.fresh or args.retry:
            orch_cmd.append("--fresh")
        if args.resume:
            orch_cmd.append("--resume")
        if args.auto_stash:
            orch_cmd.append("--auto-stash")
        logger.info(f"[DRY RUN] Would execute orchestrator command: {' '.join(orch_cmd)}")
        return

    # 2.5. リセットまたはリトライの実行 (Issue #80)
    if args.reset or args.retry:
        try:
            reset_task_environment(
                target_issue_id,
                project_key,
                satellite_cwd,
                base_branch=base_branch,
                auto_stash=args.auto_stash,
                force=args.force,
                project_root=PROJECT_ROOT,
            )
        except Exception as e:
            logger.error(f"Task reset failed: {e}")
            sys.exit(1)

        if args.reset:
            logger.info(
                "Task reset completed successfully. Skipping execution (--reset specified)."
            )
            return

        # --retry の場合は fresh モードとして続行
        args.fresh = True

    # 3. 衛星リポジトリのクリーンアップの実行 (--resume 指定時、または --retry 済みの場合はスキップ)
    should_clean = args.clean and not args.resume and not args.retry
    if should_clean:
        try:
            clean_satellite_repository(
                satellite_cwd,
                base_branch=base_branch,
                auto_stash=args.auto_stash,
                force=args.force,
                issue_id=target_issue_id,
            )
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
    if args.auto_stash:
        exec_cmd.append("--auto-stash")

    logger.info(f"Starting orchestrator execution for {target_issue_id}...")
    res = subprocess.run(exec_cmd, cwd=str(PROJECT_ROOT))
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()

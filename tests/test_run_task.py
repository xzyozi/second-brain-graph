"""Unit tests for tools/run_task.py wrapper script."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.run_task import (
    DirtyWorkingTreeError,
    clean_satellite_repository,
    main,
)


def test_clean_satellite_repository_executes_git_commands() -> None:
    """clean_satellite_repository が git status, fetch, branch check, checkout, reset, clean を正しい順番で実行することを検証する。"""
    executed_cmds = []

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        executed_cmds.append(" ".join(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository("/path/to/sat", base_branch="develop")

    assert len(executed_cmds) == 6
    assert executed_cmds[0] == "git status --porcelain"
    assert executed_cmds[1] == "git fetch origin develop"
    assert executed_cmds[2] == "git rev-parse --verify develop"
    assert executed_cmds[3] == "git checkout -f develop"
    assert executed_cmds[4] == "git reset --hard origin/develop"
    assert executed_cmds[5] == "git clean -fd"


def test_clean_satellite_repository_creates_develop_from_main_when_missing() -> None:
    """develop ブランチがローカルにもリモートにも無い場合、main から作成してチェックアウトすることを検証する。"""
    executed_cmds = []

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        cmd_str = " ".join(cmd)
        executed_cmds.append(cmd_str)
        # develop はローカル・リモートともに存在しない
        if (
            "rev-parse --verify develop" in cmd_str
            or "rev-parse --verify origin/develop" in cmd_str
        ):
            return MagicMock(returncode=1, stdout="", stderr="not found")
        # origin/main は存在する
        if "rev-parse --verify origin/main" in cmd_str:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository("/path/to/sat", base_branch="develop")

    assert any("git checkout -b develop origin/main" in c for c in executed_cmds)


def test_clean_satellite_repository_self_heals_untracked_project_json(tmp_path: Path) -> None:
    """git clean で未追跡の project.json が消去された場合でも、自己修復によって復元されることを検証する。"""
    sat_dir = tmp_path / "satellite"
    docs_dir = sat_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    pjson = docs_dir / "project.json"
    pjson.write_text('{"key": "TEST", "base_branch": "develop"}', encoding="utf-8")

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        cmd_str = " ".join(cmd)
        # git clean -fd が呼ばれたら project.json を物理削除して再現
        if "clean -fd" in cmd_str:
            if pjson.exists():
                pjson.unlink()
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository(str(sat_dir), base_branch="develop")

    assert pjson.exists()
    assert '"key": "TEST"' in pjson.read_text(encoding="utf-8")


def test_clean_satellite_repository_dirty_aborts_without_auto_stash_or_force() -> None:
    """未コミット変更がある場合、--auto-stash も --force も無ければ DirtyWorkingTreeError で停止することを検証する。"""

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=" M src/dirty.py\n?? untracked.txt", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        with pytest.raises(DirtyWorkingTreeError) as exc_info:
            clean_satellite_repository("/path/to/sat", base_branch="develop")
        assert "Dirty working tree detected" in str(exc_info.value)
        assert "--auto-stash" in str(exc_info.value)


def test_clean_satellite_repository_dirty_with_auto_stash() -> None:
    """未コミット変更がある場合でも、auto_stash=True なら git stash push されて正常に完了することを検証する。"""
    executed_cmds = []

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        executed_cmds.append(" ".join(cmd))
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=" M src/dirty.py", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository(
            "/path/to/sat", base_branch="develop", auto_stash=True, issue_id="TFG-0006"
        )

    assert any(
        "git stash push -u -m run_task: auto-stash before TFG-0006" in c for c in executed_cmds
    )
    assert any("git checkout -f develop" in c for c in executed_cmds)
    assert any("git clean -fd" in c for c in executed_cmds)


def test_clean_satellite_repository_dirty_with_force() -> None:
    """未コミット変更がある場合でも、force=True なら例外を出さずにクリーンアップを実行することを検証する。"""
    executed_cmds = []

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        executed_cmds.append(" ".join(cmd))
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=" M src/dirty.py", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository("/path/to/sat", base_branch="develop", force=True)

    assert not any("stash" in c for c in executed_cmds)
    assert any("git checkout -f develop" in c for c in executed_cmds)
    assert any("git clean -fd" in c for c in executed_cmds)


def test_run_task_resume_skips_cleanup(tmp_path: Path) -> None:
    """main が --resume オプション時に衛星リポジトリのクリーンアップをスキップすることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)

    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8",
    )

    with (
        patch("tools.run_task.clean_satellite_repository") as mock_clean,
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("sys.argv", ["run_task.py", "TFG-0006", "--resume"]),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass

    assert not mock_clean.called


def test_run_task_main_dry_run(tmp_path: Path) -> None:
    """main が --dry-run オプション時に一貫性検証とコンテキスト解決を行い、実際のサブプロセスを起動せずに正常終了することを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8",
    )

    test_args = ["run_task.py", "TFG-0005", "--dry-run", "--fresh"]

    with (
        patch("sys.argv", test_args),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.clean_satellite_repository") as mock_clean,
        patch("subprocess.run") as mock_sub_run,
    ):
        main()
        mock_clean.assert_not_called()
        mock_sub_run.assert_not_called()


def test_run_task_main_passes_auto_stash_to_orchestrator(tmp_path: Path) -> None:
    """main が --auto-stash を clean_satellite_repository および orchestrator_graph.py の引数に渡すことを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8",
    )

    test_args = ["run_task.py", "TFG-0005", "--auto-stash"]

    with (
        patch("sys.argv", test_args),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.clean_satellite_repository") as mock_clean,
        patch("subprocess.run") as mock_sub_run,
    ):
        mock_sub_run.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass

        assert mock_clean.called
        assert mock_clean.call_args.kwargs.get("auto_stash") is True

        assert mock_sub_run.called
        exec_cmd = mock_sub_run.call_args.args[0]
        assert "--auto-stash" in exec_cmd


def test_run_task_main_defaults_to_auto_stash_and_supports_no_stash(tmp_path: Path) -> None:
    """フラグ未指定時にデフォルトで auto_stash=True となり、--no-stash で False になることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    reg_file = metadata_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "TFG": {
                "name": "test_file_grep",
                "dir": "projects/test_file_grep",
                "meta": "metadata/projects/TFG",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    from tools.run_task import main

    # 1. 引数なし (デフォルト): auto_stash は True
    with (
        patch("sys.argv", ["run_task.py", "TFG-0005"]),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.clean_satellite_repository") as mock_clean,
        patch("subprocess.run") as mock_sub_run,
    ):
        mock_sub_run.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass
        assert mock_clean.called
        assert mock_clean.call_args.kwargs.get("auto_stash") is True

    # 2. --no-stash 指定時: auto_stash は False
    with (
        patch("sys.argv", ["run_task.py", "TFG-0005", "--no-stash"]),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.clean_satellite_repository") as mock_clean_no,
        patch("subprocess.run") as mock_sub_run_no,
    ):
        mock_sub_run_no.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass
        assert mock_clean_no.call_args.kwargs.get("auto_stash") is False


def test_ensure_satellite_gitignore(tmp_path: Path) -> None:
    """サテライトの .gitignore に .venv/ および .aider* が欠けている場合に自動追記されることを検証する。"""
    from tools.run_task import ensure_satellite_gitignore

    gi_file = tmp_path / ".gitignore"
    gi_file.write_text("*.pyc\n__pycache__/\n", encoding="utf-8")

    ensure_satellite_gitignore(str(tmp_path))

    content = gi_file.read_text(encoding="utf-8")
    assert ".venv/" in content
    assert ".aider*" in content

    # 既に存在する場合は二重追加されないこと
    ensure_satellite_gitignore(str(tmp_path))
    content_second = gi_file.read_text(encoding="utf-8")
    assert content_second.count(".venv/") == 1
    assert content_second.count(".aider*") == 1


def test_reset_task_environment(tmp_path: Path) -> None:
    """Issue #80: reset_task_environment が state.json、作業ブランチ、失敗レポートをリセットすることを検証する。"""
    from tools.run_task import reset_task_environment

    project_root = tmp_path
    meta_tfg = project_root / "metadata" / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    report_file = meta_tfg / "issues" / "FAILURE_REPORT_TFG-0005.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("failure details", encoding="utf-8")

    sat_dir = project_root / "projects" / "test_file_grep"
    sat_dir.mkdir(parents=True, exist_ok=True)

    executed_cmds = []

    def mock_run(
        cmd: list[str],
        cwd: str | None = None,
        text: bool = True,
        capture_output: bool = True,
        check: bool = True,
    ) -> MagicMock:
        executed_cmds.append(" ".join(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_run),
        patch("tools.metadata_store.reset_task_state") as mock_reset_state,
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.ensure_satellite_environment"),
    ):
        mock_reset_state.return_value = True

        reset_task_environment(
            "TFG-0005",
            "TFG",
            str(sat_dir),
            base_branch="develop",
            project_root=project_root,
        )

        mock_reset_state.assert_called_once_with("TFG", "TFG-0005")
        assert not report_file.exists()  # 失敗レポートが削除されていること
        assert any("branch -D sbos/TFG-0005" in c for c in executed_cmds)


def test_run_task_main_reset(tmp_path: Path) -> None:
    """Issue #80: main が --reset でリセットを実行し、オーケストレーターを起動せずに終了することを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8",
    )

    sat_dir = project_root / "projects" / "test_file_grep"
    sat_dir.mkdir(parents=True, exist_ok=True)
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    test_args = ["run_task.py", "TFG-0005", "--reset"]

    with (
        patch("sys.argv", test_args),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.reset_task_environment") as mock_reset_env,
        patch("subprocess.run") as mock_sub_run,
    ):
        main()

        mock_reset_env.assert_called_once()
        assert not mock_sub_run.called  # オーケストレーターは起動されないこと


def test_run_task_main_retry(tmp_path: Path) -> None:
    """Issue #80: main が --retry でリセットを実行後、--fresh を付与してオーケストレーターを起動することを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8",
    )

    sat_dir = project_root / "projects" / "test_file_grep"
    sat_dir.mkdir(parents=True, exist_ok=True)
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    test_args = ["run_task.py", "TFG-0005", "--retry"]

    with (
        patch("sys.argv", test_args),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.reset_task_environment") as mock_reset_env,
        patch("subprocess.run") as mock_sub_run,
    ):
        mock_sub_run.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass

        mock_reset_env.assert_called_once()
        assert mock_sub_run.called
        exec_cmd = mock_sub_run.call_args.args[0]
        assert "--fresh" in exec_cmd


def test_run_task_main_resolves_url_and_cwd(tmp_path: Path) -> None:
    """run_task.py の位置引数に GitHub Issue URL を指定した場合に、
    自動的にプロジェクトキーとタスクIDが解決されてオーケストレーターに渡されることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    (meta_tfg / "project.json").write_text(
        '{"key": "TFG", "base_branch": "develop"}', encoding="utf-8"
    )
    reg_data = {
        "projects": {
            "TFG": {
                "name": "test_file_grep",
                "github_repo": "xzyozi/test_file_grep",
                "dir": "projects/test_file_grep",
                "meta": "metadata/projects/TFG",
            }
        }
    }
    (metadata_dir / ".project-registry.json").write_text(json.dumps(reg_data), encoding="utf-8")

    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)
    (sat_docs / "tasks.md").write_text(
        "- [ ] [TFG-0005] パス検証関数を追加 (issue:#5)\n", encoding="utf-8"
    )

    test_args = ["run_task.py", "https://github.com/xzyozi/test_file_grep/issues/5"]

    with (
        patch("sys.argv", test_args),
        patch("tools.run_task.PROJECT_ROOT", project_root),
        patch("tools.run_task.clean_satellite_repository") as mock_clean,
        patch("subprocess.run") as mock_sub_run,
    ):
        mock_sub_run.return_value = MagicMock(returncode=0)
        try:
            main()
        except SystemExit:
            pass

        assert mock_clean.called
        assert mock_sub_run.called
        exec_cmd = mock_sub_run.call_args.args[0]
        # 引数に --issue-id TFG-0005 --project-key TFG が渡されていること
        assert "TFG-0005" in exec_cmd
        assert "TFG" in exec_cmd

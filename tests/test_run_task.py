"""Unit tests for tools/run_task.py wrapper script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.run_task import (
    DirtyWorkingTreeError,
    clean_satellite_repository,
    main,
)


def test_clean_satellite_repository_executes_git_commands() -> None:
    """clean_satellite_repository が git status, fetch, checkout, reset, clean を正しい順番で実行することを検証する。"""
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

    assert len(executed_cmds) == 5
    assert executed_cmds[0] == "git status --porcelain"
    assert executed_cmds[1] == "git fetch origin develop"
    assert executed_cmds[2] == "git checkout -f develop"
    assert executed_cmds[3] == "git reset --hard origin/develop"
    assert executed_cmds[4] == "git clean -fd"


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

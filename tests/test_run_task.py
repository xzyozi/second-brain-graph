"""Unit tests for tools/run_task.py wrapper script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.run_task import clean_satellite_repository, main


def test_clean_satellite_repository_executes_git_commands() -> None:
    """clean_satellite_repository が git checkout, git reset, git clean を正しい順番で実行することを検証する。"""
    executed_cmds = []

    def mock_run(cmd, cwd=None, text=True, capture_output=True, check=True):
        executed_cmds.append(" ".join(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        clean_satellite_repository("/path/to/sat", base_branch="develop")

    assert len(executed_cmds) == 3
    assert executed_cmds[0] == "git checkout -f develop"
    assert executed_cmds[1] == "git reset --hard origin/develop"
    assert executed_cmds[2] == "git clean -fd"


def test_run_task_resume_skips_cleanup(tmp_path: Path) -> None:
    """main が --resume オプション時に衛星リポジトリのクリーンアップをスキップすることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)

    (meta_tfg / "project.json").write_text('{"key": "TFG", "base_branch": "develop"}', encoding="utf-8")
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8"
    )

    with patch("tools.run_task.clean_satellite_repository") as mock_clean, \
         patch("tools.run_task.PROJECT_ROOT", project_root), \
         patch("sys.argv", ["run_task.py", "TFG-0006", "--resume"]), \
         patch("subprocess.run") as mock_run:
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

    (meta_tfg / "project.json").write_text('{"key": "TFG", "base_branch": "develop"}', encoding="utf-8")
    (metadata_dir / ".project-registry.json").write_text(
        '{"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}',
        encoding="utf-8"
    )

    test_args = ["run_task.py", "TFG-0005", "--dry-run", "--fresh"]

    with patch("sys.argv", test_args), \
         patch("tools.run_task.PROJECT_ROOT", project_root), \
         patch("tools.run_task.clean_satellite_repository") as mock_clean, \
         patch("subprocess.run") as mock_sub_run:
        main()
        mock_clean.assert_not_called()
        mock_sub_run.assert_not_called()

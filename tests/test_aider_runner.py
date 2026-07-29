"""Unit tests for tools.aider_runner."""

from unittest.mock import MagicMock, patch
from tools.aider_runner import get_git_diff, run_aider


@patch("subprocess.run")
def test_get_git_diff_success(mock_run):
    mock_res = MagicMock()
    mock_res.stdout = "diff --git a/file.txt b/file.txt"
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    diff = get_git_diff(cwd=".")
    assert "diff --git" in diff
    mock_run.assert_called_once_with(
        ["git", "diff", "HEAD"],
        cwd=".",
        capture_output=True,
        text=True,
        check=True,
    )


@patch("subprocess.run")
def test_get_git_diff_failure(mock_run):
    mock_run.side_effect = Exception("Git not found")
    diff = get_git_diff(cwd=".")
    assert diff == ""

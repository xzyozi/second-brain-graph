"""Unit tests for tools/git_utils.py."""

from unittest.mock import MagicMock, patch

import pytest

from tools.git_utils import GitDiffError, get_current_branch, get_git_diff


def test_get_git_diff_success() -> None:
    """git diff コマンドが成功した際、標準出力の文字列が返されることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "diff --git a/file.txt b/file.txt\n+new line"
        diff = get_git_diff(cwd=".")
        assert "diff --git" in diff


def test_get_git_diff_failure() -> None:
    """git diff コマンド失敗時に GitDiffError が送出されることを検証する (fail-closed)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "git error"
        with pytest.raises(GitDiffError):
            get_git_diff(cwd=".")


def test_get_git_diff_bad_revision_fallback() -> None:
    """HEAD が存在しない初回コミット前リポジトリで --cached と unstaged がフォールバック結合されることを検証する。"""
    with patch("subprocess.run") as mock_run:

        def side_effect(cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
            res = MagicMock()
            if "add" in cmd:
                res.returncode = 0
                res.stdout = ""
                res.stderr = ""
            elif "HEAD" in cmd:
                res.returncode = 128
                res.stdout = ""
                res.stderr = "fatal: bad revision 'HEAD'"
            elif "--cached" in cmd:
                res.returncode = 0
                res.stdout = "diff --git a/staged.txt b/staged.txt"
                res.stderr = ""
            else:
                res.returncode = 0
                res.stdout = "diff --git a/unstaged.txt b/unstaged.txt"
                res.stderr = ""
            return res

        mock_run.side_effect = side_effect
        diff = get_git_diff(cwd=".")
        assert "diff --git a/staged.txt" in diff
        assert "diff --git a/unstaged.txt" in diff


def test_get_git_diff_base_branch_fallback() -> None:
    """HEAD との差分が空で base_branch が指定されている場合、base_branch...HEAD の差分が取得されることを検証する。"""
    with patch("subprocess.run") as mock_run:

        def side_effect(cmd: list[str], *args: object, **kwargs: object) -> MagicMock:
            res = MagicMock()
            if "add" in cmd:
                res.returncode = 0
                res.stdout = ""
            elif "HEAD" in cmd and len(cmd) == 3:  # git diff HEAD
                res.returncode = 0
                res.stdout = ""  # 空
            elif "origin/main...HEAD" in cmd:
                res.returncode = 0
                res.stdout = "diff --git a/feature.py b/feature.py\n+feature line"
            else:
                res.returncode = 0
                res.stdout = ""
            return res

        mock_run.side_effect = side_effect
        diff = get_git_diff(cwd=".", base_branch="main")
        assert "diff --git a/feature.py" in diff


def test_get_current_branch_success() -> None:
    """git branch --show-current が成功した際、ブランチ名が返されることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "sbos/TFG-0005\n"
        assert get_current_branch(cwd=".") == "sbos/TFG-0005"


def test_get_current_branch_detached_head_returns_none() -> None:
    """detached HEAD (空文字列) の場合、None が返されることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "\n"
        assert get_current_branch(cwd=".") is None


def test_get_current_branch_error_returns_none() -> None:
    """非0終了や例外発生時、None が返されることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        assert get_current_branch(cwd=".") is None

"""
Unit tests for tools/aider_runner.py
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.aider_runner import AiderRunError, GitDiffError, get_git_diff, run_aider


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


@patch("subprocess.run")
def test_run_aider_success(mock_run: MagicMock) -> None:
    """run_aider が成功時に True を返すことを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Fix bug", ["test.py"])
    assert res is True
    assert mock_run.called


@patch("subprocess.run")
def test_run_aider_custom_model_and_timeout(mock_run: MagicMock) -> None:
    """run_aider にカスタムモデルとタイムアウトが渡されることを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Fix bug", ["test.py"], model="ollama/custom-model", timeout=600)
    assert res is True
    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    assert "ollama/custom-model" in cmd


@patch("subprocess.run")
def test_run_aider_timeout_raises_error(mock_run: MagicMock) -> None:
    """Aider 実行タイムアウト時に AiderRunError が発生することを検証する。"""
    import subprocess
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="aider", timeout=300)
    with pytest.raises(AiderRunError, match="timed out"):
        run_aider("Fix bug", ["test.py"])


def test_run_aider_file_not_found(tmp_path: Path) -> None:
    """指定されたターゲットファイルが存在しない場合に FileNotFoundError が発生することを検証する。"""
    with pytest.raises(FileNotFoundError):
        run_aider("Fix bug", ["nonexistent.py"], cwd=str(tmp_path))


@patch("subprocess.run")
def test_run_aider_sanitizes_ollama_api_base_v1_suffix(mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """OLLAMA_API_BASE に /v1 サフィックスが含まれる場合、自動的に除去されることを検証する。"""
    mock_run.return_value.returncode = 0
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434/v1")

    run_aider("Fix bug", ["test.py"])

    assert mock_run.called
    env_passed = mock_run.call_args[1]["env"]
    assert env_passed["OLLAMA_API_BASE"] == "http://localhost:11434"

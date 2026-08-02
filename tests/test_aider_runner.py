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


@patch("subprocess.run")
def test_run_aider_allows_nonexistent_files(mock_run: MagicMock, tmp_path: Path) -> None:
    """指定されたターゲットファイルが存在しない場合でも FileNotFoundError を投げず新規ファイル作成を許可することを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Create new file", ["new_script.py"], cwd=str(tmp_path))
    assert res is True
    assert mock_run.called


def test_get_default_aider_model() -> None:
    """config/models.json からモデル名を正常取得できることを検証する。"""
    from tools.aider_runner import get_default_aider_model
    model = get_default_aider_model()
    assert isinstance(model, str)
    assert len(model) > 0


@patch("subprocess.run")
def test_run_aider_sanitizes_ollama_api_base_v1_suffix(mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """OLLAMA_API_BASE に /v1 サフィックスが含まれる場合、自動的に除去されることを検証する。"""
    mock_run.return_value.returncode = 0
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434/v1")

    run_aider("Fix bug", ["test.py"])

    assert mock_run.called
    env_passed = mock_run.call_args[1]["env"]
    assert env_passed["OLLAMA_API_BASE"] == "http://localhost:11434"


def test_get_git_diff_bad_revision_fallback() -> None:
    """HEAD コミットがない新規リポジトリで git diff HEAD が失敗した際、git diff --cached と git diff へフォールバックすることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=128, stderr="fatal: bad revision 'HEAD'"),
            MagicMock(returncode=0, stdout="diff --git a/staged.py b/staged.py"),
            MagicMock(returncode=0, stdout="diff --git a/unstaged.py b/unstaged.py"),
        ]
        diff = get_git_diff(cwd=".")
        assert "a/staged.py" in diff
        assert "a/unstaged.py" in diff
        assert mock_run.call_count == 4


@patch("subprocess.run")
def test_run_aider_nonzero_exit_raises_error(mock_run: MagicMock) -> None:
    """Aider が非ゼロ終了コードを返した場合に AiderRunError が発生することを検証する。"""
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Aider process error"
    with pytest.raises(AiderRunError, match="returncode 1"):
        run_aider("Fix bug", ["test.py"])


@patch("subprocess.run")
def test_run_aider_includes_edit_format(mock_run: MagicMock) -> None:
    """run_aider に edit_format パラメータまたは config 設定が指定された場合、--edit-format が CLI に渡されることを検証する。"""
    mock_run.return_value.returncode = 0
    run_aider("Fix bug", ["test.py"], edit_format="diff")
    cmd = mock_run.call_args[0][0]
    assert "--edit-format" in cmd
    assert "diff" in cmd


@patch("subprocess.run")
def test_run_aider_tmp_file_cleaned_up_on_error(mock_run: MagicMock, tmp_path: Path) -> None:
    """Aider 実行が失敗（例外発生）した場合でも、指示文の一時ファイルがクリーンアップされることを検証する。"""
    mock_run.side_effect = RuntimeError("Subprocess crash")
    with pytest.raises(AiderRunError, match="Failed to run Aider CLI"):
        run_aider("Fix bug", ["test.py"], cwd=str(tmp_path))

    # 一時ファイル (.aider.instruction_*.tmp) が削除されていることを確認
    tmp_files = list(tmp_path.glob(".aider.instruction_*.tmp"))
    assert len(tmp_files) == 0



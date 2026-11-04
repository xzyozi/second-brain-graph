"""Unit tests for tools/agy_runner.py"""

from unittest.mock import MagicMock, patch

import pytest

from tools.agy_client import AgyExitError, AgyNotFoundError, AgyTimeoutError
from tools.agy_runner import AgyRunError, run_agy_edit


@patch("tools.agy_runner.cleanup_unauthorized_aider_artifacts", return_value=[])
@patch("tools.agy_runner.run_agy_in_workdir", return_value="done")
def test_run_agy_edit_success_returns_true(
    mock_run_agy_in_workdir: MagicMock, mock_cleanup: MagicMock
) -> None:
    """正常終了時に True を返し、run_agy_in_workdir へ cwd/timeout が渡ることを検証する。"""
    result = run_agy_edit("instruction", ["src/a.py"], "/tmp/satellite", timeout=900)

    assert result is True
    mock_run_agy_in_workdir.assert_called_once_with(
        "instruction", cwd="/tmp/satellite", timeout=900
    )
    mock_cleanup.assert_called_once_with("/tmp/satellite", ["src/a.py"])


def test_run_agy_edit_requires_cwd() -> None:
    """cwd が None の場合、AgyRunError を送出することを検証する。"""
    with pytest.raises(AgyRunError, match="non-empty cwd"):
        run_agy_edit("instruction", ["src/a.py"], None)


@patch("tools.agy_runner.cleanup_unauthorized_aider_artifacts", return_value=[])
@patch(
    "tools.agy_runner.run_agy_in_workdir",
    side_effect=AgyTimeoutError("agy execution timed out after 900 seconds"),
)
def test_run_agy_edit_timeout_raises_agy_run_error_with_timed_out(
    mock_run_agy_in_workdir: MagicMock, mock_cleanup: MagicMock
) -> None:
    """タイムアウト時に AgyRunError が送出され、メッセージに 'timed out' が含まれることを検証する。

    code_node の LLM_TIMEOUT 判定は部分文字列一致のため、この契約が崩れると
    リトライ制御が効かなくなる。
    """
    with pytest.raises(AgyRunError, match="timed out"):
        run_agy_edit("instruction", [], "/tmp/satellite", timeout=900)

    mock_cleanup.assert_called_once()


@patch("tools.agy_runner.cleanup_unauthorized_aider_artifacts", return_value=[])
@patch(
    "tools.agy_runner.run_agy_in_workdir",
    side_effect=AgyExitError("agy process failed with returncode 2", returncode=2),
)
def test_run_agy_edit_nonzero_exit_raises_agy_run_error(
    mock_run_agy_in_workdir: MagicMock, mock_cleanup: MagicMock
) -> None:
    """非0終了時に AgyRunError が送出されることを検証する。"""
    with pytest.raises(AgyRunError):
        run_agy_edit("instruction", [], "/tmp/satellite")

    mock_cleanup.assert_called_once()


@patch("tools.agy_runner.cleanup_unauthorized_aider_artifacts", return_value=[])
@patch(
    "tools.agy_runner.run_agy_in_workdir",
    side_effect=AgyNotFoundError("agy not found"),
)
def test_run_agy_edit_not_found_raises_agy_run_error(
    mock_run_agy_in_workdir: MagicMock, mock_cleanup: MagicMock
) -> None:
    """agy 未導入時に AgyRunError が送出され、メッセージに導入状況が分かる文言を含むことを検証する。"""
    with pytest.raises(AgyRunError, match="not available"):
        run_agy_edit("instruction", [], "/tmp/satellite")


@patch("tools.agy_runner.cleanup_unauthorized_aider_artifacts", return_value=["ghost.py"])
@patch("tools.agy_runner.run_agy_in_workdir", return_value="done")
def test_run_agy_edit_cleanup_runs_on_success(
    mock_run_agy_in_workdir: MagicMock, mock_cleanup: MagicMock
) -> None:
    """成功時でも target_files 外の変更の後始末 (cleanup) が必ず呼ばれることを検証する。"""
    result = run_agy_edit("instruction", ["src/a.py"], "/tmp/satellite")

    assert result is True
    mock_cleanup.assert_called_once_with("/tmp/satellite", ["src/a.py"])


def test_agy_run_error_is_coder_run_error_subclass() -> None:
    """code_node の except CoderRunError が AgyRunError を捕捉できることを確認する。"""
    from tools.agy_runner import CoderRunError

    assert issubclass(AgyRunError, CoderRunError)

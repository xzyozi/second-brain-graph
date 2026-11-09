"""
Unit tests for tools/agy_client.py

agy (Antigravity CLI) の実行ファイルはこの環境・CI には存在しないため、
subprocess.Popen をすべてモックして単体テストを行う。
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from tools.agy_client import (
    AgyAuthError,
    AgyExitError,
    AgyNotFoundError,
    AgyQuotaError,
    AgyTimeoutError,
    classify_agy_exit,
    resolve_agy_executable,
    run_agy_in_workdir,
    run_agy_text,
)
from tools.agy_policy import AgyPolicyDeniedError

# ---------------------------------------------------------------------------
# resolve_agy_executable
# ---------------------------------------------------------------------------


def test_resolve_agy_executable_found_in_path() -> None:
    """PATH 上に agy.exe が見つかる場合、そのパスを返すことを検証する。"""
    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda name: "C:/tools/agy.exe" if name == "agy.exe" else None
        result = resolve_agy_executable()
        assert result == "C:/tools/agy.exe"


def test_resolve_agy_executable_found_in_known_path() -> None:
    """PATH に無いが既知の配置先に存在する場合、そのパスを返すことを検証する。"""
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.is_file", return_value=True):
            result = resolve_agy_executable()
            assert result.endswith("agy.exe")


def test_resolve_agy_executable_not_found_raises_error() -> None:
    """PATH にも既知の配置先にも見つからない場合、AgyNotFoundError を送出することを検証する。"""
    with patch("shutil.which", return_value=None):
        with patch("pathlib.Path.is_file", return_value=False):
            with pytest.raises(AgyNotFoundError):
                resolve_agy_executable()


# ---------------------------------------------------------------------------
# run_agy_text: 正常系・コマンド組み立て
# ---------------------------------------------------------------------------


@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_text_success_returns_stdout(
    mock_popen: MagicMock, mock_resolve: MagicMock
) -> None:
    """正常終了時に stdout を返すことを検証する。"""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("hello from agy", "")
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    result = run_agy_text("テストプロンプト")

    assert result == "hello from agy"


@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_text_builds_expected_command(
    mock_popen: MagicMock, mock_resolve: MagicMock
) -> None:
    """コマンドが [agy_exe, --dangerously-skip-permissions, -p, prompt] の形であることを検証する。"""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("ok", "")
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    run_agy_text("テストプロンプト")

    cmd = mock_popen.call_args[0][0]
    assert cmd == ["agy.exe", "--dangerously-skip-permissions", "-p", "テストプロンプト"]


@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_text_classifies_auth_error_from_stdout(
    mock_popen: MagicMock, mock_resolve: MagicMock
) -> None:
    """stdoutだけに出力された認証エラーもAgyAuthErrorへ分類する。"""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("Authentication failed: token expired", "")
    mock_proc.returncode = 1
    mock_popen.return_value = mock_proc

    with pytest.raises(AgyAuthError):
        run_agy_text("テストプロンプト")


# ---------------------------------------------------------------------------
# タイムアウト
# ---------------------------------------------------------------------------


@patch("tools.agy_client._terminate_process_tree")
@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_text_timeout_raises_agy_timeout_error(
    mock_popen: MagicMock, mock_resolve: MagicMock, mock_terminate: MagicMock
) -> None:
    """タイムアウト時に AgyTimeoutError が送出され、メッセージに 'timed out' が含まれることを検証する。
    また、プロセスツリー終了のヘルパーが呼ばれることを検証する。
    """
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="agy.exe", timeout=180)
    mock_popen.return_value = mock_proc

    with pytest.raises(AgyTimeoutError, match="timed out"):
        run_agy_text("テストプロンプト", timeout=180)

    mock_terminate.assert_called_once_with(mock_proc)
    mock_proc.wait.assert_called_once()


# ---------------------------------------------------------------------------
# 非0終了コード
# ---------------------------------------------------------------------------


@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_text_nonzero_exit_raises_agy_exit_error(
    mock_popen: MagicMock, mock_resolve: MagicMock
) -> None:
    """非0終了時に AgyExitError が送出され、returncode 属性が正しいことを検証する。"""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "agy process error")
    mock_proc.returncode = 2
    mock_popen.return_value = mock_proc

    with pytest.raises(AgyExitError) as exc_info:
        run_agy_text("テストプロンプト")

    assert exc_info.value.returncode == 2
    assert "returncode 2" in str(exc_info.value)


# ---------------------------------------------------------------------------
# run_agy_in_workdir: cwd 必須チェック
# ---------------------------------------------------------------------------


def test_run_agy_in_workdir_requires_cwd_empty_string() -> None:
    """cwd が空文字列の場合に ValueError が送出されることを検証する。"""
    with pytest.raises(ValueError, match="non-empty cwd"):
        run_agy_in_workdir("テストプロンプト", cwd="")


def test_run_agy_in_workdir_requires_cwd_none() -> None:
    """cwd が None の場合に ValueError が送出されることを検証する (型注釈上は str だが実行時の防御)。"""
    with pytest.raises(ValueError, match="non-empty cwd"):
        run_agy_in_workdir("テストプロンプト", cwd=None)  # type: ignore[arg-type]


@patch("tools.agy_client.resolve_agy_executable", return_value="agy.exe")
@patch("subprocess.Popen")
def test_run_agy_in_workdir_passes_cwd_to_popen(
    mock_popen: MagicMock, mock_resolve: MagicMock
) -> None:
    """正常系で渡した cwd がそのまま subprocess.Popen の cwd 引数に渡ることを検証する。"""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("done", "")
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    result = run_agy_in_workdir("編集指示", cwd="/tmp/satellite-worktree")

    assert result == "done"
    assert mock_popen.call_args[1]["cwd"] == "/tmp/satellite-worktree"


# ---------------------------------------------------------------------------
# AgyNotFoundError の伝播
# ---------------------------------------------------------------------------


@patch(
    "tools.agy_client.resolve_agy_executable",
    side_effect=AgyNotFoundError("agy が見つかりません"),
)
def test_run_agy_text_propagates_not_found_error(mock_resolve: MagicMock) -> None:
    """resolve_agy_executable が AgyNotFoundError を送出した場合、run_agy_text がそのまま伝播することを検証する。"""
    with pytest.raises(AgyNotFoundError):
        run_agy_text("テストプロンプト")


@patch(
    "tools.agy_client.resolve_agy_executable",
    side_effect=AgyNotFoundError("agy が見つかりません"),
)
def test_run_agy_in_workdir_propagates_not_found_error(mock_resolve: MagicMock) -> None:
    """resolve_agy_executable が AgyNotFoundError を送出した場合、run_agy_in_workdir がそのまま伝播することを検証する。"""
    with pytest.raises(AgyNotFoundError):
        run_agy_in_workdir("編集指示", cwd="/tmp/satellite-worktree")


# ---------------------------------------------------------------------------
# エラー分類 (AgyAuthError / AgyQuotaError)
# ---------------------------------------------------------------------------


def test_classify_agy_exit_auth_keywords() -> None:
    """認証エラーのキーワードを含むメッセージは AgyAuthError に分類されることを検証する。"""
    for msg in [
        "Error: Unauthorized access (status 401)",
        "Authentication failed: invalid api key",
        "User is not logged in",
        "Token expired. Please login again.",
        "Permission denied (HTTP 403)",
    ]:
        err = classify_agy_exit(msg, returncode=1)
        assert isinstance(err, AgyAuthError)
        assert err.returncode == 1


def test_classify_agy_exit_quota_keywords() -> None:
    """クォータ・レート制限のキーワードを含むメッセージは AgyQuotaError に分類されることを検証する。"""
    for msg in [
        "Error: Resource exhausted (status 429)",
        "Rate limit exceeded: too many requests",
        "Daily quota exceeded for user",
        "Credit limit reached (error 429)",
        "Credits exhausted",
    ]:
        err = classify_agy_exit(msg, returncode=1)
        assert isinstance(err, AgyQuotaError)
        assert err.returncode == 1


def test_classify_agy_exit_generic_error() -> None:
    """認証やクォータに該当しない一般エラーは通常の AgyExitError に分類されることを検証する。"""
    err = classify_agy_exit("Syntax error in template file", returncode=2)
    assert type(err) is AgyExitError
    assert err.returncode == 2


@patch("tools.agy_client.subprocess.Popen")
@patch(
    "tools.agy_client.authorize_agy_execution",
    side_effect=AgyPolicyDeniedError("AGY_POLICY_DENIED: blocked"),
)
def test_run_agy_text_denied_before_popen(mock_authorize: MagicMock, mock_popen: MagicMock) -> None:
    """外部送信ポリシー拒否時はagyプロセスを起動しない。"""
    with pytest.raises(AgyPolicyDeniedError, match="AGY_POLICY_DENIED"):
        run_agy_text("blocked")

    mock_authorize.assert_called_once()
    mock_popen.assert_not_called()


@patch("tools.agy_client.subprocess.Popen")
@patch(
    "tools.agy_client.authorize_agy_execution",
    side_effect=AgyPolicyDeniedError("AGY_POLICY_DENIED: blocked"),
)
def test_run_agy_in_workdir_denied_before_popen(
    mock_authorize: MagicMock, mock_popen: MagicMock
) -> None:
    """外部送信ポリシー拒否時は作業ツリー編集プロセスを起動しない。"""
    with pytest.raises(AgyPolicyDeniedError, match="AGY_POLICY_DENIED"):
        run_agy_in_workdir("instruction", cwd="/tmp/satellite", project_key="BLOCKED")

    mock_authorize.assert_called_once()
    mock_popen.assert_not_called()

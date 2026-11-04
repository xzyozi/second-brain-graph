"""agy (Antigravity CLI) をサブプロセスとして起動する共通の薄いクライアントモジュール.

このモジュールは agy の実行ファイル解決・起動・タイムアウト処理・終了コード判定のみを
担う。プロンプトの組み立てや一時ディレクトリの管理は呼び出し側の責務とする (YAGNI)。
"""

import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("agy_client")


class AgyError(Exception):
    """agy 実行時の基底例外."""

    pass


class AgyNotFoundError(AgyError):
    """agy の実行ファイルが見つからない場合の例外."""

    pass


class AgyTimeoutError(AgyError):
    """agy の実行がタイムアウトした場合の例外.

    メッセージには必ず部分文字列 'timed out' を含める
    (呼び出し側の LLM_TIMEOUT 判定が部分文字列一致のため)。
    """

    pass


class AgyExitError(AgyError):
    """agy が非0の終了コードで終了した場合の例外."""

    def __init__(self, message: str, returncode: int) -> None:
        super().__init__(message)
        self.returncode = returncode


def resolve_agy_executable() -> str:
    """agy 実行ファイルのパスを解決する.

    1. shutil.which("agy.exe") / shutil.which("agy") の順で PATH から探す。
    2. 見つからなければ既知の配置先を順に確認する。
    3. すべて見つからなければ AgyNotFoundError を送出する
       (フォールバックで "agy" 文字列を返さない。呼び出し元が未導入を確実に検知できるようにするため)。
    """
    for candidate in ("agy.exe", "agy"):
        found = shutil.which(candidate)
        if found:
            return found

    known_paths = [
        Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        Path.home() / ".cargo" / "bin" / "agy.exe",
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)

    raise AgyNotFoundError(
        "agy の実行ファイルが見つかりません。PATH または既知の配置先を確認してください。"
    )


def _terminate_process_tree(proc: "subprocess.Popen[str]") -> None:
    """タイムアウトした子プロセスとその子孫プロセスをまとめて終了する."""
    pid = proc.pid
    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
            logger.warning(
                f"agy プロセスツリーを終了しました (taskkill /F /T, pid={pid}, rc={result.returncode})"
            )
        except Exception as e:
            logger.warning(f"agy プロセスツリーの終了に失敗しました (taskkill, pid={pid}): {e}")
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            logger.warning(f"agy プロセスグループを終了しました (killpg, pid={pid})")
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"agy プロセスグループの終了に失敗しました (killpg, pid={pid}): {e}")
    try:
        proc.kill()
    except OSError:
        pass


def _run_agy(prompt: str, *, cwd: Optional[str], timeout: int) -> str:
    """agy を非対話で起動し、stdout(str)を返す.

    - resolve_agy_executable() で実行ファイルを解決する。見つからなければ
      AgyNotFoundError をそのまま呼び出し元へ伝播する。
    - 終了コードが非0なら AgyExitError を送出する。
    - タイムアウト時は AgyTimeoutError を送出する。
    """
    agy_exe = resolve_agy_executable()
    cmd = [agy_exe, "--dangerously-skip-permissions", "-p", prompt]

    popen_kwargs: dict[str, Any] = {}
    if not sys.platform.startswith("win"):
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        proc.wait()
        raise AgyTimeoutError(f"agy execution timed out after {timeout} seconds") from None

    if proc.returncode != 0:
        raise AgyExitError(
            f"agy process failed with returncode {proc.returncode}: {(stderr or '')[:500]}",
            returncode=proc.returncode,
        )

    return stdout or ""


def run_agy_text(prompt: str, *, timeout: int = 180, cwd: Optional[str] = None) -> str:
    """agy をテキスト応答用に起動する (読み取り専用な問い合わせ等向け)."""
    return _run_agy(prompt, cwd=cwd, timeout=timeout)


def run_agy_in_workdir(prompt: str, *, cwd: str, timeout: int = 1200) -> str:
    """agy を指定ワークツリーで編集実行用に起動する.

    cwd は必須 (衛星ワークツリー)。空文字列や None の場合は ValueError を送出する。
    """
    if not cwd:
        raise ValueError("run_agy_in_workdir requires a non-empty cwd")
    return _run_agy(prompt, cwd=cwd, timeout=timeout)

#!/usr/bin/env python3
"""
tools/aider_runner.py - Aider CLI 実行ラッパーモジュール (TFG-0004 仕様準拠).
"""

import os
import subprocess
from pathlib import Path
from typing import List, Optional


class AiderRunError(Exception):
    """Aider 実行時のタイムアウトおよびシステムエラー例外"""
    pass


class GitDiffError(Exception):
    """Git diff 取得失敗時の例外 (fail-closed 契約)"""
    pass


def get_git_diff(cwd: Optional[str] = None) -> str:
    """現在の Git 作業ツリーの差分を取得する。失敗時は GitDiffError を送出する (fail-closed)."""
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if res.returncode != 0:
            raise GitDiffError(f"git diff command failed with returncode {res.returncode}: {res.stderr}")
        return res.stdout
    except Exception as e:
        if isinstance(e, GitDiffError):
            raise
        raise GitDiffError(f"Failed to execute git diff: {e}") from e


def run_aider(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str] = None,
    model: str = "ollama/qwen2.5-coder:7b-instruct",
    timeout: int = 300,
) -> bool:
    """Aider CLI を subprocess 経由で非対話形式で実行する。
    - Ollama API ベースが指定されている場合、末尾の /v1 サフィックスを自動除去する。
    - タイムアウト時は AiderRunError を発生させる。
    - 対象ファイルが存在しない場合は FileNotFoundError を発生させる。
    """
    if cwd:
        cwd_path = Path(cwd)
        for tf in target_files:
            abs_path = cwd_path / tf
            if not abs_path.exists():
                raise FileNotFoundError(f"Target file does not exist: {abs_path}")

    env = os.environ.copy()

    # Ollama API ベースサフィックスの自動サニタイズ
    if "OLLAMA_API_BASE" in env:
        api_base = env["OLLAMA_API_BASE"]
        if api_base.endswith("/v1"):
            env["OLLAMA_API_BASE"] = api_base[:-3]
        elif api_base.endswith("/v1/"):
            env["OLLAMA_API_BASE"] = api_base[:-4]

    cmd = [
        "aider",
        "--model", model,
        "--no-auto-commits",
        "--yes-always",
        "--message", instruction,
    ] + target_files

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired as e:
        raise AiderRunError(f"Aider execution timed out after {timeout} seconds") from e
    except Exception as e:
        raise AiderRunError(f"Failed to run Aider CLI: {e}") from e

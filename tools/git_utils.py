"""Git 操作に関する汎用ユーティリティモジュール."""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger("git_utils")


class GitDiffError(Exception):
    """Git diff 取得失敗時の例外 (fail-closed 契約)."""

    pass


def get_git_diff(cwd: Optional[str] = None, base_branch: Optional[str] = None) -> str:
    """現在の Git 作業ツリーの差分を取得する。失敗時は GitDiffError を送出する (fail-closed).

    - 新規作成された未追跡ファイル (untracked files) も git diff 対象に含めるため intent-to-add (git add -N .) を設定する。
    - 初期コミット前のリポジトリ等で HEAD が存在しない場合はフォールバックして差分を取得する。
    - HEAD との差分が空の場合で base_branch が指定されている場合、ブランチ全体の差分 (origin/{base_branch}...HEAD) をフォールバック取得する。
    """
    try:
        # 新規作成された未追跡ファイル (untracked files) も git diff 対象に含めるため intent-to-add を設定
        subprocess.run(
            ["git", "add", "-N", "."],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if res.returncode != 0:
            err_msg = res.stderr.lower()
            if (
                "bad revision" in err_msg
                or "ambiguous argument 'head'" in err_msg
                or "unknown revision" in err_msg
            ):
                # Fallback for initial commit (no HEAD)
                # Capture both staged and unstaged changes since 'git diff HEAD' is unavailable.
                diffs = []
                cached_res = subprocess.run(
                    ["git", "diff", "--cached"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if cached_res.returncode == 0 and cached_res.stdout:
                    diffs.append(cached_res.stdout)

                unstaged_res = subprocess.run(
                    ["git", "diff"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if unstaged_res.returncode == 0 and unstaged_res.stdout:
                    diffs.append(unstaged_res.stdout)

                if cached_res.returncode == 0 and unstaged_res.returncode == 0:
                    return "\n".join(diffs)
            raise GitDiffError(
                f"git diff command failed with returncode {res.returncode}: {res.stderr}"
            )

        diff_out = res.stdout
        # HEAD との差分が空で base_branch が指定されている場合、コミット済み差分をフォールバック取得
        if not diff_out.strip() and base_branch:
            for branch_ref in [f"origin/{base_branch}...HEAD", f"{base_branch}...HEAD"]:
                branch_diff = subprocess.run(
                    ["git", "diff", branch_ref],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if branch_diff.returncode == 0 and branch_diff.stdout.strip():
                    return branch_diff.stdout

        return diff_out
    except Exception as e:
        if isinstance(e, GitDiffError):
            raise
        raise GitDiffError(f"Failed to execute git diff: {e}") from e

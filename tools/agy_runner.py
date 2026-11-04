"""agy によるコード編集実行の薄いランナー.

既存の Aider 実行 (tools/aider_runner.run_aider) と code_node から見た外側契約を
揃えるため、AgyRunError は AiderRunError のサブクラスとする。これにより、
code_node の既存の `except AiderRunError` がそのまま agy の例外も捕捉できる
(#128 で CoderRunError へ整理するまでの暫定措置、SBOS-DD-004 §3.2)。
"""

import logging
from typing import List, Optional

from tools.agy_client import (
    AgyError,
    AgyExitError,
    AgyNotFoundError,
    AgyTimeoutError,
    run_agy_in_workdir,
)
from tools.aider_runner import AiderRunError
from tools.edit_guard import (
    MotherRepositoryProtectionError,
    cleanup_unauthorized_aider_artifacts,
    validate_cwd_is_satellite,
    warn_if_working_tree_dirty,
)

logger = logging.getLogger("agy_runner")


class AgyRunError(AiderRunError):
    """agy 実行時のエラー。code_node から見た契約は AiderRunError と同一とする。"""

    pass


def run_agy_edit(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str],
    *,
    timeout: int = 1200,
) -> bool:
    """agy にコード編集を行わせる.

    - cwd は必須 (衛星ワークツリー)。母艦でないことの検証は呼び出し側の責務とする。
    - 成功・失敗にかかわらず、target_files 外の変更は cleanup_unauthorized_aider_artifacts で
      後始末する (SBOS-DD-004 §2.1。この関数は git status のみに依存し engine 非依存)。
    - タイムアウトのメッセージには 'timed out' を含む (AgyTimeoutError のメッセージをそのまま使う)。
      code_node の LLM_TIMEOUT 判定が部分文字列一致のため。
    """
    if not cwd:
        raise AgyRunError("run_agy_edit requires a non-empty cwd")

    try:
        validate_cwd_is_satellite(cwd)
    except MotherRepositoryProtectionError as e:
        raise AgyRunError(f"Security violation: {e}") from e

    warn_if_working_tree_dirty(cwd, target_files)

    try:
        run_agy_in_workdir(instruction, cwd=cwd, timeout=timeout)
        return True
    except AgyTimeoutError as e:
        raise AgyRunError(str(e)) from e
    except AgyNotFoundError as e:
        raise AgyRunError(f"agy is not available: {e}") from e
    except AgyExitError as e:
        raise AgyRunError(str(e)) from e
    except AgyError as e:
        raise AgyRunError(str(e)) from e
    finally:
        handled = cleanup_unauthorized_aider_artifacts(cwd, target_files)
        if handled:
            logger.warning(f"[agy_runner] Reverted/removed files outside target_files: {handled}")

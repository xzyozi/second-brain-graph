"""agy によるコード編集実行の薄いランナー.

コード編集エンジンの実行例外として CoderRunError を定義し、AgyRunError はそのサブクラスとする。
"""

import logging
from typing import List, Optional

from tools.backends.agy_client import (
    AgyError,
    AgyExitError,
    AgyNotFoundError,
    AgyTimeoutError,
    run_agy_in_workdir,
)
from tools.backends.agy_policy import AgyPolicyDeniedError
from tools.core.edit_guard import (
    MotherRepositoryProtectionError,
    cleanup_unauthorized_aider_artifacts,
    validate_cwd_is_satellite,
    warn_if_working_tree_dirty,
)

logger = logging.getLogger("agy_runner")


class CoderRunError(Exception):
    """コード編集エンジンの実行時エラー（タイムアウト・プロセス失敗等）."""

    pass


class AgyRunError(CoderRunError):
    """agy 実行時のエラー."""

    pass


def run_agy_edit(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str],
    *,
    timeout: int = 1200,
    allowed_new_file_globs: Optional[List[str]] = None,
    project_key: Optional[str] = None,
) -> bool:
    """agy にコード編集を行わせる.

    - cwd は必須 (衛星ワークツリー)。母艦でないことの検証は呼び出し側の責務とする。
    - 成功・失敗にかかわらず、target_files 外の変更は cleanup_unauthorized_aider_artifacts で
      後始末する (SBOS-DD-004 §2.1。この関数は git status のみに依存し engine 非依存)。
    - allowed_new_file_globs にマッチする未追跡ファイルは許可・保持される。
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
        policy_denied = False
        try:
            run_agy_in_workdir(
                instruction,
                cwd=cwd,
                timeout=timeout,
                project_key=project_key,
            )
        except AgyPolicyDeniedError as e:
            policy_denied = True
            raise AgyRunError(str(e)) from e
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
        if policy_denied:
            handled = []
        elif allowed_new_file_globs is not None:
            handled = cleanup_unauthorized_aider_artifacts(
                cwd, target_files, allowed_new_file_globs=allowed_new_file_globs
            )
        else:
            handled = cleanup_unauthorized_aider_artifacts(cwd, target_files)
        if handled:
            logger.warning(f"[agy_runner] Reverted/removed files outside target_files: {handled}")

"""agy 外部送信の認可ポリシー.

agy はクラウド側のモデルへプロンプトや作業ツリーの内容を送るため、
実行前に project key 単位の認可を行う。ファイル書き込み境界は edit_guard、
認証・クォータは agy_client の責務であり、このモジュールでは扱わない。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from tools.config_loader import AgyExternalSendConfig, get_backend_execution_config
from tools.edit_guard import detect_secret_files
from tools.metadata_store import resolve_project_from_cwd

AgyOperation = Literal["text", "edit", "review"]


class AgyPolicyDeniedError(Exception):
    """agy への外部送信がポリシーで拒否された場合の例外."""

    pass


@dataclass(frozen=True)
class AgyExecutionContext:
    """agy実行の認可に必要な最小コンテキスト."""

    project_key: Optional[str]
    operation: AgyOperation
    cwd: Optional[Path]


def _normalized_project_key(project_key: Optional[str]) -> Optional[str]:
    if project_key is None:
        return None
    value = project_key.strip().upper()
    return value or None


def _deny(reason: str, context: AgyExecutionContext) -> None:
    key = context.project_key or "<missing>"
    raise AgyPolicyDeniedError(
        f"AGY_POLICY_DENIED: project_key={key}, operation={context.operation}, reason={reason}"
    )


def authorize_agy_execution(
    *,
    project_key: Optional[str],
    operation: AgyOperation,
    cwd: Optional[str | Path] = None,
    policy_config: Optional[AgyExternalSendConfig] = None,
) -> AgyExecutionContext:
    """agyへの外部送信を許可する。拒否時はfail-closedで例外を送出する。

    移行互換の既定値は ``allow_all`` とし、既存のroutes切替を停止させない。
    ``allowlist`` に変更した場合は、検証済みproject keyだけを許可する。
    reject_secret_files=True の場合、作業ツリー内の秘密ファイル存在も拒否する。
    """
    config = policy_config or get_backend_execution_config().agy_external_send
    normalized_key = _normalized_project_key(project_key)
    context = AgyExecutionContext(
        project_key=normalized_key,
        operation=operation,
        cwd=Path(cwd).resolve() if cwd else None,
    )

    if config.mode == "allowlist":
        allowed = {_normalized_project_key(key) for key in config.allowed_project_keys}
        if normalized_key is None or normalized_key not in allowed:
            _deny("project key is not in the external-send allowlist", context)

    if config.reject_secret_files and context.cwd is not None:
        secrets = detect_secret_files(context.cwd)
        if secrets:
            _deny("secret-like files exist in the workspace", context)

    if operation == "edit" and context.cwd is not None and normalized_key is not None:
        resolved_key = resolve_project_from_cwd(context.cwd)
        if config.mode == "allowlist" and resolved_key is None:
            _deny("cwd is not registered to a project key", context)
        if resolved_key is not None and _normalized_project_key(resolved_key) != normalized_key:
            _deny("cwd does not match project key", context)

    return context

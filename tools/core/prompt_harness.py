"""実行時のエージェント役割・プロンプトを解決するハーネス。

呼び出し側は role と intent の組み合わせだけを指定し、具体的な
system prompt の配置や prompt version の扱いを意識しない。
"""

import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, List, Optional, Tuple

from tools.workspace.config_loader import PromptConfig, load_prompt_config

logger = logging.getLogger("prompt_harness")


@dataclass(frozen=True)
class ResolvedPrompt:
    """実行に使う prompt と監査用メタデータ。"""

    role: str
    intent: str
    prompt_id: str
    version: str
    system_prompt: str
    digest: str


# role はモデル設定上の役割、section は prompt.yaml 上のペルソナ役割を表す。
# test_feedback は planner モデルを使うが、ペルソナは advisor として定義する。
_PROMPT_BINDINGS: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("planner", "spec_draft"): ("planner", "spec_draft_system"),
    ("planner", "test_feedback"): ("advisor", "test_feedback_system"),
    ("reviewer", "code_review"): ("reviewer", "code_review_system"),
    ("reviewer", "failure_analysis"): ("reviewer", "failure_analysis_system"),
}

# コード編集エンジンごとに、指示文へ追加する coder ブロックを切り替える。
# 現在は agy のみサポート (Issue #128)。
_CODER_ENGINE_RULES: Dict[str, str] = {
    "agy": "agy_edit_rules",
}


def engine_for_backend(backend: str) -> str:
    """profile.backend からコード編集エンジン名を決める。

    現在は agy のみサポート (Issue #128)。
    """
    if backend == "agy":
        return "agy"
    return "agy"


def _log_resolved(prompt_id: str, version: str, digest: str) -> None:
    """監査用に prompt の識別子だけをログへ残す。本文は記録しない。"""
    logger.info("Prompt resolved: id=%s version=%s digest=%s", prompt_id, version, digest)


def resolve_prompt(
    role: str,
    intent: str,
    prompt_config: Optional[PromptConfig] = None,
) -> ResolvedPrompt:
    """role / intent に対応する system prompt を SSOT から解決する。

    未定義の組み合わせは、呼び出し側が別のペルソナを暗黙に使わないよう
    fail-closed で拒否する。prompt_config はテスト用の差し替え seam である。
    """
    binding = _PROMPT_BINDINGS.get((role, intent))
    if binding is None:
        supported = ", ".join(
            f"{bound_role}/{bound_intent}" for bound_role, bound_intent in sorted(_PROMPT_BINDINGS)
        )
        raise ValueError(
            f"Unsupported prompt binding '{role}/{intent}'. Supported bindings: {supported}"
        )

    config = prompt_config or load_prompt_config()
    section_name, field_name = binding
    section = getattr(config, section_name)
    system_prompt = getattr(section, field_name)
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError(f"Prompt '{section_name}.{field_name}' must be a non-empty string")

    version = str(getattr(config, "version", "1.0"))
    digest = sha256(system_prompt.encode("utf-8")).hexdigest()[:16]
    prompt_id = f"{section_name}.{field_name}"
    _log_resolved(prompt_id, version, digest)
    return ResolvedPrompt(
        role=role,
        intent=intent,
        prompt_id=prompt_id,
        version=version,
        system_prompt=system_prompt.strip(),
        digest=digest,
    )


def build_coder_instruction(
    *,
    engine: str,
    base_instruction: str,
    impl_plan: Optional[str],
    target_files: List[str],
    feedback: Optional[str],
    prompt_config: Optional[PromptConfig] = None,
) -> str:
    """コード編集エンジンへ渡す指示文を組み立てる。

    構成は、基本指示、実装計画、編集範囲の制限、実行戦略、エンジン別の規則、
    フィードバックの順とする。エンジン別の規則だけがエンジンで異なり、
    それ以外は共通である。未知のエンジンは fail-closed で拒否する。
    """
    rules_field = _CODER_ENGINE_RULES.get(engine)
    if rules_field is None:
        supported = ", ".join(sorted(_CODER_ENGINE_RULES))
        raise ValueError(f"Unsupported coder engine '{engine}'. Supported engines: {supported}")

    config = prompt_config or load_prompt_config()
    coder = config.coder
    engine_rules = getattr(coder, rules_field)
    if not isinstance(engine_rules, str) or not engine_rules.strip():
        raise ValueError(f"Prompt 'coder.{rules_field}' must be a non-empty string")

    instruction = base_instruction
    if impl_plan:
        instruction += f"\n\nImplementation Plan:\n{impl_plan}"

    if target_files:
        target_files_str = ", ".join(target_files)
        scope = coder.scope_restriction_template.strip().replace(
            "{target_files_str}", target_files_str
        )
        instruction += f"\n\n{scope}"

    instruction += f"\n\n{coder.execution_strategy_step_by_step.strip()}"
    instruction += f"\n\n{engine_rules.strip()}"

    if feedback:
        instruction += f"\n\nFeedback:\n{feedback}"

    version = str(getattr(config, "version", "1.0"))
    digest = sha256(engine_rules.encode("utf-8")).hexdigest()[:16]
    _log_resolved(f"coder.{rules_field}", version, digest)
    return instruction

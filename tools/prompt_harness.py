"""実行時のエージェント役割・プロンプトを解決するハーネス。

呼び出し側は role と intent の組み合わせだけを指定し、具体的な
system prompt の配置や prompt version の扱いを意識しない。
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, Optional, Tuple

from tools.config_loader import PromptConfig, load_prompt_config


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
    return ResolvedPrompt(
        role=role,
        intent=intent,
        prompt_id=f"{section_name}.{field_name}",
        version=version,
        system_prompt=system_prompt.strip(),
        digest=digest,
    )

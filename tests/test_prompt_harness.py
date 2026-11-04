"""prompt.yaml を実行時の役割解決へ接続するハーネスの契約テスト。"""

import pytest

from tools.config_loader import (
    AdvisorPromptConfig,
    CoderPromptConfig,
    PlannerPromptConfig,
    PromptConfig,
    ReviewerPromptConfig,
)
from tools.prompt_harness import resolve_prompt


def make_prompt_config() -> PromptConfig:
    return PromptConfig(
        version="test-1",
        planner=PlannerPromptConfig(spec_draft_system="planner prompt"),
        coder=CoderPromptConfig(
            scope_restriction_template="scope",
            execution_strategy_step_by_step="strategy",
            strict_output_rules="aider output",
            read_only_test_enforcement="read only",
        ),
        advisor=AdvisorPromptConfig(test_feedback_system="advisor prompt"),
        reviewer=ReviewerPromptConfig(
            code_review_system="review prompt",
            failure_analysis_system="failure prompt",
        ),
    )


def test_resolve_prompt_maps_role_and_intent_to_prompt_section() -> None:
    config = make_prompt_config()

    result = resolve_prompt("planner", "test_feedback", prompt_config=config)

    assert result.prompt_id == "advisor.test_feedback_system"
    assert result.system_prompt == "advisor prompt"
    assert result.version == "test-1"
    assert len(result.digest) == 16


def test_resolve_prompt_supports_failure_analysis() -> None:
    result = resolve_prompt("reviewer", "failure_analysis", prompt_config=make_prompt_config())

    assert result.prompt_id == "reviewer.failure_analysis_system"
    assert result.system_prompt == "failure prompt"


def test_resolve_prompt_rejects_unknown_binding() -> None:
    with pytest.raises(ValueError, match="Unsupported prompt binding"):
        resolve_prompt("coder", "code_review", prompt_config=make_prompt_config())

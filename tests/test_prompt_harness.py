"""prompt.yaml を実行時の役割解決へ接続するハーネスの契約テスト。"""

from typing import List, Optional

import pytest

from tools.config_loader import (
    AdvisorPromptConfig,
    CoderPromptConfig,
    PlannerPromptConfig,
    PromptConfig,
    ReviewerPromptConfig,
    load_prompt_config,
)
from tools.prompt_harness import build_coder_instruction, engine_for_backend, resolve_prompt


def make_prompt_config() -> PromptConfig:
    return PromptConfig(
        version="test-1",
        planner=PlannerPromptConfig(spec_draft_system="planner prompt"),
        coder=CoderPromptConfig(
            scope_restriction_template="[SCOPE] only {target_files_str}\n",
            execution_strategy_step_by_step="[STRATEGY]\n",
            strict_output_rules="[AIDER RULES]\n",
            agy_edit_rules="[AGY RULES]\n",
            read_only_test_enforcement="read only",
        ),
        advisor=AdvisorPromptConfig(test_feedback_system="advisor prompt"),
        reviewer=ReviewerPromptConfig(
            code_review_system="review prompt",
            failure_analysis_system="failure prompt",
        ),
    )


def legacy_aider_instruction(
    base: str, plan: Optional[str], targets: List[str], feedback: Optional[str]
) -> str:
    """ハーネス導入前に code_node が直書きで組み立てていた Aider 向け指示文。"""
    instruction = base
    if plan:
        instruction += f"\n\nImplementation Plan:\n{plan}"
    if targets:
        target_files_str = ", ".join(targets)
        instruction += (
            "\n\n[SCOPE RESTRICTION]\nYou are ONLY permitted to modify the following files: "
            f"{target_files_str}. DO NOT modify, touch, or create any other files."
        )
    instruction += (
        "\n\n[EXECUTION STRATEGY - STEP-BY-STEP]\n"
        "Follow a strict 2-phase approach:\n"
        "1. Phase 1 (Core Logic): Focus first on implementing the core logic, classes, and "
        "exceptions under `src/`.\n"
        "2. Phase 2 (Tests & Refinement): Then create/update tests under `tests/` and refine "
        "until all requirements pass.\n\n"
        "[STRICT AIDER OUTPUT FORMAT RULES]\n"
        "- Output ONLY the target file modifications.\n"
        "- For each file, the FIRST line must be the exact relative file path without "
        "backticks, quotes, or markdown formatting (e.g. src/utils/file_utils.py).\n"
        "- Follow immediately with a markdown code block containing the complete source code.\n"
        "- DO NOT output any introductory text, conversational filler, greetings, thoughts, or "
        "explanations outside code blocks.\n"
        "- DO NOT replace implementations or tests with ellipses (...), pass, or placeholder "
        "comments. Always write complete, runnable Python code.\n"
        "- DO NOT create or modify any files not listed in Target Files."
    )
    if feedback:
        instruction += f"\n\nFeedback:\n{feedback}"
    return instruction


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


def test_engine_for_backend_maps_agy_and_defaults_to_aider() -> None:
    assert engine_for_backend("agy") == "agy"
    assert engine_for_backend("ollama") == "aider"
    assert engine_for_backend("llama_server") == "aider"


def test_build_coder_instruction_uses_engine_specific_rules() -> None:
    config = make_prompt_config()
    targets = ["src/a.py", "tests/test_a.py"]

    aider = build_coder_instruction(
        engine="aider",
        base_instruction="Implement X",
        impl_plan="the plan",
        target_files=targets,
        feedback=None,
        prompt_config=config,
    )
    agy = build_coder_instruction(
        engine="agy",
        base_instruction="Implement X",
        impl_plan="the plan",
        target_files=targets,
        feedback=None,
        prompt_config=config,
    )

    assert "[AIDER RULES]" in aider and "[AGY RULES]" not in aider
    assert "[AGY RULES]" in agy and "[AIDER RULES]" not in agy
    assert "[SCOPE] only src/a.py, tests/test_a.py" in aider
    assert "[SCOPE] only src/a.py, tests/test_a.py" in agy
    assert "Implementation Plan:\nthe plan" in agy


def test_build_coder_instruction_omits_optional_sections() -> None:
    result = build_coder_instruction(
        engine="aider",
        base_instruction="Apply edits",
        impl_plan=None,
        target_files=[],
        feedback=None,
        prompt_config=make_prompt_config(),
    )

    assert "Implementation Plan" not in result
    assert "[SCOPE]" not in result
    assert "Feedback:" not in result


def test_build_coder_instruction_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unsupported coder engine"):
        build_coder_instruction(
            engine="unknown",
            base_instruction="x",
            impl_plan=None,
            target_files=[],
            feedback=None,
            prompt_config=make_prompt_config(),
        )


@pytest.mark.parametrize(
    ("base", "plan", "targets", "feedback"),
    [
        ("Implement X", "plan text", ["src/a.py", "tests/test_a.py"], "fix this"),
        ("Apply edits", None, ["src/a.py"], None),
        ("Apply edits", "plan", [], "fb"),
        ("Apply edits", None, [], None),
        ("Do {x}", "plan {y}", ["src/{z}.py"], "{w}"),
    ],
)
def test_aider_instruction_is_byte_identical_to_legacy_code_node(
    base: str, plan: Optional[str], targets: List[str], feedback: Optional[str]
) -> None:
    """実運用の prompt.yaml から組み立てた Aider 指示文が、導入前の直書きと一致すること。"""
    actual = build_coder_instruction(
        engine="aider",
        base_instruction=base,
        impl_plan=plan,
        target_files=targets,
        feedback=feedback,
        prompt_config=load_prompt_config(),
    )

    assert actual == legacy_aider_instruction(base, plan, targets, feedback)

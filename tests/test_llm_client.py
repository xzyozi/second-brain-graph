"""Tests for tools/llm_client.py and config_loader parameters integration."""

import os
from unittest.mock import MagicMock, patch

from tools.config_loader import ProfileConfig, get_model_params
from tools.llm_client import call_llm


def test_get_model_params() -> None:
    planner_params = get_model_params("planner")
    assert planner_params["max_tokens"] == 35000
    assert planner_params["temperature"] == 0.2

    coder_params = get_model_params("coder")
    assert coder_params["max_tokens"] == 35000


@patch("tools.llm_client.OpenAI")
@patch("tools.llm_client.get_coordinator")
@patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:11434"})
def test_call_llm_with_dynamic_params(
    mock_get_coordinator: MagicMock, mock_openai_class: MagicMock
) -> None:
    mock_coordinator = MagicMock()
    from tools.config_loader import ProfileConfig

    dummy_profile = ProfileConfig(
        backend="ollama",
        model="gemma-4-12B-it-qat-UD-Q4_K_XL",
        openai_endpoint="http://localhost:11434/v1",
        ollama_management_endpoint="http://localhost:11434",
    )
    mock_coordinator.execute.side_effect = lambda intent, req: req["action"](dummy_profile)
    mock_get_coordinator.return_value = mock_coordinator

    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"verdict": "LGTM"}'))]
    mock_client.chat.completions.create.return_value = mock_response

    res = call_llm("planner", "System Prompt", "User Prompt", expect_json=True, intent="spec_draft")

    assert res == {"verdict": "LGTM"}
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args.kwargs

    assert kwargs["model"] == "gemma-4-12B-it-qat-UD-Q4_K_XL"
    assert kwargs["max_tokens"] == 35000
    assert kwargs["temperature"] == 0.2


@patch("tools.llm_client.OpenAI")
@patch("tools.llm_client.get_coordinator")
@patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:11434"})
def test_call_llm_fallback_intent(
    mock_get_coordinator: MagicMock, mock_openai_class: MagicMock
) -> None:
    mock_coordinator = MagicMock()
    from tools.config_loader import ProfileConfig

    dummy_profile = ProfileConfig(
        backend="ollama",
        model="gemma-4-12B-it-qat-UD-Q4_K_XL",
        openai_endpoint="http://localhost:11434/v1",
        ollama_management_endpoint="http://localhost:11434",
    )
    mock_coordinator.execute.side_effect = lambda intent, req: req["action"](dummy_profile)
    mock_get_coordinator.return_value = mock_coordinator

    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"verdict": "LGTM"}'))]
    mock_client.chat.completions.create.return_value = mock_response

    # Calling call_llm without intent, role="planner" should fallback to intent="spec_draft"
    res = call_llm("planner", "System Prompt", "User Prompt", expect_json=True)

    assert res == {"verdict": "LGTM"}
    # Verify fallback intent 'spec_draft' was used
    mock_coordinator.execute.assert_called_once()
    assert mock_coordinator.execute.call_args[0][0] == "spec_draft"


# ---------------------------------------------------------------------------
# expect_json=True 時の JSON フォールバック分岐
# ローカル LLM は前後にテキストが混ざる/整形されない出力を返しがちなため、
# call_llm 側の抽出・フォールバックロジックを個別に検証する。
# ---------------------------------------------------------------------------
def _run_call_llm_with_content(raw_content: str, expect_json: bool = True) -> dict:
    """指定した生出力を返す OpenAI をモックし、call_llm の戻り値を得るヘルパー。"""
    with (
        patch("tools.llm_client.OpenAI") as mock_openai_class,
        patch("tools.llm_client.get_coordinator") as mock_get_coordinator,
        patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:11434"}),
    ):
        dummy_profile = ProfileConfig(
            backend="ollama",
            model="test-model",
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
        coordinator = MagicMock()
        coordinator.execute.side_effect = lambda _intent, req: req["action"](dummy_profile)
        mock_get_coordinator.return_value = coordinator

        client = MagicMock()
        mock_openai_class.return_value = client
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=raw_content))]
        client.chat.completions.create.return_value = response

        return call_llm("reviewer", "system", "user", expect_json=expect_json, intent="code_review")


def test_call_llm_extracts_json_embedded_in_text() -> None:
    """前後にテキストが混在していても、埋め込まれた JSON オブジェクトを抽出することを確認する。"""
    raw = 'ここが結果です:\n{"verdict": "LGTM", "comments": []}\n以上。'
    result = _run_call_llm_with_content(raw)

    assert result["verdict"] == "LGTM"
    assert result["comments"] == []


def test_call_llm_falls_back_when_output_is_not_json() -> None:
    """JSON を含まない出力では changes_requested へフォールバックし raw を保持することを確認する。"""
    raw = "これはただのテキストで JSON ではありません。"
    result = _run_call_llm_with_content(raw)

    assert result["verdict"] == "changes_requested"
    assert result["raw"] == raw


def test_call_llm_falls_back_when_json_root_is_array() -> None:
    """ルートが配列 (非 dict) の場合も changes_requested へフォールバックすることを確認する。"""
    raw = "出力: [1, 2, 3]"
    result = _run_call_llm_with_content(raw)

    assert result["verdict"] == "changes_requested"
    assert result["raw"] == raw


def test_call_llm_returns_raw_when_expect_json_false() -> None:
    """expect_json=False の場合はパースせず raw をそのまま返すことを確認する。"""
    raw = '{"verdict": "LGTM"}'
    result = _run_call_llm_with_content(raw, expect_json=False)

    assert result == {"raw": raw}

"""Tests for the bunri-local LLM client Module."""

import os
from unittest.mock import MagicMock, patch

from tools.config_loader import ProfileConfig
from tools.llm_client import call_llm


@patch("tools.llm_client.OpenAI")
@patch("tools.llm_client.get_coordinator")
@patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:11434"})
def test_call_llm_uses_resolved_profile_and_model_settings(
    mock_get_coordinator: MagicMock, mock_openai_class: MagicMock
) -> None:
    profile = ProfileConfig(
        backend="ollama",
        model="test-model",
        openai_endpoint="http://localhost:11434/v1",
        ollama_management_endpoint="http://localhost:11434",
    )
    coordinator = MagicMock()
    coordinator.execute.side_effect = lambda _intent, request: request["action"](profile)
    mock_get_coordinator.return_value = coordinator

    client = MagicMock()
    mock_openai_class.return_value = client
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content='{"verdict": "LGTM"}'))]
    client.chat.completions.create.return_value = response

    result = call_llm("planner", "system", "user", expect_json=True)

    assert result == {"verdict": "LGTM"}
    assert coordinator.execute.call_args.args[0] == "spec_draft"
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["temperature"] == 0.2
    assert request["max_tokens"] == 35000


def test_call_llm_requires_a_known_intent() -> None:
    try:
        call_llm("unknown", "system", "user")
    except ValueError as error:
        assert "intent is required" in str(error)
    else:
        raise AssertionError("call_llm must reject an unknown role without an intent")

"""Tests for tools/llm_client.py and config_loader parameters integration."""

from unittest.mock import MagicMock, patch
import os
import pytest
from tools.config_loader import get_model_params
from tools.llm_client import call_llm


def test_get_model_params():
    planner_params = get_model_params("planner")
    assert planner_params["max_tokens"] == 35000
    assert planner_params["temperature"] == 0.2

    coder_params = get_model_params("coder")
    assert coder_params["max_tokens"] == 35000


@patch("tools.llm_client.OpenAI")
@patch("tools.llm_client.BackendExecutionCoordinator")
@patch.dict(os.environ, {"OPENAI_API_BASE": "http://localhost:11434"})
def test_call_llm_with_dynamic_params(mock_coordinator_class, mock_openai_class):
    mock_coordinator = MagicMock()
    from tools.config_loader import ProfileConfig
    # Execute the action immediately to test the inner logic, passing a dummy profile
    dummy_profile = ProfileConfig(backend="ollama", model="gemma-4-12B-it-qat-UD-Q4_K_XL", endpoint="http://localhost")
    mock_coordinator.execute.side_effect = lambda intent, req: req["action"](dummy_profile)
    mock_coordinator_class.return_value = mock_coordinator

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

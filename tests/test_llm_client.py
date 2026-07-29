"""Tests for tools/llm_client.py and config_loader parameters integration."""

from unittest.mock import MagicMock, patch

from tools.config_loader import get_model_params
from tools.llm_client import call_llm


def test_get_model_params():
    planner_params = get_model_params("planner")
    assert planner_params["model_name"] == "ollama/gemma4-12b-it-Q4_K_M:latest"
    assert planner_params["max_tokens"] == 35000
    assert planner_params["temperature"] == 0.2

    coder_params = get_model_params("coder")
    assert coder_params["model_name"] == "ollama/gemma-4-py_coder:latest"
    assert coder_params["max_tokens"] == 35000


@patch("litellm.completion")
def test_call_llm_with_dynamic_params(mock_completion):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"verdict": "LGTM"}'))]
    mock_completion.return_value = mock_response

    res = call_llm("planner", "System Prompt", "User Prompt", expect_json=True)

    assert res == {"verdict": "LGTM"}
    mock_completion.assert_called_once()
    kwargs = mock_completion.call_args.kwargs

    assert kwargs["model"] == "ollama/gemma4-12b-it-Q4_K_M:latest"
    assert kwargs["max_tokens"] == 35000
    assert kwargs["temperature"] == 0.2

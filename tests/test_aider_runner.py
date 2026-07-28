"""Unit tests for config_loader and aider_runner modules."""

from unittest.mock import patch
from tools.config_loader import get_model_name, load_model_config
from tools.aider_runner import run_aider


def test_load_model_config() -> None:
    """Test loading configuration file."""
    config = load_model_config()
    assert "models" in config
    assert "aider" in config


def test_get_model_name() -> None:
    """Test getting model names for roles."""
    coder_model = get_model_name("coder")
    aider_model = get_model_name("aider")
    planner_model = get_model_name("planner")

    assert "gemma" in coder_model.lower()
    assert "gemma" in aider_model.lower()
    assert "gemma" in planner_model.lower()


@patch("subprocess.run")
def test_run_aider_mock(mock_run) -> None:
    """Test run_aider function with mocked subprocess."""
    mock_run.return_value.returncode = 0

    success = run_aider(
        instruction="Fix syntax error",
        target_files=["test.py"],
    )

    assert success is True
    assert mock_run.called
    args, _ = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "aider"
    assert "--model" in cmd
    assert "ollama/gemma-4-py_coder:latest" in cmd
    assert "--no-auto-commits" in cmd

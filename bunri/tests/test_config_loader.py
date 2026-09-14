"""Tests for the bunri-local configuration Module."""

from tools.config_loader import (
    get_aider_config,
    get_backend_execution_config,
    get_config_path,
    get_model_params,
)


def test_config_path_is_bunri_local() -> None:
    config_path = get_config_path()

    assert config_path.name == "models.json"
    assert config_path.parent.name == "config"
    assert config_path.exists()


def test_model_parameters_are_loaded_from_local_config() -> None:
    params = get_model_params("planner")

    assert params["temperature"] == 0.2
    assert params["max_tokens"] == 35000


def test_backend_and_aider_configuration_are_available() -> None:
    backend = get_backend_execution_config()
    aider = get_aider_config()

    assert backend.routes["code_edit"] == "coding_ollama"
    assert aider.no_auto_commits is True

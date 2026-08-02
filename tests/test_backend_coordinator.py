"""Unit tests for tools.backend_coordinator."""

from unittest.mock import MagicMock, patch

import pytest

from tools.backend_coordinator import (
    BackendExecutionCoordinator,
    LlamaServerBackendAdapter,
)
from tools.config_loader import BackendExecutionConfig, ProfileConfig


@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_routing_ollama(mock_gpu_lease_class, mock_get_config):
    # Mock config to route 'aider_edit' to ollama
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"aider_edit": "coding_ollama"},
        profiles={
            "coding_ollama": ProfileConfig(
                backend="ollama", model="test-model", openai_endpoint="http://localhost:11434/v1", ollama_management_endpoint="http://localhost:11434"
            )
        }
    )
    mock_gpu_lease = MagicMock()
    mock_gpu_lease.__enter__ = MagicMock(return_value=mock_gpu_lease)
    mock_gpu_lease.__exit__ = MagicMock(return_value=None)
    mock_gpu_lease_class.return_value = mock_gpu_lease

    coordinator = BackendExecutionCoordinator()

    action_mock = MagicMock(return_value="success")
    request = {"action": action_mock}

    with patch("tools.backend_coordinator.OllamaBackendAdapter") as mock_adapter_class:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.execute.return_value = "success"
        mock_adapter_class.return_value = mock_adapter_instance

        result = coordinator.execute("aider_edit", request)

        # Verify GPU lease acquired and released via context manager
        mock_gpu_lease.__enter__.assert_called_once()
        mock_gpu_lease.__exit__.assert_called_once()

        # Verify adapter called
        mock_adapter_class.assert_called_once_with(mock_get_config.return_value.profiles["coding_ollama"])
        mock_adapter_instance.execute.assert_called_once_with(request)

        assert result == "success"

@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_routing_llama_server(mock_gpu_lease_class, mock_get_config):
    # Mock config to route 'spec_draft' to llama_server
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model-reasoning",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            )
        }
    )
    mock_gpu_lease = MagicMock()
    mock_gpu_lease.__enter__ = MagicMock(return_value=mock_gpu_lease)
    mock_gpu_lease.__exit__ = MagicMock(return_value=None)
    mock_gpu_lease_class.return_value = mock_gpu_lease

    coordinator = BackendExecutionCoordinator()

    action_mock = MagicMock(return_value="success")
    request = {"action": action_mock}

    with patch("tools.backend_coordinator.LlamaServerBackendAdapter") as mock_adapter_class:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.execute.return_value = "success"
        mock_adapter_class.return_value = mock_adapter_instance

        result = coordinator.execute("spec_draft", request)

        # Verify GPU lease acquired and released via context manager
        mock_gpu_lease.__enter__.assert_called_once()
        mock_gpu_lease.__exit__.assert_called_once()

        # Verify adapter called
        mock_adapter_class.assert_called_once_with(
            mock_get_config.return_value.profiles["reasoning_economy"],
            mock_get_config.return_value
        )
        mock_adapter_instance.execute.assert_called_once_with(request)

        assert result == "success"

@patch("tools.backend_coordinator.get_backend_execution_config")
def test_coordinator_unmapped_intent(mock_get_config):
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            )
        }
    )
    coordinator = BackendExecutionCoordinator()
    with pytest.raises(ValueError, match="No route mapped for intent 'unknown_intent'"):
        coordinator.execute("unknown_intent", {"action": lambda p: None})

@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_gpu_lease_timeout(mock_gpu_lease_class, mock_get_config):
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            )
        }
    )
    mock_lease = MagicMock()
    mock_lease.__enter__.side_effect = TimeoutError("Failed to acquire GPU lease within 60 seconds.")
    mock_gpu_lease_class.return_value = mock_lease

    coordinator = BackendExecutionCoordinator()
    with pytest.raises(TimeoutError, match="GPU lease"):
        coordinator.execute("spec_draft", {"action": lambda p: None})

@patch("tools.backend_coordinator.unload_ollama_models")
@patch("tools.backend_coordinator.managed_llama_server")
@patch("tools.backend_coordinator.patch_env")
def test_llama_server_adapter_skips_ollama_unload_when_no_ollama_profile(mock_patch_env, mock_managed_llama, mock_unload):
    mock_managed_llama.return_value.__enter__ = MagicMock()
    mock_managed_llama.return_value.__exit__ = MagicMock()
    mock_patch_env.return_value.__enter__ = MagicMock()
    mock_patch_env.return_value.__exit__ = MagicMock()

    config = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            )
        }
    )
    profile = config.profiles["reasoning_economy"]
    adapter = LlamaServerBackendAdapter(profile, config)
    result = adapter.execute({"action": lambda p: "ok"})

    assert result == "ok"
    mock_unload.assert_not_called()


@patch("tools.backend_coordinator.urllib.request.urlopen")
@patch("tools.backend_coordinator.managed_llama_server")
@patch("tools.backend_coordinator.patch_env")
def test_llama_server_adapter_ollama_unreachable_fallback(mock_patch_env, mock_managed_llama, mock_urlopen):
    # urlopen raising URLError (simulating Ollama unreachable)
    import urllib.error
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    mock_managed_llama.return_value.__enter__ = MagicMock()
    mock_managed_llama.return_value.__exit__ = MagicMock()
    mock_patch_env.return_value.__enter__ = MagicMock()
    mock_patch_env.return_value.__exit__ = MagicMock()

    config = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        gpu_lease_timeout=120,
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            ),
            "coding_ollama": ProfileConfig(
                backend="ollama",
                model="test-ollama",
                openai_endpoint="http://localhost:11434/v1",
                ollama_management_endpoint="http://localhost:11434"
            )
        }
    )
    profile = config.profiles["reasoning_economy"]
    adapter = LlamaServerBackendAdapter(profile, config)

    # Execute should continue normally even when unload_ollama_models logs warning on URLError
    result = adapter.execute({"action": lambda p: "ok"})

    assert result == "ok"
    mock_urlopen.assert_called()  # verifying it tried to contact Ollama
    mock_managed_llama.assert_called_once()  # verifying it continued to llama-server startup


@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_passes_gpu_lease_timeout_from_config(mock_gpu_lease_class, mock_get_config):
    # Config has custom timeout
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        gpu_lease_timeout=45,  # custom value
        routes={"spec_draft": "reasoning_economy"},
        profiles={
            "reasoning_economy": ProfileConfig(
                backend="llama_server",
                model="test-model",
                openai_endpoint="http://localhost:8080/v1",
                port=8080,
                model_path="./models/test.gguf"
            )
        }
    )
    mock_gpu_lease = MagicMock()
    mock_gpu_lease.__enter__ = MagicMock(return_value=mock_gpu_lease)
    mock_gpu_lease.__exit__ = MagicMock(return_value=None)
    mock_gpu_lease_class.return_value = mock_gpu_lease

    _coordinator = BackendExecutionCoordinator()

    # Verify GpuLeaseAdapter initialized with timeout=45
    mock_gpu_lease_class.assert_called_once_with(timeout=45)

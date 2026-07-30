"""Unit tests for tools.backend_coordinator."""

from unittest.mock import MagicMock, patch
import pytest

from tools.backend_coordinator import (
    BackendExecutionCoordinator,
    GpuLeaseAdapter,
    OllamaBackendAdapter,
    LlamaServerBackendAdapter,
)

@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_routing_ollama(mock_gpu_lease_class, mock_get_config):
    # Mock config to route 'aider_edit' to ollama
    mock_get_config.return_value = {
        "routes": {"aider_edit": "coding_ollama"},
        "profiles": {
            "coding_ollama": {"backend": "ollama", "model": "test-model"}
        }
    }
    mock_gpu_lease = MagicMock()
    mock_gpu_lease_class.return_value = mock_gpu_lease

    coordinator = BackendExecutionCoordinator()
    
    action_mock = MagicMock(return_value="success")
    request = {"action": action_mock}
    
    with patch("tools.backend_coordinator.OllamaBackendAdapter") as mock_adapter_class:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.execute.return_value = "success"
        mock_adapter_class.return_value = mock_adapter_instance
        
        result = coordinator.execute("aider_edit", request)
        
        # Verify GPU lease acquired and released
        mock_gpu_lease.acquire.assert_called_once()
        mock_gpu_lease.release.assert_called_once()
        
        # Verify adapter called
        mock_adapter_class.assert_called_once_with({"backend": "ollama", "model": "test-model"})
        mock_adapter_instance.execute.assert_called_once_with(request)
        
        assert result == "success"

@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_routing_llama_server(mock_gpu_lease_class, mock_get_config):
    # Mock config to route 'spec_draft' to llama_server
    mock_get_config.return_value = {
        "routes": {"spec_draft": "reasoning_economy"},
        "profiles": {
            "reasoning_economy": {"backend": "llama_server", "model": "test-model-reasoning"}
        }
    }
    mock_gpu_lease = MagicMock()
    mock_gpu_lease_class.return_value = mock_gpu_lease

    coordinator = BackendExecutionCoordinator()
    
    action_mock = MagicMock(return_value="success")
    request = {"action": action_mock}
    
    with patch("tools.backend_coordinator.LlamaServerBackendAdapter") as mock_adapter_class:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.execute.return_value = "success"
        mock_adapter_class.return_value = mock_adapter_instance
        
        result = coordinator.execute("spec_draft", request)
        
        # Verify GPU lease acquired and released
        mock_gpu_lease.acquire.assert_called_once()
        mock_gpu_lease.release.assert_called_once()
        
        # Verify adapter called
        mock_adapter_class.assert_called_once_with({"backend": "llama_server", "model": "test-model-reasoning"})
        mock_adapter_instance.execute.assert_called_once_with(request)
        
        assert result == "success"

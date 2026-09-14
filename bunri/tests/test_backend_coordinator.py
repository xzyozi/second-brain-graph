"""Tests for the bunri-local backend execution Module."""

from unittest.mock import MagicMock, patch

import pytest

from tools.backend_coordinator import BackendExecutionCoordinator
from tools.config_loader import BackendExecutionConfig, ProfileConfig


def _ollama_config() -> BackendExecutionConfig:
    return BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"code_edit": "coding"},
        profiles={
            "coding": ProfileConfig(
                backend="ollama",
                model="test-model",
                openai_endpoint="http://localhost:11434/v1",
                ollama_management_endpoint="http://localhost:11434",
            )
        },
    )


@patch("tools.backend_coordinator.get_backend_execution_config")
@patch("tools.backend_coordinator.GpuLeaseAdapter")
def test_coordinator_resolves_ollama_route(
    mock_lease_class: MagicMock, mock_get_config: MagicMock
) -> None:
    mock_get_config.return_value = _ollama_config()
    lease = MagicMock()
    lease.__enter__.return_value = lease
    mock_lease_class.return_value = lease

    coordinator = BackendExecutionCoordinator()
    with patch("tools.backend_coordinator.OllamaBackendAdapter") as adapter_class:
        adapter = adapter_class.return_value
        adapter.execute.return_value = "complete"

        assert coordinator.execute("code_edit", {"action": MagicMock()}) == "complete"

    lease.__enter__.assert_called_once()
    lease.__exit__.assert_called_once()


@patch("tools.backend_coordinator.get_backend_execution_config")
def test_coordinator_rejects_unmapped_intent(mock_get_config: MagicMock) -> None:
    mock_get_config.return_value = _ollama_config()

    with pytest.raises(ValueError, match="No route mapped"):
        BackendExecutionCoordinator().execute("missing", {"action": MagicMock()})

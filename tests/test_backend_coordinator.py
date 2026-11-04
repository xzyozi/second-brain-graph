"""Unit tests for tools.backend_coordinator."""

from unittest.mock import MagicMock, patch

import pytest

from tools.backend_coordinator import (
    AgyBackendAdapter,
    BackendExecutionCoordinator,
    GpuLeaseAdapter,
)
from tools.config_loader import BackendExecutionConfig, ProfileConfig


@patch("tools.backend_coordinator.get_backend_execution_config")
def test_coordinator_routing_agy(mock_get_config: MagicMock) -> None:
    """agy プロファイルへのルーティングと正常実行を検証する."""
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "agy_default"},
        profiles={
            "agy_default": ProfileConfig(
                backend="agy",
                model="agy-default",
                timeout=1200,
            )
        },
    )

    coordinator = BackendExecutionCoordinator()

    action_mock = MagicMock(return_value="success")
    request = {"action": action_mock}

    result = coordinator.execute("spec_draft", request)
    assert result == "success"
    action_mock.assert_called_once_with(mock_get_config.return_value.profiles["agy_default"])


@patch("tools.backend_coordinator.get_backend_execution_config")
def test_coordinator_unmapped_intent(mock_get_config: MagicMock) -> None:
    """未マップの intent で ValueError が発生することを検証する."""
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"code_edit": "agy_default"},
        profiles={"agy_default": ProfileConfig(backend="agy", model="agy-default")},
    )
    coordinator = BackendExecutionCoordinator()
    with pytest.raises(ValueError, match="No route mapped for intent 'unknown_intent'"):
        coordinator.execute("unknown_intent", {"action": lambda _: None})


@patch("tools.backend_coordinator.get_backend_execution_config")
def test_coordinator_retired_backend_raises_value_error(mock_get_config: MagicMock) -> None:
    """退役したバックエンド（ollama / llama_server）が指定された場合、明確なエラーを送出することを検証する."""
    mock_get_config.return_value = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"spec_draft": "legacy_profile"},
        profiles={
            "legacy_profile": ProfileConfig(
                backend="ollama",
                model="gemma",
                openai_endpoint="http://localhost:11434/v1",
                ollama_management_endpoint="http://localhost:11434",
            )
        },
    )
    coordinator = BackendExecutionCoordinator()
    with pytest.raises(ValueError, match="Backend 'ollama' is retired/unsupported"):
        coordinator.execute("spec_draft", {"action": lambda _: None})


def test_agy_adapter_requires_action() -> None:
    """AgyBackendAdapter に action が渡されない場合、ValueError を送出することを検証する."""
    profile = ProfileConfig(backend="agy", model="agy-default")
    adapter = AgyBackendAdapter(profile)
    with pytest.raises(ValueError, match="requires an 'action' callable"):
        adapter.execute({})


def test_agy_adapter_does_not_change_environment() -> None:
    """AgyBackendAdapter が環境変数を変更しないことを検証する."""
    import os

    profile = ProfileConfig(backend="agy", model="agy-default")
    adapter = AgyBackendAdapter(profile)
    before_env = dict(os.environ)

    adapter.execute({"action": lambda p: "ok"})

    assert dict(os.environ) == before_env


def test_gpu_lease_adapter_timeout_handling() -> None:
    """GpuLeaseAdapter の初期化とタイムアウト設定を検証する."""
    adapter = GpuLeaseAdapter(timeout=42)
    assert adapter.timeout == 42

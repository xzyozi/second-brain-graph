"""code_node が profile.backend == 'agy' のとき agy 経路へ分岐することを検証するテスト.

実 agy バイナリは使用しない。BackendExecutionCoordinator を模擬し、
run_agy_edit をモックして、呼び出しの配線と既存の状態遷移契約を検証する。
"""

from unittest.mock import MagicMock, patch

from tools.agy_runner import AgyRunError
from tools.config_loader import ProfileConfig
from tools.orchestrator_graph import GraphState, code_node


def _make_agy_coordinator(dummy_profile: ProfileConfig) -> MagicMock:
    coordinator = MagicMock()
    coordinator.execute.side_effect = lambda intent, req: req["action"](dummy_profile)
    return coordinator


@patch("tools.agy_runner.run_agy_edit", return_value=True)
@patch("tools.orchestrator_graph.get_coordinator")
def test_code_node_dispatches_to_agy_when_profile_backend_is_agy(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """profile.backend が agy の場合、run_agy_edit を呼び、code_completed へ遷移することを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)

    state: GraphState = {
        "issue_id": "TFG-0099",
        "target_files": ["src/example.py"],
        "instruction": "Implement feature",
        "cwd": None,
    }

    result = code_node(state)

    mock_run_agy_edit.assert_called_once()
    call_kwargs = mock_run_agy_edit.call_args.kwargs
    assert call_kwargs["target_files"] == ["src/example.py"]
    assert call_kwargs["timeout"] == 1200
    assert "Implement feature" in call_kwargs["instruction"]
    assert result["status"] == "code_completed"


@patch("tools.agy_runner.run_agy_edit")
@patch("tools.orchestrator_graph.get_coordinator")
def test_code_node_uses_default_timeout_when_profile_timeout_unset(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """profile.timeout が未設定の場合、既定の 1200 秒を使うことを検証する。"""
    mock_run_agy_edit.return_value = True
    dummy_profile = ProfileConfig(backend="agy", model="agy-default")  # timeout は既定で None
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)

    state: GraphState = {
        "issue_id": "TFG-0096",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    code_node(state)

    assert mock_run_agy_edit.call_args.kwargs["timeout"] == 1200


@patch("tools.agy_runner.run_agy_edit")
@patch("tools.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_timeout_retry_and_escalation(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """agy のタイムアウトが Aider と同じ LLM_TIMEOUT のリトライ・エスカレーション契約に従うことを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError("agy execution timed out after 1200 seconds")

    state: GraphState = {
        "issue_id": "TFG-0098",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }

    first = code_node(state)
    assert first["llm_timeout_count"] == 1
    assert first["error_category"] == "LLM_TIMEOUT"
    assert first["status"] == "retry_code"

    second = code_node(first)
    assert second["llm_timeout_count"] == 2
    assert second["error_category"] == "LLM_TIMEOUT"
    assert second["status"] == "FAILED_SYSTEM"


@patch("tools.agy_runner.run_agy_edit")
@patch("tools.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_nonzero_exit_as_failed_system(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """タイムアウト以外の agy 異常終了は、即時 FAILED_SYSTEM / SYSTEM_ERROR とすることを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError("agy process failed with returncode 2: boom")

    state: GraphState = {
        "issue_id": "TFG-0097",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    result = code_node(state)

    assert result["status"] == "FAILED_SYSTEM"
    assert result["error_category"] == "SYSTEM_ERROR"

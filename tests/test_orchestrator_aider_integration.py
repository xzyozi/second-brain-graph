"""Integration tests for orchestrator_graph Aider timeout handling and state transitions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tools.aider_runner import AiderRunError
from tools.orchestrator_graph import (
    GraphState,
    code_node,
    execute_issue,
)


def test_code_node_handles_aider_timeout_retry_and_escalation() -> None:
    """Test that code_node maps AiderRunError to LLM_TIMEOUT, retries on 1st timeout, and escalates to FAILED_SYSTEM on 2nd timeout."""
    initial_state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_001",
        generation=0,
        status="running",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        target_files=["main.py"],
        instruction="Fix bug",
        cwd=None,
    )

    with patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Timeout 300s")):
        # First timeout -> retry
        state_after_first = code_node(initial_state)
        assert state_after_first["llm_timeout_count"] == 1
        assert state_after_first["error_category"] == "LLM_TIMEOUT"
        assert state_after_first["status"] == "retry_code"

        # Second timeout -> escalate FAILED_SYSTEM
        state_after_second = code_node(state_after_first)
        assert state_after_second["llm_timeout_count"] == 2
        assert state_after_second["error_category"] == "LLM_TIMEOUT"
        assert state_after_second["status"] == "FAILED_SYSTEM"


@patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Aider execution timed out"))
@patch("tools.llm_client.call_llm")
def test_execute_issue_aider_timeout_flow(mock_call_llm: MagicMock, mock_run_aider: MagicMock) -> None:
    """Verify full graph execution flow when Aider times out repeatedly."""
    project_key = "TFG"
    issue_id = "TFG-0004"

    # Mock locks
    with patch("tools.orchestrator_graph.ProjectLockManager._acquire_lock"), \
         patch("tools.orchestrator_graph.ProjectLockManager._release_lock"):
        execute_issue(issue_id, project_key)

    state_file = Path(__file__).resolve().parent.parent / "metadata" / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_state["status"] == "FAILED_SYSTEM"
    assert saved_state["error_category"] == "LLM_TIMEOUT"

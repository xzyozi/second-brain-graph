"""Integration tests for orchestrator_graph Aider handling, state transitions, isolation, and lock verification."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tools.aider_runner import AiderRunError
from tools.orchestrator_graph import (
    GraphState,
    ProjectLockManager,
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
        review_round=0,
        max_round=3,
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


def test_code_node_handles_aider_false_return_as_failed_system() -> None:
    """Test that code_node normalizes Aider False return value to FAILED_SYSTEM and SYSTEM_ERROR."""
    initial_state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_002",
        generation=0,
        status="running",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        review_round=0,
        max_round=3,
        target_files=["main.py"],
        instruction="Fix bug",
        cwd=None,
    )

    with patch("tools.orchestrator_graph.run_aider", return_value=False):
        state_after_failure = code_node(initial_state)
        assert state_after_failure["status"] == "FAILED_SYSTEM"
        assert state_after_failure["error_category"] == "SYSTEM_ERROR"
        assert "Aider execution returned False" in str(state_after_failure["error"])


@patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Aider execution timed out"))
@patch("tools.llm_client.call_llm")
def test_execute_issue_aider_timeout_flow_isolated(
    mock_call_llm: MagicMock, mock_run_aider: MagicMock, tmp_path: Path
) -> None:
    """Verify full graph execution flow when Aider times out using isolated tmp_path for metadata and lock verification."""
    metadata_dir = tmp_path / "metadata"
    project_key = "TFG"
    issue_id = "TFG-0004"

    # Create dummy registry
    registry_file = metadata_dir / ".project-registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        json.dumps({
            "projects": {
                "TFG": {
                    "name": "test_file_grep",
                    "dir": "projects/test_file_grep",
                    "meta": "metadata/projects/TFG",
                }
            }
        }),
        encoding="utf-8",
    )

    with patch.object(ProjectLockManager, "_acquire_lock", autospec=True) as mock_acquire, \
         patch.object(ProjectLockManager, "_release_lock", autospec=True) as mock_release:

        execute_issue(issue_id, project_key, metadata_dir=metadata_dir)

        # Verify lock acquisition and release calls
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()

    # Verify state.json was created under isolated tmp_path conforming to SSOT dictionary schema
    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert issue_id in saved_data
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "LLM_TIMEOUT"


def test_execute_issue_lock_timeout_flow(tmp_path: Path) -> None:
    """Verify that lock acquisition timeout records SKIPPED_LOCKED and LOCKED error_category in state.json."""
    metadata_dir = tmp_path / "metadata"
    project_key = "TFG"
    issue_id = "TFG-0004"

    with patch.object(ProjectLockManager, "_acquire_lock", side_effect=TimeoutError("Lock timeout")):
        execute_issue(issue_id, project_key, metadata_dir=metadata_dir)

    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert issue_id in saved_data
    assert saved_data[issue_id]["status"] == "SKIPPED_LOCKED"
    assert saved_data[issue_id]["error_category"] == "LOCKED"

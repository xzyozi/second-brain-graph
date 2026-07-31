"""Integration tests for orchestrator_graph Aider handling, state transitions, history isolation, failsafe, git switch, reviewer validation, and CLI commands."""

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
    lint_node,
    review_node,
    run_pytest_node,
    update_task_state,
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
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/grep/office_parser.py"],
        instruction="Fix bug",
        cwd=None,
        base_branch="develop",
        aider_message="",
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
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/grep/office_parser.py"],
        instruction="Fix bug",
        cwd=None,
        base_branch="develop",
        aider_message="",
    )

    with patch("tools.orchestrator_graph.run_aider", return_value=False):
        state_after_failure = code_node(initial_state)
        assert state_after_failure["status"] == "FAILED_SYSTEM"
        assert state_after_failure["error_category"] == "SYSTEM_ERROR"
        assert "Aider execution returned False" in str(state_after_failure["error"])


def test_nodes_normalize_exceptions_to_failed_system() -> None:
    """Verify that exceptions in lint_node, test_node, and review_node normalize to FAILED_SYSTEM."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_003",
        generation=0,
        status="running",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        review_round=0,
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/grep/office_parser.py"],
        instruction="Fix bug",
        cwd="/invalid/nonexistent/path",
        base_branch="develop",
        aider_message="",
    )

    with patch("subprocess.run", side_effect=RuntimeError("Subprocess failed")):
        lint_res = lint_node(state.copy())
        assert lint_res["status"] == "FAILED_SYSTEM"
        assert lint_res["error_category"] == "SYSTEM_ERROR"

        test_res = run_pytest_node(state.copy())
        assert test_res["status"] == "FAILED_SYSTEM"
        assert test_res["error_category"] == "SYSTEM_ERROR"

    with patch("tools.llm_client.call_llm", side_effect=RuntimeError("LLM call failed")):
        review_res = review_node(state.copy())
        assert review_res["status"] == "FAILED_SYSTEM"
        assert review_res["error_category"] == "SYSTEM_ERROR"


def test_review_node_validates_response_structure() -> None:
    """Verify that non-dict or invalid verdict from Reviewer LLM normalizes to FAILED_SYSTEM."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_004",
        generation=0,
        status="running",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        review_round=0,
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/grep/office_parser.py"],
        instruction="Fix bug",
        cwd=None,
        base_branch="develop",
        aider_message="",
    )

    # Invalid non-dict response
    with patch("tools.llm_client.call_llm", return_value="Invalid string response"):
        res = review_node(state.copy())
        assert res["status"] == "FAILED_SYSTEM"
        assert res["error_category"] == "SYSTEM_ERROR"

    # Missing verdict key in dict
    with patch("tools.llm_client.call_llm", return_value={"comments": ["Looks weird"]}):
        res = review_node(state.copy())
        assert res["status"] == "FAILED_SYSTEM"
        assert res["error_category"] == "SYSTEM_ERROR"


@patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Aider execution timed out"))
@patch("tools.llm_client.call_llm", return_value={"verdict": "LGTM", "comments": []})
def test_execute_issue_aider_timeout_flow_fully_isolated(
    mock_call_llm: MagicMock, mock_run_aider: MagicMock, tmp_path: Path
) -> None:
    """Verify full graph execution flow when Aider times out using isolated project_root and metadata_dir."""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    history_file = project_root / "tools" / ".cache" / "execution_history.json"
    project_key = "TFG"
    issue_id = "TFG-0004"

    # Setup satellite repo dir & target file inside project_root for context resolution
    sat_dir = project_root / "projects" / "test_file_grep"
    git_dir = sat_dir / ".git"
    target_file = sat_dir / "src" / "grep" / "office_parser.py"

    git_dir.mkdir(parents=True, exist_ok=True)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Target file for test", encoding="utf-8")

    # Setup project registry
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "tasks.md").write_text("- [ ] [TFG-0004] office_parser.py test", encoding="utf-8")
    (meta_tfg / "project.json").write_text(json.dumps({"key": "TFG", "base_branch": "develop"}), encoding="utf-8")

    registry_file = metadata_dir / ".project-registry.json"
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
         patch.object(ProjectLockManager, "_release_lock", autospec=True) as mock_release, \
         patch("subprocess.run"):

        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=project_root)

        mock_acquire.assert_called_once()
        mock_release.assert_called_once()
        # Verify run_aider was called twice (1st timeout retry + 2nd timeout escalation)
        assert mock_run_aider.call_count == 2

    # 1. Verify isolated state.json was created with SSOT dictionary schema
    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert issue_id in saved_data
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "LLM_TIMEOUT"

    # 2. Verify isolated history_file was created in tmp_path with review_round key
    assert history_file.exists()
    hist_data = json.loads(history_file.read_text(encoding="utf-8"))
    assert "records" in hist_data
    record = hist_data["records"][0]
    assert record["issue_id"] == issue_id
    assert record["final_status"] == "FAILED_SYSTEM"
    assert "review_round" in record


def test_execute_issue_lock_timeout_flow_isolated(tmp_path: Path) -> None:
    """Verify that lock acquisition timeout records SKIPPED_LOCKED and LOCKED in isolated state.json and history_file."""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    history_file = project_root / "tools" / ".cache" / "execution_history.json"
    project_key = "TFG"
    issue_id = "TFG-0004"

    # Setup satellite repo dir & target file
    sat_dir = project_root / "projects" / "test_file_grep"
    git_dir = sat_dir / ".git"
    target_file = sat_dir / "src" / "grep" / "office_parser.py"

    git_dir.mkdir(parents=True, exist_ok=True)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Target file for test", encoding="utf-8")

    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "tasks.md").write_text("- [ ] [TFG-0004] office_parser.py test", encoding="utf-8")

    registry_file = metadata_dir / ".project-registry.json"
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

    with patch.object(ProjectLockManager, "_acquire_lock", side_effect=TimeoutError("Lock timeout")):
        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=project_root)

    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert issue_id in saved_data
    assert saved_data[issue_id]["status"] == "SKIPPED_LOCKED"
    assert saved_data[issue_id]["error_category"] == "LOCKED"

    assert history_file.exists()
    hist_data = json.loads(history_file.read_text(encoding="utf-8"))
    assert hist_data["records"][0]["final_status"] == "SKIPPED_LOCKED"


def test_update_task_state_migrates_old_flat_format(tmp_path: Path) -> None:
    """Verify that update_task_state correctly migrates old flat state.json format to SSOT dictionary schema."""
    metadata_dir = tmp_path / "metadata"
    project_key = "TFG"
    issue_id = "TFG-0004"
    state_file = metadata_dir / "projects" / project_key / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Write old flat format
    old_flat_data = {
        "issue_id": "TFG-0004",
        "status": "FAILED_SYSTEM",
        "review_round": 0,
        "max_round": 3,
    }
    state_file.write_text(json.dumps(old_flat_data), encoding="utf-8")

    # Call update_task_state
    update_task_state(project_key, issue_id, status="COMPLETED", review_round=1, metadata_dir=metadata_dir)

    # Verify migration
    new_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "issue_id" not in new_data  # flat key cleaned up
    assert issue_id in new_data
    assert new_data[issue_id]["status"] == "COMPLETED"
    assert new_data[issue_id]["review_round"] == 1


def test_failsafe_invalid_satellite_context(tmp_path: Path) -> None:
    """Verify that execute_issue fails safe without running Aider if project registry or satellite dir is invalid."""
    metadata_dir = tmp_path / "metadata"
    history_file = tmp_path / "tools" / ".cache" / "execution_history.json"
    project_key = "UNKNOWN_PROJ"
    issue_id = "UNK-0001"

    with patch("tools.orchestrator_graph.run_aider") as mock_run_aider:
        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=tmp_path)
        mock_run_aider.assert_not_called()

    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "SYSTEM_ERROR"

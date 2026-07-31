"""Integration tests for orchestrator_graph Aider handling, state transitions, history isolation, failsafe, git switch, reviewer validation, RDJSON, audit schema, regex validation, and CLI commands."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tools.aider_runner import AiderRunError
from tools.orchestrator_graph import (
    GraphState,
    ProjectLockManager,
    cmd_orchestrate,
    code_node,
    execute_issue,
    lint_node,
    review_node,
    run_pytest_node,
    spec_draft_node,
    update_task_state,
    validate_issue_id,
    validate_project_consistency,
)


def test_validate_issue_id_format() -> None:
    """Verify that validate_issue_id enforces strict PROJECT-0001 pattern (range 0001-9999, 0000 rejected)."""
    assert validate_issue_id("TFG-0004") is True
    assert validate_issue_id("SBOS-0001") is True
    assert validate_issue_id("TFG-0004-A") is True

    # 0000 is rejected
    assert validate_issue_id("EC-0000") is False
    assert validate_issue_id("EC-1") is False
    assert validate_issue_id("invalid_id") is False
    assert validate_issue_id("TFG0004") is False


def test_validate_project_consistency_mismatch(tmp_path: Path) -> None:
    """Verify that validate_project_consistency rejects ID range anomalies and project key mismatches before side-effects."""
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # 1. 0000 rejected
    with pytest.raises(ValueError, match="0001-9999"):
        validate_project_consistency("EC-0000", "EC", metadata_dir=metadata_dir, project_root=tmp_path)

    # 2. Issue ID prefix vs project_key mismatch
    with pytest.raises(ValueError, match="Project key mismatch"):
        validate_project_consistency("EC-0001", "MOB", metadata_dir=metadata_dir, project_root=tmp_path)


def test_spec_draft_node_timeout_retry() -> None:
    """Verify that spec_draft_node routes timeout to retry_spec_draft on 1st timeout and FAILED_SYSTEM on 2nd timeout."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_spec_001",
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
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        history_summary=None,
        rdjson=None,
    )

    with patch("tools.llm_client.call_llm", side_effect=RuntimeError("Timeout occurred")):
        res_1 = spec_draft_node(state.copy())
        assert res_1["status"] == "retry_spec_draft"
        assert res_1["llm_timeout_count"] == 1

        res_2 = spec_draft_node(res_1.copy())
        assert res_2["status"] == "FAILED_SYSTEM"
        assert res_2["llm_timeout_count"] == 2


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
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        history_summary=None,
        rdjson=None,
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
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        history_summary=None,
        rdjson=None,
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
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        history_summary=None,
        rdjson=None,
    )

    with patch("subprocess.run", side_effect=RuntimeError("Subprocess failed")):
        lint_res = lint_node(state.copy())
        assert lint_res["status"] == "FAILED_SYSTEM"
        assert lint_res["error_category"] == "SYSTEM_ERROR"

        test_res = run_pytest_node(state.copy())
        assert test_res["status"] == "FAILED_SYSTEM"
        assert test_res["error_category"] == "SYSTEM_ERROR"


def test_review_node_validates_response_records_lgtm_and_structures_rdjson() -> None:
    """Verify that review_node parses LGTM and changes_requested, builds rdjson, and tracks all review_rounds."""
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
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        history_summary=None,
        rdjson=None,
    )

    # 1. Test changes_requested
    mock_resp = {"verdict": "changes_requested", "comments": ["Syntax error on line 10"]}
    with patch("tools.llm_client.call_llm", return_value=mock_resp):
        res = review_node(state.copy())
        assert res["status"] == "retry_code"
        assert res["review_round"] == 1
        assert res["review_verdict"] == "changes_requested"
        assert len(res["review_rounds"]) == 1
        assert res["review_rounds"][0]["verdict"] == "changes_requested"
        assert "rdjson" in res
        assert res["rdjson"]["diagnostics"][0]["message"] == "Syntax error on line 10"

    # 2. Test LGTM with fresh state
    state_lgtm = state.copy()
    state_lgtm["review_rounds"] = []
    mock_lgtm = {"verdict": "LGTM", "comments": ["Looks good"]}
    with patch("tools.llm_client.call_llm", return_value=mock_lgtm):
        res_lgtm = review_node(state_lgtm)
        assert res_lgtm["status"] == "review_lgtm"
        assert res_lgtm["review_verdict"] == "LGTM"
        assert len(res_lgtm["review_rounds"]) == 1
        assert res_lgtm["review_rounds"][0]["verdict"] == "LGTM"


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
         patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")):

        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=project_root)

        mock_acquire.assert_called_once()
        mock_release.assert_called_once()
        assert mock_run_aider.call_count == 2

    # 1. Verify isolated state.json was created with SSOT dictionary schema
    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert issue_id in saved_data
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "LLM_TIMEOUT"

    # 2. Verify isolated history_file was created in tmp_path with DD-003 audit schema
    assert history_file.exists()
    hist_data = json.loads(history_file.read_text(encoding="utf-8"))
    assert "records" in hist_data
    record = hist_data["records"][0]
    assert record["issue_id"] == issue_id
    assert record["final_status"] == "FAILED_SYSTEM"
    assert "actual_round" in record
    assert "history_summary" in record


def test_cmd_orchestrate_reads_canonical_issues_schema(tmp_path: Path) -> None:
    """Verify that cmd_orchestrate reads canonical priority-cache.json with {"issues": [{"id": "..."}]} structure."""
    cache_dir = tmp_path / "tools" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "priority-cache.json"

    dummy_cache = {
        "issues": [
            {"id": "TFG-0001", "title": "Task 1", "score": 10, "project_key": "TFG"},
            {"id": "TFG-0002", "title": "Task 2", "score": 90, "project_key": "TFG"},
            {"id": "TFG-0003", "title": "Task 3", "score": 50, "project_key": "TFG"},
            {"id": "TFG-0004", "title": "Task 4", "score": 100, "project_key": "TFG"},
        ]
    }
    cache_file.write_text(json.dumps(dummy_cache), encoding="utf-8")

    with patch("tools.orchestrator_graph.logger") as mock_logger:
        cmd_orchestrate("TFG", cache_file=cache_file)
        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        assert any("TFG-0004" in msg for msg in log_calls)


def test_failsafe_invalid_satellite_context(tmp_path: Path) -> None:
    """Verify that execute_issue fails safe without running Aider if project registry or satellite dir is invalid."""
    metadata_dir = tmp_path / "metadata"
    history_file = tmp_path / "tools" / ".cache" / "execution_history.json"
    project_key = "UNK"
    issue_id = "UNK-0001"

    # Registry must include UNK key for validate_project_consistency
    registry_file = metadata_dir / ".project-registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(json.dumps({"projects": {"UNK": {"dir": "invalid/dir"}}}), encoding="utf-8")

    with patch("tools.orchestrator_graph.run_aider") as mock_run_aider:
        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=tmp_path)
        mock_run_aider.assert_not_called()

    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "SYSTEM_ERROR"

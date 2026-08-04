"""Integration tests for orchestrator_graph Aider handling, state transitions, history isolation, failsafe, git switch, reviewer validation, RDJSON, audit schema, regex validation, and CLI commands."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from tools.aider_runner import AiderRunError, GitDiffError
from tools.orchestrator_graph import (
    GraphState,
    ProjectLockManager,
    cmd_orchestrate,
    code_node,
    done_node,
    escalate_node,
    execute_issue,
    lint_node,
    resolve_project_context,
    review_node,
    run_pytest_node,
    spec_draft_node,
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


def test_validate_project_consistency_mismatch_and_missing_metadata(tmp_path: Path) -> None:
    """Verify that validate_project_consistency rejects ID range anomalies, project key mismatches, and missing registry/meta/project.json."""
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # 1. 0000 rejected
    with pytest.raises(ValueError, match="0001-9999"):
        validate_project_consistency("EC-0000", "EC", metadata_dir=metadata_dir, project_root=tmp_path)

    # 2. Issue ID prefix vs project_key mismatch
    with pytest.raises(ValueError, match="Project key mismatch"):
        validate_project_consistency("EC-0001", "MOB", metadata_dir=metadata_dir, project_root=tmp_path)

    # 3. Missing registry
    with pytest.raises(ValueError, match="registry file"):
        validate_project_consistency("TFG-0004", "TFG", metadata_dir=metadata_dir, project_root=tmp_path)

    # 4. Registry missing project
    registry_file = metadata_dir / ".project-registry.json"
    registry_file.write_text(json.dumps({"projects": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="is not registered"):
        validate_project_consistency("TFG-0004", "TFG", metadata_dir=metadata_dir, project_root=tmp_path)


def test_generic_satellite_context_resolution(tmp_path: Path) -> None:
    """Verify that resolve_project_context dynamically resolves targets without hardcoded filenames."""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    sat_dir = project_root / "projects" / "custom_satellite"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)

    target_file = sat_dir / "src" / "custom_module.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Custom satellite file", encoding="utf-8")

    meta_custom = metadata_dir / "projects" / "CST"
    meta_custom.mkdir(parents=True, exist_ok=True)
    (meta_custom / "project.json").write_text(json.dumps({"key": "CST", "base_branch": "main"}), encoding="utf-8")

    registry_file = metadata_dir / ".project-registry.json"
    registry_file.write_text(
        json.dumps({
            "projects": {
                "CST": {
                    "name": "custom_satellite",
                    "dir": "projects/custom_satellite",
                    "meta": "metadata/projects/CST",
                }
            }
        }),
        encoding="utf-8"
    )

    ctx = resolve_project_context("CST", metadata_dir=metadata_dir, project_root=project_root)
    assert ctx["valid"] is True
    assert ctx["base_branch"] == "main"
    assert "src/custom_module.py" in ctx["target_files"]


def test_done_node_handles_git_failures() -> None:
    """Verify that done_node maps git diff --cached, add, commit, push, gh pr create failures to PR_FAILED / PR_ERROR."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_done_001",
        generation=0,
        status="review_lgtm",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        review_round=1,
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/grep/office_parser.py"],
        instruction="Fix bug",
        cwd="/tmp/fake_repo",
        base_branch="develop",
        aider_message="",
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict="LGTM",
        review_comments=[],
        review_rounds=[],
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    with patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True):
        # 1. git diff --cached returns non-zero code
        with patch("tools.orchestrator_graph.run_cmd", return_value=MagicMock(returncode=1, stderr="diff error")):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"

        # 2. git diff --cached non-empty staged changes
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout="staged_file.py\n"),
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"
            assert "staged changes" in str(res["error"])

        # 3. git add returns non-zero code
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=1, stderr="add error"), # git add
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"
            assert "git add failed" in str(res["error"])

        # 4. git status returns non-zero code
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=0, stdout=""), # git add
            MagicMock(returncode=0, stdout="src/grep/office_parser.py"), # diff --cached (after add)
            MagicMock(returncode=1, stderr="status error"), # git status
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"
            assert "git status failed" in str(res["error"])

        # 5. git commit returns non-zero code
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=0, stdout=""), # git add
            MagicMock(returncode=0, stdout="src/grep/office_parser.py"), # diff --cached (after add)
            MagicMock(returncode=0, stdout="M src/grep/office_parser.py\n"), # git status (dirty)
            MagicMock(returncode=1, stderr="commit error"), # git commit
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"
            assert "git commit failed" in str(res["error"])

        # 6. git push returns non-zero code
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=0, stdout=""), # git add
            MagicMock(returncode=0, stdout="src/grep/office_parser.py"), # diff --cached (after add)
            MagicMock(returncode=0, stdout="M src/grep/office_parser.py\n"), # git status (dirty)
            MagicMock(returncode=0, stdout=""), # git commit
            MagicMock(returncode=0, stdout=""), # git fetch
            MagicMock(returncode=1, stderr="push error"), # git push
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"
            assert "Git push failed" in str(res["error"])

        # 7. gh pr create returns non-zero code (real error, no existing PR found via gh pr list)
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=0, stdout=""), # git add
            MagicMock(returncode=0, stdout="src/grep/office_parser.py"), # diff --cached (after add)
            MagicMock(returncode=0, stdout=""), # git status (clean) - skips commit
            MagicMock(returncode=0, stdout=""), # git fetch
            MagicMock(returncode=0, stdout=""), # git push
            MagicMock(returncode=0, stdout="[]"), # gh pr list (no PR exists)
            MagicMock(returncode=1, stderr="pr create error"), # gh pr create
        ]):
            res = done_node(state.copy())
            assert res["status"] == "PR_FAILED"
            assert res["error_category"] == "PR_ERROR"

        # 8. gh pr list detects existing PR (structured pre-check)
        with patch("tools.orchestrator_graph.run_cmd", side_effect=[
            MagicMock(returncode=0, stdout=""), # diff --cached (first)
            MagicMock(returncode=0, stdout=""), # git add
            MagicMock(returncode=0, stdout="src/grep/office_parser.py"), # diff --cached (after add)
            MagicMock(returncode=0, stdout=""), # git status (clean) - skips commit
            MagicMock(returncode=0, stdout=""), # git fetch
            MagicMock(returncode=0, stdout=""), # git push
            MagicMock(returncode=0, stdout='[{"number": 12}]'), # gh pr list (PR #12 exists!)
        ]):
            res = done_node(state.copy())
            assert res["status"] == "COMPLETED"

    # 8. Non-git workspace handles PR creation gracefully
    with patch("tools.orchestrator_graph.is_in_git_workspace", return_value=False):
        res = done_node(state.copy())
        assert res["status"] == "PR_FAILED"
        assert res["error_category"] == "PR_ERROR"
        assert "not in a valid git workspace" in str(res["error"])



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
        reviewdog_result=None,
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
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    with patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Aider execution timed out after 300 seconds")):
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


def test_code_node_handles_aider_nonzero_exit_as_failed_system() -> None:
    """Test that code_node normalizes non-timeout AiderRunError to FAILED_SYSTEM and SYSTEM_ERROR without retry."""
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
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    with patch("tools.orchestrator_graph.run_aider", side_effect=AiderRunError("Aider process failed with returncode 1")):
        state_after_failure = code_node(initial_state)
        assert state_after_failure["status"] == "FAILED_SYSTEM"
        assert state_after_failure["error_category"] == "SYSTEM_ERROR"
        assert "returncode 1" in str(state_after_failure["error"])
        assert state_after_failure.get("llm_timeout_count", 0) == 0


def test_nodes_normalize_exceptions_to_failed_system() -> None:
    """Verify that exceptions in lint_node, test_node, and review_node normalize to FAILED_SYSTEM."""
    from tools.orchestrator_graph import ProcessTimeoutError

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
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    # Test RuntimeError
    with patch("tools.orchestrator_graph.run_cmd", side_effect=RuntimeError("Subprocess failed")):
        lint_res = lint_node(state.copy())
        assert lint_res["status"] == "FAILED_SYSTEM"
        assert lint_res["error_category"] == "SYSTEM_ERROR"

        test_res = run_pytest_node(state.copy())
        assert test_res["status"] == "FAILED_SYSTEM"
        assert test_res["error_category"] == "SYSTEM_ERROR"

    # Test ProcessTimeoutError
    with patch("tools.orchestrator_graph.run_cmd", side_effect=ProcessTimeoutError("Command timed out after 300 seconds")):
        lint_res_timeout = lint_node(state.copy())
        assert lint_res_timeout["status"] == "FAILED_SYSTEM"
        assert lint_res_timeout["error_category"] == "SYSTEM_ERROR"

        test_res_timeout = run_pytest_node(state.copy())
        assert test_res_timeout["status"] == "FAILED_SYSTEM"
        assert test_res_timeout["error_category"] == "SYSTEM_ERROR"


def test_review_node_fail_closed_on_git_diff_error() -> None:
    """Verify that review_node stops with FAILED_SYSTEM if get_git_diff raises GitDiffError."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_diff_err",
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
        cwd="/fake/path",
        base_branch="develop",
        aider_message="",
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    with patch("tools.orchestrator_graph.get_git_diff", side_effect=GitDiffError("git diff failed")):
        res = review_node(state)
        assert res["status"] == "FAILED_SYSTEM"
        assert res["error_category"] == "SYSTEM_ERROR"


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
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    # 1. Test changes_requested
    mock_resp = {
        "verdict": "changes_requested",
        "comments": [{"file": "src/grep/office_parser.py", "line": 10, "message": "Syntax error", "severity": "WARNING"}]
    }
    with patch("tools.llm_client.call_llm", return_value=mock_resp), \
         patch("tools.orchestrator_graph.get_git_diff", return_value="diff text"):
        res = review_node(state.copy())
        assert res["status"] == "retry_code"
        assert res["review_round"] == 1
        assert res["review_verdict"] == "changes_requested"
        assert len(res["review_rounds"]) == 1
        assert res["review_rounds"][0]["verdict"] == "changes_requested"
        assert "rdjson" in res
        assert res["rdjson"]["diagnostics"][0]["message"] == "Syntax error"

    # 2. Test LGTM with fresh state
    state_lgtm = state.copy()
    state_lgtm["review_rounds"] = []
    mock_lgtm = {"verdict": "LGTM", "comments": []}
    with patch("tools.llm_client.call_llm", return_value=mock_lgtm), \
         patch("tools.orchestrator_graph.get_git_diff", return_value="diff text"):
        res_lgtm = review_node(state_lgtm)
        assert res_lgtm["status"] == "review_lgtm"
        assert res_lgtm["review_verdict"] == "LGTM"
        assert len(res_lgtm["review_rounds"]) == 1
        assert res_lgtm["review_rounds"][0]["verdict"] == "LGTM"


def test_review_node_continues_on_reviewdog_failure() -> None:
    """Reviewdog 実行が失敗 (returncode=1) した場合でも FAILED_SYSTEM にならず、LLM の判定 (LGTM/retry_code) に遷移することを検証する。"""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_rd_fail",
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
        cwd=".",
        base_branch="develop",
        aider_message="",
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    mock_lgtm = {"verdict": "LGTM", "comments": []}
    mock_rd_fail = MagicMock(returncode=1, stdout="", stderr="reviewdog error")

    with patch("tools.llm_client.call_llm", return_value=mock_lgtm), \
         patch("tools.orchestrator_graph.get_git_diff", return_value="diff text"), \
         patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True), \
         patch("tools.orchestrator_graph.run_cmd", return_value=mock_rd_fail):
        res = review_node(state)
        assert res["status"] == "review_lgtm"
        assert res["reviewdog_result"]["returncode"] == 1
        assert res["reviewdog_result"]["stderr"] == "reviewdog error"


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

    # Setup project registry & metadata
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "tasks.md").write_text("- [ ] [TFG-0004] office_parser.py test", encoding="utf-8")
    (meta_tfg / "project.json").write_text(
        json.dumps({"key": "TFG", "base_branch": "develop", "target_files": ["src/grep/office_parser.py"]}),
        encoding="utf-8"
    )

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
         patch("tools.orchestrator_graph.run_cmd", return_value=MagicMock(returncode=0, stdout="")):

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

    # Setup valid registry and meta for validate_project_consistency
    meta_unk = metadata_dir / "projects" / "UNK"
    meta_unk.mkdir(parents=True, exist_ok=True)
    (meta_unk / "project.json").write_text(json.dumps({"key": "UNK"}), encoding="utf-8")

    registry_file = metadata_dir / ".project-registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        json.dumps({"projects": {"UNK": {"dir": "invalid/dir", "meta": "metadata/projects/UNK"}}}),
        encoding="utf-8"
    )

    with patch("tools.orchestrator_graph.run_aider") as mock_run_aider:
        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=tmp_path)
        mock_run_aider.assert_not_called()

    state_file = metadata_dir / "projects" / project_key / "state.json"
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "SYSTEM_ERROR"


def test_run_pytest_node_json_report_parsing(tmp_path: Path) -> None:
    """Verify that run_pytest_node executes pytest with --json-report and parses failures for Aider feedback."""
    state = GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_pytest_json",
        generation=0,
        status="running",
        error=None,
        error_category=None,
        llm_timeout_count=0,
        review_round=0,
        lint_round=0,
        test_round=0,
        max_round=3,
        target_files=["src/test.py"],
        instruction="Fix bug",
        cwd=str(tmp_path),
        base_branch="develop",
        aider_message="",
        impl_plan=None,
        lint_result=None,
        test_result=None,
        review_verdict=None,
        review_comments=None,
        review_rounds=[],
        reviewdog_result=None,
        history_summary=None,
        rdjson=None,
    )

    report_content = {
        "summary": {"failed": 1, "passed": 0, "total": 1},
        "tests": [
            {
                "nodeid": "tests/test_foo.py::test_bar",
                "outcome": "failed",
                "call": {"longrepr": "AssertionError: expected True got False"},
            }
        ],
    }
    report_file = tmp_path / ".report.json"
    report_file.write_text(json.dumps(report_content), encoding="utf-8")

    with patch("tools.orchestrator_graph.run_cmd", return_value=MagicMock(returncode=1, stdout="Failed", stderr="")):
        res = run_pytest_node(state)
        assert res["status"] == "retry_code"
        assert res["error_category"] == "TEST_ERROR"
        assert "AssertionError: expected True got False" in res["aider_message"]
        assert "tests/test_foo.py::test_bar" in res["aider_message"]


def test_execute_issue_rebase_existing_branch(tmp_path: Path) -> None:
    """Verify that execute_issue performs git rebase base_branch when switching to an existing work branch."""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    history_file = project_root / "tools" / ".cache" / "execution_history.json"
    project_key = "TFG"
    issue_id = "TFG-0004"

    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    target_file = sat_dir / "src" / "grep" / "office_parser.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Target file", encoding="utf-8")

    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "project.json").write_text(
        json.dumps({"key": "TFG", "base_branch": "develop", "target_files": ["src/grep/office_parser.py"]}),
        encoding="utf-8"
    )

    registry_file = metadata_dir / ".project-registry.json"
    registry_file.write_text(
        json.dumps({"projects": {"TFG": {"name": "test_file_grep", "dir": "projects/test_file_grep", "meta": "metadata/projects/TFG"}}}),
        encoding="utf-8",
    )

    # Simulate git switch head_branch returning 0 (existing branch), but git rebase base_branch returning 1 (rebase conflict)
    cmd_responses = [
        MagicMock(returncode=0, stdout=""), # git status --porcelain (clean)
        MagicMock(returncode=0, stdout=""), # git switch develop
        MagicMock(returncode=0, stdout=""), # git pull --ff-only origin develop
        MagicMock(returncode=0, stdout=""), # git switch sbos/TFG-0004 (existing branch!)
        MagicMock(returncode=1, stderr="Rebase conflict"), # git rebase develop (failed!)
        MagicMock(returncode=0, stdout=""), # git rebase --abort
    ]

    with patch.object(ProjectLockManager, "_acquire_lock"), \
         patch.object(ProjectLockManager, "_release_lock"), \
         patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True), \
         patch("tools.orchestrator_graph.run_cmd", side_effect=cmd_responses):

        execute_issue(issue_id, project_key, metadata_dir=metadata_dir, history_file=history_file, project_root=project_root)

    state_file = metadata_dir / "projects" / project_key / "state.json"
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_data[issue_id]["status"] == "FAILED_SYSTEM"
    assert saved_data[issue_id]["error_category"] == "SYSTEM_ERROR"


@patch("tools.orchestrator_graph.run_aider", return_value=True)
def test_code_node_target_files_keyerror_prevention(mock_run_aider: MagicMock) -> None:
    """state に target_files キーが存在しない場合でも、KeyError を起こさず安全にセットされることを検証する。"""
    state: GraphState = {"issue_id": "TFG-0010", "cwd": "."}
    res = code_node(state)
    assert "target_files" in res
    assert isinstance(res["target_files"], list)
    assert res["status"] == "code_completed"


def test_run_pytest_node_nonexistent_candidate_handling(tmp_path: Path) -> None:
    """候補テストファイルがディスク上に存在しない場合、pytest に渡されず全滅エラーを回避することを検証する。"""
    # Create fake tests dir with one safe test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    safe_test = tests_dir / "test_safe.py"
    safe_test.write_text("def test_ok(): assert True\n", encoding="utf-8")

    # Target files has a non-existent file whose candidate tests/test_nonexistent.py does not exist
    state: GraphState = {
        "issue_id": "TFG-0011",
        "cwd": str(tmp_path),
        "target_files": ["src/nonexistent.py"],
    }
    with patch("tools.orchestrator_graph.run_cmd", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        res = run_pytest_node(state)
        assert res["status"] == "test_passed"


def test_escalate_node_defensive_classification_fallback() -> None:
    """escalate_node に status 未確定 (running 等) で進入した場合、error_category に基づいて FAILED_B7 / FAILED_SYSTEM へ安全分類されることを検証する。"""
    # 1. LINT_ERROR ➔ FAILED_B7
    state1: GraphState = {"issue_id": "TFG-0020", "status": "running", "error_category": "LINT_ERROR"}
    res1 = escalate_node(state1)
    assert res1["status"] == "FAILED_B7"

    # 2. TEST_ERROR ➔ FAILED_B7
    state2: GraphState = {"issue_id": "TFG-0020", "status": "running", "error_category": "TEST_ERROR"}
    res2 = escalate_node(state2)
    assert res2["status"] == "FAILED_B7"

    # 3. REVIEW_REJECTED ➔ FAILED_B7
    state3: GraphState = {"issue_id": "TFG-0020", "status": "running", "error_category": "REVIEW_REJECTED"}
    res3 = escalate_node(state3)
    assert res3["status"] == "FAILED_B7"

    # 4. SYSTEM_ERROR ➔ FAILED_SYSTEM
    state4: GraphState = {"issue_id": "TFG-0020", "status": "running", "error_category": "SYSTEM_ERROR"}
    res4 = escalate_node(state4)
    assert res4["status"] == "FAILED_SYSTEM"

    # 5. Already determined FAILED_B7 is preserved
    state5: GraphState = {"issue_id": "TFG-0020", "status": "FAILED_B7", "error_category": "LINT_ERROR"}
    res5 = escalate_node(state5)
    assert res5["status"] == "FAILED_B7"


def test_issue_detail_file_loading_in_execute_issue(tmp_path: Path) -> None:
    """execute_issue が metadata/projects/<PROJECT_KEY>/issues/<ISSUE_ID>.md を優先ロードすることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    issues_dir = meta_tfg / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    sat_dir = project_root / "projects" / "tfg_sat"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "dummy.py").write_text("# dummy", encoding="utf-8")

    (meta_tfg / "project.json").write_text(json.dumps({"key": "TFG", "base_branch": "main"}), encoding="utf-8")
    (meta_tfg / "state.json").write_text(json.dumps({}), encoding="utf-8")

    registry_file = metadata_dir / ".project-registry.json"
    registry_file.write_text(
        json.dumps({
            "projects": {
                "TFG": {
                    "name": "tfg_sat",
                    "dir": "projects/tfg_sat",
                    "meta": "metadata/projects/TFG",
                }
            }
        }),
        encoding="utf-8"
    )

    issue_md = issues_dir / "TFG-0005.md"
    issue_md.write_text("# TFG-0005 Special Specification\nDetail specification content", encoding="utf-8")

    captured_initial_state = {}

    def mock_invoke(state: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal captured_initial_state
        captured_initial_state = state
        state["status"] = "COMPLETED"
        return state

    mock_app = MagicMock()
    mock_app.invoke.side_effect = mock_invoke

    mock_workflow = MagicMock()
    mock_workflow.compile.return_value = mock_app

    with patch("tools.orchestrator_graph.StateGraph", return_value=mock_workflow), \
         patch("tools.orchestrator_graph.run_cmd", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        execute_issue("TFG-0005", "TFG", metadata_dir=metadata_dir, project_root=project_root)

    assert captured_initial_state.get("instruction") == "# TFG-0005 Special Specification\nDetail specification content"


def test_lint_node_passes_ignore_e501_flag() -> None:
    """lint_node が ruff check 呼び出し時に --ignore E501 オプションを付与することを検証する。"""
    executed_cmds = []

    def mock_run_cmd(cmd, cwd=None, timeout=300):
        executed_cmds.append(" ".join(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    state: GraphState = {
        "issue_id": "TFG-0006",
        "project_key": "TFG",
        "execution_id": "123",
        "generation": 0,
        "status": "running",
        "error": None,
        "error_category": None,
        "llm_timeout_count": 0,
        "review_round": 0,
        "lint_round": 0,
        "test_round": 0,
        "max_round": 3,
        "target_files": ["src/dummy.py"],
        "instruction": "",
        "cwd": "/dummy",
        "base_branch": "develop",
        "aider_message": "",
        "impl_plan": None,
        "lint_result": None,
        "test_result": None,
        "review_verdict": None,
        "review_comments": None,
        "review_rounds": [],
        "reviewdog_result": None,
        "history_summary": None,
        "rdjson": None,
    }

    with patch("tools.orchestrator_graph.run_cmd", side_effect=mock_run_cmd), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True):
        res = lint_node(state)

    assert res["status"] == "lint_passed"
    assert any("--ignore E501" in cmd for cmd in executed_cmds)


def test_extract_target_files_from_issue_text() -> None:
    """Issue Markdown の『編集対象ファイル (Target Files)』セクションから target_files が抽出されることを検証する。"""
    from tools.orchestrator_graph import extract_target_files_from_issue_text

    text = """
# [TFG-0006] 暗号化 Office ドキュメント対応

## 3. 編集対象ファイル (Target Files)
- `src/grep/office_parser.py`
- `src/grep/engine.py`
- `src/grep/interface.py`
- `tests/test_office_parser.py`
- `tests/test_engine.py`

## 4. 除外条件・禁止事項
- スコープ外のテストファイル（例: tests/test_interface.py）を自動生成しないこと。
"""
    targets = extract_target_files_from_issue_text(text)
    assert "src/grep/office_parser.py" in targets
    assert "src/grep/engine.py" in targets
    assert "src/grep/interface.py" in targets
    assert "tests/test_office_parser.py" in targets
    assert "tests/test_engine.py" in targets
    assert "tests/test_interface.py" not in targets


def test_review_node_empty_comments_guard() -> None:
    """review_node が changes_requested かつ comments が空の応答を受け取った際に verdict を LGTM に補正することを検証する。"""
    state: GraphState = {
        "issue_id": "TFG-0006",
        "project_key": "TFG",
        "execution_id": "123",
        "generation": 0,
        "status": "running",
        "error": None,
        "error_category": None,
        "llm_timeout_count": 0,
        "review_round": 0,
        "lint_round": 0,
        "test_round": 0,
        "max_round": 3,
        "target_files": ["src/grep/engine.py"],
        "instruction": "",
        "cwd": "/dummy",
        "base_branch": "develop",
        "aider_message": "",
        "impl_plan": "Plan text",
        "lint_result": None,
        "test_result": None,
        "review_verdict": None,
        "review_comments": None,
        "review_rounds": [],
        "reviewdog_result": None,
        "history_summary": None,
        "rdjson": None,
    }

    mock_llm_res = {"verdict": "changes_requested", "comments": []}

    with patch("tools.orchestrator_graph.get_git_diff", return_value="diff text"), \
         patch("tools.llm_client.call_llm", return_value=mock_llm_res):
        res_state = review_node(state)

    assert res_state["status"] == "review_lgtm"
    assert res_state["review_verdict"] == "LGTM"


def test_run_pytest_node_dynamic_recovery_tips(tmp_path: Path) -> None:
    """run_pytest_node が pytest エラーログから不足フィクスチャや例外名を動的抽出して回復指示を構築することを検証する。"""
    state: GraphState = {
        "issue_id": "TFG-0006",
        "project_key": "TFG",
        "execution_id": "123",
        "generation": 0,
        "status": "running",
        "error": None,
        "error_category": None,
        "llm_timeout_count": 0,
        "review_round": 0,
        "lint_round": 0,
        "test_round": 0,
        "max_round": 3,
        "target_files": ["tests/test_engine.py"],
        "instruction": "",
        "cwd": str(tmp_path),
        "base_branch": "develop",
        "aider_message": "",
        "impl_plan": "Plan text",
        "lint_result": None,
        "test_result": None,
        "review_verdict": None,
        "review_comments": None,
        "review_rounds": [],
        "reviewdog_result": None,
        "history_summary": None,
        "rdjson": None,
    }

    mock_res = MagicMock(
        returncode=1,
        stdout="fixture 'temp_test_files' not found\nDID NOT RAISE EncryptedFileError\nhas no attribute 'assertRaises'",
        stderr=""
    )

    with patch("tools.orchestrator_graph.run_cmd", return_value=mock_res), \
         patch("pathlib.Path.exists", return_value=False):
        res_state = run_pytest_node(state)

    aider_msg = res_state.get("aider_message", "")
    assert "FIXTURE ERROR: The fixture 'temp_test_files' does not exist." in aider_msg
    assert "EXCEPTION ERROR: Expected exception `EncryptedFileError` was not raised." in aider_msg
    assert "SYNTAX ERROR: `self.assertRaises` is a unittest method" in aider_msg







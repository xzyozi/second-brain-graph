"""tests/test_jev_review_conformance.py - JEV レビュー合否二次検問ゲートの単体・統合テスト (Issue #50, PM-054)."""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

from tools.jev_adapter import (
    verify_review_conformance,
)
from tools.orchestrator_graph import GraphState, review_node


def test_verify_review_conformance_empty_diff() -> None:
    """空の差分 (Git diff) は即時不適合となること。"""
    is_valid, conf, detail = verify_review_conformance(
        issue_id="TEST-001",
        instruction="Add new feature",
        diff_text="",
    )
    assert is_valid is False
    assert conf == 0.0
    assert "Empty diff" in detail


def test_verify_review_conformance_pytest_failed() -> None:
    """pytest 終了コードが非ゼロの場合、即時不適合となること。"""
    is_valid, conf, detail = verify_review_conformance(
        issue_id="TEST-002",
        instruction="Fix bug in foo.py",
        diff_text="diff --git a/foo.py b/foo.py\n+x = 1",
        pytest_returncode=1,
    )
    assert is_valid is False
    assert conf == 1.0
    assert "pytest failed" in detail


def test_verify_review_conformance_passed() -> None:
    """JEV パイプラインが Yes を返した場合、適合 (True) となること。"""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.status = "SUCCESS"
    mock_response.verdict = "Yes"
    mock_response.confidence = 0.96
    mock_response.latency_ms = 35.0
    mock_pipeline.judge.return_value = mock_response

    is_valid, conf, detail = verify_review_conformance(
        issue_id="TEST-003",
        instruction="Add timeout parameter",
        diff_text="diff --git a/src/api.py b/src/api.py\n+timeout = 30",
        impl_plan="1. Modify api.py to accept timeout=30.",
        pytest_returncode=0,
        pipeline=mock_pipeline,
    )

    assert is_valid is True
    assert conf == 0.96
    assert "PASSED" in detail
    assert mock_pipeline.judge.called


def test_verify_review_conformance_rejected() -> None:
    """JEV パイプラインが No を返した場合、不適合 (False) となること。"""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.status = "SUCCESS"
    mock_response.verdict = "No"
    mock_response.confidence = 0.89
    mock_response.latency_ms = 40.0
    mock_pipeline.judge.return_value = mock_response

    is_valid, conf, detail = verify_review_conformance(
        issue_id="TEST-004",
        instruction="Fix typo in error message",
        diff_text="diff --git a/src/db.py b/src/db.py\n+import asyncpg",
        impl_plan="Fix error message string.",
        pytest_returncode=0,
        pipeline=mock_pipeline,
    )

    assert is_valid is False
    assert conf == 0.89
    assert "REJECTED" in detail


def test_verify_review_conformance_fail_open_on_exception() -> None:
    """JEV パイプライン実行中に例外が発生した場合、安全にフェイルオープン (True) すること。"""
    mock_pipeline = MagicMock()
    mock_pipeline.judge.side_effect = RuntimeError("Ollama connection timed out")

    is_valid, conf, detail = verify_review_conformance(
        issue_id="TEST-005",
        instruction="Update README",
        diff_text="diff --git a/README.md b/README.md\n+# Title",
        pipeline=mock_pipeline,
    )

    assert is_valid is True
    assert conf == 1.0
    assert "bypassed" in detail


@patch("tools.llm_client.call_llm")
@patch("tools.jev_adapter.verify_review_conformance")
@patch("tools.orchestrator_graph.get_git_diff")
def test_review_node_lgtm_confirmed_by_jev(
    mock_diff: MagicMock,
    mock_verify: MagicMock,
    mock_llm: MagicMock,
) -> None:
    """review_node: LLM が LGTM を出し JEV も Yes の場合、review_lgtm で確定すること。"""
    mock_diff.return_value = "diff --git a/src/calc.py b/src/calc.py\n+return a + b"
    mock_llm.return_value = {
        "verdict": "LGTM",
        "comments": [],
    }
    mock_verify.return_value = (True, 0.95, "JEV Review Conformance: PASSED")

    state: GraphState = {
        "issue_id": "CALC-001",
        "instruction": "Implement add",
        "impl_plan": "Add add() function",
        "target_files": ["src/calc.py"],
        "cwd": ".",
        "max_round": 3,
        "test_result": {"returncode": 0},
    }

    new_state = review_node(state)

    assert new_state["status"] == "review_lgtm"
    assert new_state["review_verdict"] == "LGTM"
    assert new_state["review_conformance_status"] == "passed"
    assert new_state["review_conformance_score"] == 0.95
    assert len(new_state["review_rounds"]) == 1
    round_log: Dict[str, Any] = new_state["review_rounds"][0]
    assert "jev_review_conformance" in round_log
    assert round_log["jev_review_conformance"]["is_valid"] is True


@patch("tools.llm_client.call_llm")
@patch("tools.jev_adapter.verify_review_conformance")
@patch("tools.orchestrator_graph.get_git_diff")
def test_review_node_lgtm_overridden_by_jev_rejection(
    mock_diff: MagicMock,
    mock_verify: MagicMock,
    mock_llm: MagicMock,
) -> None:
    """review_node: LLM が LGTM を出したが JEV が No の場合、changes_requested に上書きされ差し戻されること。"""
    mock_diff.return_value = "diff --git a/src/calc.py b/src/calc.py\n+return a - b"
    mock_llm.return_value = {
        "verdict": "LGTM",
        "comments": [],
    }
    mock_verify.return_value = (
        False,
        0.88,
        "JEV Review Conformance: REJECTED (Unimplemented requirements)",
    )

    state: GraphState = {
        "issue_id": "CALC-002",
        "instruction": "Implement add",
        "impl_plan": "Add add() function",
        "target_files": ["src/calc.py"],
        "cwd": ".",
        "max_round": 3,
        "review_round": 0,
        "test_result": {"returncode": 0},
    }

    new_state = review_node(state)

    assert new_state["status"] == "retry_code"
    assert new_state["review_verdict"] == "changes_requested"
    assert new_state["review_conformance_status"] == "rejected"
    assert new_state["error_category"] == "REVIEW_REJECTED"
    assert "【JEV REVIEW REJECTED】" in new_state["aider_message"]
    round_log: Dict[str, Any] = new_state["review_rounds"][0]
    assert "jev_review_conformance" in round_log
    assert round_log["jev_review_conformance"]["is_valid"] is False


@patch("tools.llm_client.call_llm")
@patch("tools.jev_adapter.verify_review_conformance")
@patch("tools.orchestrator_graph.get_git_diff")
def test_review_node_changes_requested_skips_jev(
    mock_diff: MagicMock,
    mock_verify: MagicMock,
    mock_llm: MagicMock,
) -> None:
    """review_node: LLM が既に changes_requested を返している場合、JEV 二次検問はスキップされること。"""
    mock_diff.return_value = "diff --git a/src/calc.py b/src/calc.py\n+pass"
    mock_llm.return_value = {
        "verdict": "changes_requested",
        "comments": [
            {"file": "src/calc.py", "line": 1, "message": "Incomplete", "severity": "ERROR"}
        ],
    }

    state: GraphState = {
        "issue_id": "CALC-003",
        "instruction": "Implement add",
        "target_files": ["src/calc.py"],
        "cwd": ".",
        "max_round": 3,
        "review_round": 0,
    }

    new_state = review_node(state)

    assert new_state["status"] == "retry_code"
    assert new_state["review_verdict"] == "changes_requested"
    assert mock_verify.called is False
    assert "review_conformance_status" not in new_state

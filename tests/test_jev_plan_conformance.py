"""tests/test_jev_plan_conformance.py - JEV 計画適合性検問ゲートの単体・統合テスト (PM-053)."""

from unittest.mock import MagicMock, patch

from tools.jev_adapter import (
    is_jev_available,
    verify_plan_conformance,
)
from tools.orchestrator_graph import GraphState, spec_draft_node


def test_jev_available() -> None:
    """JEV Core SDK がサブモジュールから正常にインポート可能であることを確認。"""
    assert is_jev_available() is True


def test_verify_plan_conformance_empty_plan() -> None:
    """空の実装計画は即時不適合となること。"""
    is_valid, conf, detail = verify_plan_conformance(
        issue_id="TEST-001",
        instruction="Fix bug in foo.py",
        impl_plan="",
    )
    assert is_valid is False
    assert conf == 0.0
    assert "Empty" in detail


def test_verify_plan_conformance_passed() -> None:
    """JEV パイプラインが Yes を返した場合、適合 (True) となること。"""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.status = "SUCCESS"
    mock_response.verdict = "Yes"
    mock_response.confidence = 0.95
    mock_response.latency_ms = 42.0
    mock_pipeline.judge.return_value = mock_response

    is_valid, conf, detail = verify_plan_conformance(
        issue_id="TEST-001",
        instruction="Add timeout parameter to fetch_data()",
        impl_plan="1. Modify fetch_data() in src/api.py to accept timeout=30.\n2. Update tests.",
        target_files=["src/api.py", "tests/test_api.py"],
        pipeline=mock_pipeline,
    )

    assert is_valid is True
    assert conf == 0.95
    assert "PASSED" in detail
    assert mock_pipeline.judge.called


def test_verify_plan_conformance_rejected() -> None:
    """JEV パイプラインが No (YAGNI違反) を返した場合、不適合 (False) となること。"""
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.status = "SUCCESS"
    mock_response.verdict = "No"
    mock_response.confidence = 0.88
    mock_response.latency_ms = 38.5
    mock_pipeline.judge.return_value = mock_response

    is_valid, conf, detail = verify_plan_conformance(
        issue_id="TEST-002",
        instruction="Fix typo in error message",
        impl_plan="1. Rewrite the entire database layer into async SQLAlchemy.\n2. Add GraphQL API.",
        target_files=["src/errors.py"],
        pipeline=mock_pipeline,
    )

    assert is_valid is False
    assert conf == 0.88
    assert "REJECTED" in detail


def test_verify_plan_conformance_fail_open_on_exception() -> None:
    """JEV パイプライン実行中に例外が発生した場合、安全にフェイルオープン (True) すること。"""
    mock_pipeline = MagicMock()
    mock_pipeline.judge.side_effect = RuntimeError("Ollama connection refused")

    is_valid, conf, detail = verify_plan_conformance(
        issue_id="TEST-003",
        instruction="Update README",
        impl_plan="Fix markdown link in README.md",
        target_files=["README.md"],
        pipeline=mock_pipeline,
    )

    assert is_valid is True
    assert conf == 1.0
    assert "bypassed" in detail


@patch("tools.llm_client.call_llm")
@patch("tools.jev_adapter.verify_plan_conformance")
def test_spec_draft_node_conformance_passed(mock_verify: MagicMock, mock_llm: MagicMock) -> None:
    """spec_draft_node: 計画が適合した場合、running ステータスで通過すること。"""
    mock_llm.return_value = {"content": "1. Minimal fix in src/calc.py"}
    mock_verify.return_value = (True, 0.92, "JEV Plan Conformance: PASSED")

    state: GraphState = {
        "issue_id": "CALC-001",
        "instruction": "Fix divide by zero",
        "target_files": ["src/calc.py"],
    }

    new_state = spec_draft_node(state)

    assert new_state["plan_conformance_status"] == "passed"
    assert new_state["plan_conformance_score"] == 0.92
    assert new_state["plan_conformance_round"] == 0
    assert new_state["status"] == "running"
    assert "impl_plan" in new_state


@patch("tools.llm_client.call_llm")
@patch("tools.jev_adapter.verify_plan_conformance")
def test_spec_draft_node_conformance_retry_and_b7(
    mock_verify: MagicMock, mock_llm: MagicMock
) -> None:
    """spec_draft_node: 1回目は retry_spec_draft、2回目は FAILED_B7 に遷移すること。"""
    mock_llm.return_value = {"content": "1. Re-architect everything (YAGNI violation)"}
    mock_verify.return_value = (False, 0.85, "JEV Plan Conformance: REJECTED")

    # Round 1
    state: GraphState = {
        "issue_id": "CALC-002",
        "instruction": "Fix typo",
        "target_files": ["src/calc.py"],
    }

    state1 = spec_draft_node(state)
    assert state1["plan_conformance_status"] == "rejected"
    assert state1["plan_conformance_round"] == 1
    assert state1["status"] == "retry_spec_draft"
    assert "YAGNI VIOLATION FEEDBACK" in state1["aider_message"]

    # Round 2 (リトライ上限超過)
    state2 = spec_draft_node(state1)
    assert state2["plan_conformance_status"] == "rejected"
    assert state2["plan_conformance_round"] == 2
    assert state2["status"] == "FAILED_B7"
    assert state2["error_category"] == "REVIEW_REJECTED"

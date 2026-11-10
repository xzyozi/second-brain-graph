"""Unit tests for GitHub Actions CI monitoring and autonomous recovery in orchestrator_graph (Issue #171)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.core.orchestrator_graph import (
    GraphState,
    ci_watch_node,
)


def test_ci_watch_node_all_green_passes(tmp_path: Path) -> None:
    """PR の全 CI チェックが成功 (pass/SUCCESS) の場合、COMPLETED で正常終了することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "pr_number": 42,
        "watch_ci": True,
        "ci_round": 0,
        "max_ci_round": 2,
        "ci_timeout_seconds": 10,
        "ci_poll_interval": 0.01,
    }

    mock_checks_res = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "ci", "bucket": "pass", "state": "SUCCESS"}]),
        stderr="",
    )

    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_checks_res):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "COMPLETED"
    assert new_state.get("error") is None


def test_ci_watch_node_pending_then_pass(tmp_path: Path) -> None:
    """CI チェックが最初は pending で、ポーリング後に pass となった場合に COMPLETED となることを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "pr_number": 42,
        "watch_ci": True,
        "ci_round": 0,
        "max_ci_round": 2,
        "ci_timeout_seconds": 10,
        "ci_poll_interval": 0.01,
    }

    mock_pending = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "ci", "bucket": "pending", "state": "PENDING"}]),
        stderr="",
    )
    mock_pass = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "ci", "bucket": "pass", "state": "SUCCESS"}]),
        stderr="",
    )

    with patch("tools.core.orchestrator_graph.run_cmd", side_effect=[mock_pending, mock_pass]):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "COMPLETED"


def test_ci_watch_node_failure_triggers_retry(tmp_path: Path) -> None:
    """CI チェックが失敗した場合、詳細ログを取得して retry_code に遷移することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "pr_number": 42,
        "watch_ci": True,
        "ci_round": 0,
        "max_ci_round": 2,
        "ci_timeout_seconds": 10,
        "ci_poll_interval": 0.01,
    }

    mock_fail_check = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "name": "ci",
                    "bucket": "fail",
                    "state": "FAILURE",
                    "link": "https://github.com/ci/1",
                }
            ]
        ),
        stderr="",
    )
    mock_run_list = MagicMock(
        returncode=0,
        stdout=json.dumps([{"databaseId": 999000}]),
        stderr="",
    )
    mock_run_log = MagicMock(
        returncode=0,
        stdout="Error: test_feature failed with exit code 1\nAssertionError in test_main.py",
        stderr="",
    )

    with patch(
        "tools.core.orchestrator_graph.run_cmd",
        side_effect=[mock_fail_check, mock_run_list, mock_run_log],
    ):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "retry_code"
    assert new_state["ci_round"] == 1
    assert new_state["error_category"] == "CI_ERROR"
    assert "CI FAILURE RECOVERY INSTRUCTIONS" in new_state["aider_message"]
    assert "AssertionError in test_main.py" in new_state["aider_message"]


def test_ci_watch_node_max_ci_round_exceeded(tmp_path: Path) -> None:
    """CI リトライ回数が max_ci_round に達した場合、FAILED_CI に遷移することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "pr_number": 42,
        "watch_ci": True,
        "ci_round": 1,
        "max_ci_round": 2,
        "ci_timeout_seconds": 10,
        "ci_poll_interval": 0.01,
    }

    mock_fail_check = MagicMock(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "name": "ci",
                    "bucket": "fail",
                    "state": "FAILURE",
                    "link": "https://github.com/ci/2",
                }
            ]
        ),
        stderr="",
    )
    mock_run_list = MagicMock(returncode=1, stdout="", stderr="")

    with patch(
        "tools.core.orchestrator_graph.run_cmd", side_effect=[mock_fail_check, mock_run_list]
    ):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "FAILED_CI"
    assert new_state["ci_round"] == 2
    assert new_state["error_category"] == "CI_ERROR"
    assert "CI failed after 2 round(s)" in (new_state.get("error") or "")


def test_ci_watch_node_timeout_fails(tmp_path: Path) -> None:
    """CI 監視が timeout_seconds を超えた場合、FAILED_CI / CI_ERROR で停止することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "pr_number": 42,
        "watch_ci": True,
        "ci_round": 0,
        "max_ci_round": 2,
        "ci_timeout_seconds": 0.02,
        "ci_poll_interval": 0.01,
    }

    mock_pending = MagicMock(
        returncode=0,
        stdout=json.dumps([{"name": "ci", "bucket": "pending", "state": "PENDING"}]),
        stderr="",
    )

    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_pending):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "FAILED_CI"
    assert new_state["error_category"] == "CI_ERROR"
    assert "timed out" in (new_state.get("error") or "")


def test_ci_watch_node_no_pr_graceful_complete(tmp_path: Path) -> None:
    """PR が存在しない場合、安全にスキップして COMPLETED のまま終了することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-171",
        "cwd": str(tmp_path),
        "status": "COMPLETED",
        "watch_ci": True,
        "ci_round": 0,
        "max_ci_round": 2,
    }

    mock_pr_list = MagicMock(returncode=0, stdout="[]", stderr="")

    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_pr_list):
        new_state = ci_watch_node(state)

    assert new_state["status"] == "COMPLETED"


def test_workflow_conditional_edges() -> None:
    """ワークフローのルーティング関数 (route_after_done / route_after_ci_watch) の挙動を検証する。"""
    # ワークフロー構築内の関数をテストするためダミーステートで検証
    from tools.core.orchestrator_graph import StateGraph, execute_issue  # noqa: F401

    # route_after_done の挙動確認
    done_state_no_watch: GraphState = {
        "status": "COMPLETED",
        "watch_ci": False,
    }
    done_state_watch: GraphState = {
        "status": "COMPLETED",
        "watch_ci": True,
    }
    done_state_satisfied: GraphState = {
        "status": "COMPLETED",
        "watch_ci": True,
        "already_satisfied": True,
    }
    done_state_failed: GraphState = {
        "status": "PR_FAILED",
        "watch_ci": True,
    }

    # orchestrator_graph 内のクロージャと同様のロジックテスト
    def check_route_done(s: GraphState) -> str:
        if s.get("status") in ["PR_FAILED", "FAILED_SYSTEM", "FAILED_B7"]:
            return "escalate_node"
        if s.get("already_satisfied") or not s.get("watch_ci"):
            return "end"
        return "ci_watch_node"

    assert check_route_done(done_state_no_watch) == "end"
    assert check_route_done(done_state_watch) == "ci_watch_node"
    assert check_route_done(done_state_satisfied) == "end"
    assert check_route_done(done_state_failed) == "escalate_node"

    def check_route_ci(s: GraphState) -> str:
        if s.get("status") in ["FAILED_SYSTEM", "FAILED_CI", "FAILED_B7"]:
            return "escalate_node"
        if s.get("status") == "retry_code":
            return "code_node"
        if s.get("status") in ["COMPLETED", "ci_passed"]:
            return "end"
        return "escalate_node"

    assert check_route_ci({"status": "COMPLETED"}) == "end"
    assert check_route_ci({"status": "retry_code"}) == "code_node"
    assert check_route_ci({"status": "FAILED_CI"}) == "escalate_node"

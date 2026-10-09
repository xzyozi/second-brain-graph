"""reviewdog 未導入の事前判定 (Issue #106) のテスト。"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from tools.doctor import check_reviewdog
from tools.orchestrator_graph import GraphState, review_node


def _state() -> GraphState:
    return GraphState(
        issue_id="TFG-0004",
        project_key="TFG",
        execution_id="test_exec_rd_precheck",
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


def _run_review(which_result: str | None, run_cmd_mock: MagicMock) -> GraphState:
    with (
        patch("tools.llm_client.call_llm", return_value={"verdict": "LGTM", "comments": []}),
        patch("tools.orchestrator_graph.get_git_diff", return_value="diff text"),
        patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True),
        patch("tools.orchestrator_graph.shutil.which", return_value=which_result),
        patch("tools.orchestrator_graph.run_cmd", run_cmd_mock),
        patch(
            "tools.jev_adapter.verify_review_conformance",
            return_value=(True, 1.0, "JEV conformance passed"),
        ),
    ):
        return review_node(_state())


def test_review_node_skips_reviewdog_when_not_installed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """未導入なら reviewdog を呼ばず、スキップとして記録する。WinError 由来の警告は出ない。"""
    run_cmd_mock = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))

    with caplog.at_level(logging.INFO, logger="orchestrator_graph"):
        res = _run_review(None, run_cmd_mock)

    assert res["status"] == "review_lgtm"
    assert res["reviewdog_result"]["skipped"] == "not_installed"
    assert res["reviewdog_result"]["returncode"] is None
    assert not any("reviewdog" in str(c.args[0]) for c in run_cmd_mock.call_args_list)
    assert "Reviewdog is not installed" in caplog.text
    assert "WinError" not in caplog.text
    assert "Reviewdog pipe execution skipped or failed" not in caplog.text


def test_review_node_runs_reviewdog_when_installed() -> None:
    """導入済みなら従来どおり reviewdog を実行して結果を保存する。"""
    run_cmd_mock = MagicMock(return_value=MagicMock(returncode=0, stdout="ok", stderr=""))

    res = _run_review("/usr/bin/reviewdog", run_cmd_mock)

    assert res["reviewdog_result"]["returncode"] == 0
    assert "skipped" not in res["reviewdog_result"]
    assert any(c.args[0][0] == "reviewdog" for c in run_cmd_mock.call_args_list)


def test_check_reviewdog_warns_when_not_installed() -> None:
    with patch("tools.doctor.shutil.which", return_value=None):
        res = check_reviewdog()

    assert res.status == "WARN"
    assert "reviewdog" in res.message
    assert res.fixable is False


def test_check_reviewdog_ok_when_installed() -> None:
    with patch("tools.doctor.shutil.which", return_value="/usr/bin/reviewdog"):
        res = check_reviewdog()

    assert res.status == "OK"
    assert "/usr/bin/reviewdog" in res.message

"""tests/test_orchestrator_graph.py - OrchestratorGraph ノード・条件分岐・メタデータ更新の単体テスト."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.orchestrator_graph import (
    OrchestratorState,
    build_graph,
    build_initial_state,
    code_node,
    lint_node,
    plan_node,
    record_execution_history,
    review_node,
    route_after_lint,
    route_after_review,
    route_after_test,
    test_node,
    update_task_metadata,
)


@pytest.fixture
def sample_state() -> OrchestratorState:
    """基本 OrchestratorState のフィクスチャ."""
    return {
        "issue_id": "EC-012",
        "project_path": "projects/dummy",
        "title": "EC-012: 決済処理のバグ修正",
        "description": "アサーションエラーの修正",
        "priority": "HIGH",
        "impl_plan": "",
        "aider_message": "",
        "lint_result": {},
        "test_result": {},
        "review_verdict": "",
        "review_comments": [],
        "error_category": None,
        "last_error_message": None,
        "round": 0,
        "lint_round": 0,
        "test_round": 0,
        "max_round": 3,
        "history": [],
    }


def test_build_initial_state():
    """initial state の構築テスト."""
    state = build_initial_state("EC-999")
    assert state["issue_id"] == "EC-999"
    assert state["max_round"] == 3
    assert state["round"] == 0
    assert state["lint_round"] == 0
    assert state["test_round"] == 0


@patch("tools.orchestrator_graph.call_llm")
def test_plan_node(mock_call_llm, sample_state):
    """plan_node の実行テスト."""
    mock_call_llm.return_value = {"raw": "# 実装指示書\n1. 編集"}
    state = plan_node(sample_state)
    assert "実装指示書" in state["impl_plan"]
    mock_call_llm.assert_called_once()


@patch("tools.orchestrator_graph.run_aider")
def test_code_node(mock_run_aider, sample_state, tmp_path):
    """code_node の実行テスト."""
    mock_run_aider.return_value = True
    sample_state["project_path"] = str(tmp_path)
    sample_state["impl_plan"] = "テスト実装指示"

    state = code_node(sample_state)
    mock_run_aider.assert_called_once()
    assert state["issue_id"] == "EC-012"


@patch("subprocess.run")
def test_lint_node_pass(mock_run, sample_state):
    """lint_node 成功パステスト."""
    mock_run.return_value = MagicMock(stdout="[]", returncode=0)
    state = lint_node(sample_state)

    assert state["lint_result"]["passed"] is True
    assert state["lint_round"] == 0


@patch("subprocess.run")
def test_lint_node_fail(mock_run, sample_state):
    """lint_node 失敗パステスト (lint_round インクリメント)."""
    issues = [{"filename": "main.py", "message": "Syntax Error"}]
    mock_run.return_value = MagicMock(stdout=json.dumps(issues), returncode=1)

    state = lint_node(sample_state)
    assert state["lint_result"]["passed"] is False
    assert state["lint_round"] == 1
    assert state["error_category"] == "LINT_ERROR"
    assert "Ruff静的解析指摘事項" in state["aider_message"]


@patch("subprocess.run")
def test_test_node_fail(mock_run, sample_state, tmp_path):
    """test_node 失敗パステスト."""
    sample_state["project_path"] = str(tmp_path)
    mock_run.return_value = MagicMock(returncode=1)

    state = test_node(sample_state)
    assert state["test_result"]["passed"] is False
    assert state["test_round"] == 1
    assert state["error_category"] == "TEST_ERROR"


@patch("tools.orchestrator_graph.call_llm")
@patch("tools.orchestrator_graph.get_git_diff")
def test_review_node_rejection(mock_diff, mock_call_llm, sample_state):
    """review_node 差し戻しテスト."""
    mock_diff.return_value = "diff --git a/b"
    mock_call_llm.return_value = {
        "verdict": "changes_requested",
        "comments": [{"message": "修正が必要"}],
    }

    state = review_node(sample_state)
    assert state["review_verdict"] == "changes_requested"
    assert state["round"] == 1
    assert state["error_category"] == "REVIEW_REJECTED"


def test_routing_pure_functions(sample_state):
    """ルーティング関数の純粋性および副作用無きことの検証 (DD-003 §6.2)."""
    # 1. route_after_lint
    sample_state["lint_result"] = {"passed": True}
    assert route_after_lint(sample_state) == "test"
    assert sample_state["lint_round"] == 0  # 副作用無し

    sample_state["lint_result"] = {"passed": False}
    sample_state["lint_round"] = 1
    assert route_after_lint(sample_state) == "code"

    sample_state["lint_round"] = 3
    assert route_after_lint(sample_state) == "escalate"
    assert sample_state["lint_round"] == 3  # 二重インクリメントなきこと

    # 2. route_after_test
    sample_state["test_result"] = {"passed": True}
    assert route_after_test(sample_state) == "review"

    sample_state["test_result"] = {"passed": False}
    sample_state["test_round"] = 2
    assert route_after_test(sample_state) == "code"

    sample_state["test_round"] = 3
    assert route_after_test(sample_state) == "escalate"

    # 3. route_after_review
    sample_state["review_verdict"] = "LGTM"
    assert route_after_review(sample_state) == "done"

    sample_state["review_verdict"] = "changes_requested"
    sample_state["round"] = 1
    assert route_after_review(sample_state) == "code"

    sample_state["round"] = 3
    assert route_after_review(sample_state) == "escalate"


def test_update_task_metadata(tmp_path):
    """tasks.md メタデータ更新・タグ挿入機能のテスト."""
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text("- [ ] EC-012: 決済処理バグ\n- [ ] EC-013: ログ出力\n", encoding="utf-8")

    update_task_metadata(tmp_path, "EC-012", round_num=3, status="FAILED_B7", max_round=3)

    content = tasks_file.read_text(encoding="utf-8")
    assert "<!-- round:3 max_round:3 status:FAILED_B7 -->" in content

    # COMPLETED 更新テスト
    update_task_metadata(tmp_path, "EC-012", round_num=1, status="COMPLETED")
    content_updated = tasks_file.read_text(encoding="utf-8")
    assert "- [x] EC-012:" in content_updated
    assert "<!-- round:1 max_round:3 status:COMPLETED -->" in content_updated


def test_record_execution_history(sample_state, tmp_path, monkeypatch):
    """execution_history.json へのアトミック書き込みテスト."""
    monkeypatch.chdir(tmp_path)
    record_execution_history(sample_state, final_status="COMPLETED", actual_round=1)

    history_file = tmp_path / "tools" / ".cache" / "execution_history.json"
    assert history_file.exists()

    data = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(data["records"]) == 1
    assert data["records"][0]["issue_id"] == "EC-012"
    assert data["records"][0]["final_status"] == "COMPLETED"


def test_build_graph_structure():
    """StateGraph 構造構築のテスト."""
    compiled_graph = build_graph()
    assert compiled_graph is not None

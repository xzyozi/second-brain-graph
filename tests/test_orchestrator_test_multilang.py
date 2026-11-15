"""Unit tests for multi-language test execution in orchestrator_graph test_node (Issue #170)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.core.orchestrator_graph import (
    GraphState,
    run_pytest_node,
)
from tools.core.orchestrator_graph import (
    test_feedback_node as run_test_feedback_node,
)


def test_run_pytest_node_custom_command_success(tmp_path: Path) -> None:
    """カスタム test_command が指定され、終了コード 0 の場合 test_passed になることを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/index.ts"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "typescript",
        "test_command": "npm run custom-test",
    }

    mock_res = MagicMock(returncode=0, stdout="Tests passed!", stderr="")
    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res) as mock_run:
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert new_state["test_result"] is not None
    assert new_state["test_result"]["returncode"] == 0
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0]
    assert "npm" in called_cmd[0]
    assert called_cmd[1:] == ["run", "custom-test"]


def test_run_pytest_node_custom_command_failure_retry(tmp_path: Path) -> None:
    """カスタム test_command が失敗した場合、retry_code に遷移しリカバリ指示が生成されることを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/lib.rs"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "rust",
        "test_command": "cargo test -- --nocapture",
    }

    mock_res = MagicMock(
        returncode=1, stdout="test failed: assertion `left == right` failed", stderr=""
    )
    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "retry_code"
    assert new_state["test_round"] == 1
    assert new_state["error_category"] == "TEST_ERROR"
    assert "Satellite test command 'cargo test -- --nocapture' failed" in new_state["aider_message"]
    assert "assertion `left == right` failed" in new_state["aider_message"]


def test_run_pytest_node_failure_max_round_exceeded(tmp_path: Path) -> None:
    """テスト試行回数が max_round に達した場合、FAILED_B7 に遷移することを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/index.ts"],
        "status": "code_completed",
        "test_round": 2,
        "max_round": 3,
        "language": "typescript",
        "test_command": "npm test",
    }

    mock_res = MagicMock(returncode=1, stdout="Jest failed", stderr="")
    with patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "FAILED_B7"
    assert new_state["test_round"] == 3
    assert new_state["error_category"] == "TEST_ERROR"


def test_run_pytest_node_typescript_default_npm_test(tmp_path: Path) -> None:
    """TypeScript サテライトで test_command 未指定時、npm test が既定で実行されることを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/index.ts"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "typescript",
    }

    mock_res = MagicMock(returncode=0, stdout="All 5 tests passed", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/npm"),
        patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res) as mock_run,
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == ["/usr/bin/npm", "test"]


def test_run_pytest_node_typescript_npm_missing_graceful_pass(tmp_path: Path) -> None:
    """TypeScript サテライトで npm が環境に存在しない場合、安全に警告を出してスキップ (test_passed) することを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/index.ts"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "typescript",
    }

    with (
        patch("shutil.which", return_value=None),
        patch("tools.core.orchestrator_graph.run_cmd") as mock_run,
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert not mock_run.called
    assert "npm not found in PATH" in (new_state.get("test_result") or {}).get("stdout", "")


def test_run_pytest_node_rust_default_cargo_test(tmp_path: Path) -> None:
    """Rust サテライトで test_command 未指定時、cargo test が既定で実行されることを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/lib.rs"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "rust",
    }

    mock_res = MagicMock(returncode=0, stdout="test result: ok. 10 passed", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/cargo"),
        patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res) as mock_run,
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == ["/usr/bin/cargo", "test"]


def test_run_pytest_node_rust_cargo_missing_graceful_pass(tmp_path: Path) -> None:
    """Rust サテライトで cargo が環境に存在しない場合、安全に警告を出してスキップ (test_passed) することを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/lib.rs"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "rust",
    }

    with (
        patch("shutil.which", return_value=None),
        patch("tools.core.orchestrator_graph.run_cmd") as mock_run,
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert not mock_run.called
    assert "cargo not found in PATH" in (new_state.get("test_result") or {}).get("stdout", "")


def test_run_pytest_node_python_default_executes_pytest(tmp_path: Path) -> None:
    """Python サテライト（test_command 未指定）の場合、従来の pytest が実行されることを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["main.py"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "python",
    }

    mock_res = MagicMock(returncode=0, stdout="1 passed in 0.05s", stderr="")
    with (
        patch("tools.core.orchestrator_graph.ensure_satellite_environment", return_value="python"),
        patch("tools.core.orchestrator_graph.clean_legacy_pytest_reports", return_value=0),
        patch("tools.core.orchestrator_graph.run_cmd", return_value=mock_res) as mock_run,
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "test_passed"
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "python"
    assert "-m" in called_cmd
    assert "pytest" in called_cmd


def test_run_pytest_node_exception_system_error(tmp_path: Path) -> None:
    """テスト実行処理中に予期せぬ例外が発生した場合、FAILED_SYSTEM / SYSTEM_ERROR で安全停止することを検証する。"""
    state: GraphState = {
        "cwd": str(tmp_path),
        "target_files": ["src/index.ts"],
        "status": "code_completed",
        "test_round": 0,
        "max_round": 3,
        "language": "typescript",
        "test_command": "npm test",
    }

    with patch(
        "tools.core.orchestrator_graph.run_cmd", side_effect=OSError("Command spawn failure")
    ):
        new_state = run_pytest_node(state)

    assert new_state["status"] == "FAILED_SYSTEM"
    assert new_state["error_category"] == "SYSTEM_ERROR"
    assert "Command spawn failure" in (new_state.get("error") or "")


def test_test_feedback_node_multilang() -> None:
    """多言語サテライトでテスト失敗時、test_feedback_node が多言語対応ヘッダーを生成することを検証する。"""
    state: GraphState = {
        "issue_id": "ISSUE-170",
        "project_key": "my-ts-app",
        "target_files": ["src/index.ts"],
        "status": "retry_code",
        "test_round": 1,
        "language": "typescript",
        "test_command": "npm test",
        "test_result": {
            "returncode": 1,
            "stdout": "FAIL src/index.test.ts\nTypeError: Cannot read properties of undefined",
            "stderr": "",
        },
    }

    mock_llm_res = {"content": "Fix the undefined access by adding optional chaining."}
    with patch("tools.backends.llm_client.call_llm", return_value=mock_llm_res):
        new_state = run_test_feedback_node(state)

    assert new_state["status"] == "retry_code"
    assert "【ARCHITECT ADVICE FOR TEST FAILURE (Round 1)】" in new_state["aider_message"]
    assert "Fix the undefined access by adding optional chaining." in new_state["aider_message"]
    assert "【RAW TEST OUTPUT】" in new_state["aider_message"]
    assert "TypeError: Cannot read properties of undefined" in new_state["aider_message"]

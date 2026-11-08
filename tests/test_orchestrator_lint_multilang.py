"""Unit tests for multi-language syntax verification in orchestrator_graph lint_node (Issue #169)."""

from pathlib import Path
from typing import Any

from tools.core.orchestrator_graph import lint_node


def test_lint_node_typescript_valid_syntax(tmp_path: Path) -> None:
    """TypeScript ファイルが正常な構文の場合、lint_passed に遷移することを検証する。"""
    ts_file = tmp_path / "valid.ts"
    ts_file.write_text(
        """export interface User {
    id: number;
    name: string;
}

export function getUser(id: number): User {
    return { id, name: "Alice" };
}
""",
        encoding="utf-8",
    )

    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["valid.ts"],
        "status": "code_generated",
        "lint_round": 0,
        "max_round": 3,
    }

    new_state = lint_node(state)
    assert new_state["status"] == "lint_passed"


def test_lint_node_typescript_broken_syntax(tmp_path: Path) -> None:
    """TypeScript ファイルの構文が破損している場合、retry_code に遷移しリカバリ指示が生成されることを検証する。"""
    broken_ts = tmp_path / "broken.ts"
    broken_ts.write_text(
        """export function broken() {
    console.log("missing closing brace";
""",
        encoding="utf-8",
    )

    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["broken.ts"],
        "status": "code_generated",
        "lint_round": 0,
        "max_round": 3,
    }

    new_state = lint_node(state)
    assert new_state["status"] == "retry_code"
    assert new_state["lint_round"] == 1
    assert new_state["error_category"] == "LINT_ERROR"
    assert (
        "TypeScript/JavaScript Tree-sitter syntax verification failed" in new_state["aider_message"]
    )
    assert "broken.ts" in new_state["aider_message"]


def test_lint_node_rust_valid_syntax(tmp_path: Path) -> None:
    """Rust ファイルが正常な構文の場合、lint_passed に遷移することを検証する。"""
    rs_file = tmp_path / "lib.rs"
    rs_file.write_text(
        """pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
""",
        encoding="utf-8",
    )

    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["lib.rs"],
        "status": "code_generated",
        "lint_round": 0,
        "max_round": 3,
    }

    new_state = lint_node(state)
    assert new_state["status"] == "lint_passed"


def test_lint_node_rust_broken_syntax(tmp_path: Path) -> None:
    """Rust ファイルの構文が破損している場合、retry_code に遷移しリカバリ指示が生成されることを検証する。"""
    broken_rs = tmp_path / "broken.rs"
    broken_rs.write_text(
        """pub fn broken(a: i32) -> i32 {
    a + 1
// missing closing brace
""",
        encoding="utf-8",
    )

    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["broken.rs"],
        "status": "code_generated",
        "lint_round": 0,
        "max_round": 3,
    }

    new_state = lint_node(state)
    assert new_state["status"] == "retry_code"
    assert new_state["lint_round"] == 1
    assert new_state["error_category"] == "LINT_ERROR"
    assert "Rust syntax / AST verification failed" in new_state["aider_message"]
    assert "broken.rs" in new_state["aider_message"]


def test_lint_node_multilang_max_round_exceeded(tmp_path: Path) -> None:
    """リトライ回数が max_round に達した場合は FAILED_B7 に遷移することを検証する。"""
    broken_ts = tmp_path / "broken.ts"
    broken_ts.write_text("function { broken", encoding="utf-8")

    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["broken.ts"],
        "status": "retry_code",
        "lint_round": 2,
        "max_round": 3,
    }

    new_state = lint_node(state)
    assert new_state["status"] == "FAILED_B7"
    assert new_state["lint_round"] == 3


def test_lint_node_no_matching_targets(tmp_path: Path) -> None:
    """検査対象のファイルが存在しない場合は即座に lint_passed に遷移することを検証する。"""
    state: dict[str, Any] = {
        "cwd": str(tmp_path),
        "target_files": ["README.md", "docs/spec.txt"],
        "status": "code_generated",
    }

    new_state = lint_node(state)
    assert new_state["status"] == "lint_passed"

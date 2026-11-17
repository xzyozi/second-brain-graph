"""code_node が profile.backend == 'agy' のとき agy 経路へ分岐することを検証するテスト.

実 agy バイナリは使用しない。BackendExecutionCoordinator を模擬し、
run_agy_edit をモックして、呼び出しの配線と既存の状態遷移契約を検証する。
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tools.backends.agy_runner import AgyRunError
from tools.core.orchestrator_graph import GraphState, code_node
from tools.workspace.config_loader import ProfileConfig


def _make_agy_coordinator(dummy_profile: ProfileConfig) -> MagicMock:
    coordinator = MagicMock()
    coordinator.execute.side_effect = lambda intent, req: req["action"](dummy_profile)
    return coordinator


@patch("tools.backends.agy_runner.run_agy_edit", return_value=True)
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_dispatches_to_agy_when_profile_backend_is_agy(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """profile.backend が agy の場合、run_agy_edit を呼び、code_completed へ遷移することを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)

    state: GraphState = {
        "issue_id": "TFG-0099",
        "target_files": ["src/example.py"],
        "instruction": "Implement feature",
        "cwd": None,
    }

    result = code_node(state)

    mock_run_agy_edit.assert_called_once()
    call_kwargs = mock_run_agy_edit.call_args.kwargs
    assert call_kwargs["target_files"] == ["src/example.py"]
    assert call_kwargs["timeout"] == 1200
    assert "Implement feature" in call_kwargs["instruction"]
    assert result["status"] == "code_completed"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_uses_default_timeout_when_profile_timeout_unset(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """profile.timeout が未設定の場合、既定の 1200 秒を使うことを検証する。"""
    mock_run_agy_edit.return_value = True
    dummy_profile = ProfileConfig(backend="agy", model="agy-default")  # timeout は既定で None
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)

    state: GraphState = {
        "issue_id": "TFG-0096",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    code_node(state)

    assert mock_run_agy_edit.call_args.kwargs["timeout"] == 1200


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_timeout_retry_and_escalation(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """agy のタイムアウトが Aider と同じ LLM_TIMEOUT のリトライ・エスカレーション契約に従うことを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError("agy execution timed out after 1200 seconds")

    state: GraphState = {
        "issue_id": "TFG-0098",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }

    first = code_node(state)
    assert first["llm_timeout_count"] == 1
    assert first["error_category"] == "LLM_TIMEOUT"
    assert first["status"] == "retry_code"

    second = code_node(first)
    assert second["llm_timeout_count"] == 2
    assert second["error_category"] == "LLM_TIMEOUT"
    assert second["status"] == "FAILED_SYSTEM"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_nonzero_exit_as_failed_system(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """タイムアウト以外の agy 異常終了は、即時 FAILED_SYSTEM / SYSTEM_ERROR とすることを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError("agy process failed with returncode 2: boom")

    state: GraphState = {
        "issue_id": "TFG-0097",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    result = code_node(state)

    assert result["status"] == "FAILED_SYSTEM"
    assert result["error_category"] == "SYSTEM_ERROR"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_auth_error_as_agy_auth(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """agy の認証エラーは即時 FAILED_SYSTEM / AGY_AUTH とすることを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError(
        "agy process failed with returncode 1: unauthorized access, login required"
    )

    state: GraphState = {
        "issue_id": "TFG-0096",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    result = code_node(state)

    assert result["status"] == "FAILED_SYSTEM"
    assert result["error_category"] == "AGY_AUTH"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_quota_error_as_agy_quota(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """agy のクォータ超過・レート制限エラーは即時 FAILED_SYSTEM / AGY_QUOTA とすることを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError(
        "agy process failed with returncode 1: Resource exhausted (status 429), quota exceeded"
    )

    state: GraphState = {
        "issue_id": "TFG-0095",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    result = code_node(state)

    assert result["status"] == "FAILED_SYSTEM"
    assert result["error_category"] == "AGY_QUOTA"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_handles_agy_policy_denied_as_failed_system(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock
) -> None:
    """agy のポリシー拒否エラーは即時 FAILED_SYSTEM / AGY_POLICY_DENIED とすることを検証する。"""
    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)
    mock_run_agy_edit.side_effect = AgyRunError(
        "AGY_POLICY_DENIED: project_key=BLOCKED, operation=edit, reason=not allowed"
    )

    state: GraphState = {
        "issue_id": "TFG-0095",
        "target_files": [],
        "instruction": "x",
        "cwd": None,
    }
    result = code_node(state)

    assert result["status"] == "FAILED_SYSTEM"
    assert result["error_category"] == "AGY_POLICY_DENIED"


@patch("tools.backends.agy_runner.run_agy_edit")
@patch("tools.core.orchestrator_graph.get_coordinator")
def test_code_node_does_not_dynamically_register_new_files(
    mock_get_coordinator: MagicMock, mock_run_agy_edit: MagicMock, tmp_path: Path
) -> None:
    """Issue #187 (B12): allowed_new_file_globs でファイルが作成されても code_node は target_files へ自動追加しない。"""
    import subprocess

    dummy_profile = ProfileConfig(backend="agy", model="agy-default", timeout=1200)
    mock_get_coordinator.return_value = _make_agy_coordinator(dummy_profile)

    # テスト用 git リポジトリ作成
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    def fake_edit(*args: Any, **kwargs: Any) -> bool:
        # 編集エンジンが新しい .rs ファイルと .ts ファイルを作成したと仮定
        (repo / "src" / "helper.rs").write_text("pub fn h() {}\n", encoding="utf-8")
        (repo / "app.ts").write_text("export const a = 1;\n", encoding="utf-8")
        return True

    mock_run_agy_edit.side_effect = fake_edit

    state: GraphState = {
        "issue_id": "TFG-0097",
        "target_files": ["src/main.rs"],
        "instruction": "add helper",
        "cwd": str(repo),
        "allowed_new_file_globs": ["src/**/*.rs", "*.ts"],
    }
    result = code_node(state)

    assert result["status"] == "code_completed"
    assert result["target_files"] == ["src/main.rs"]
    assert "src/helper.rs" not in result["target_files"]
    assert "app.ts" not in result["target_files"]


def test_done_node_rejects_unauthorized_untracked_files_after_add(tmp_path: Path) -> None:
    """Issue #187 (B12): target_files 外の未追跡ファイルが残存する場合、done_node がコミット・PR作成を中断する。"""
    import subprocess

    from tools.core.orchestrator_graph import done_node

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "develop"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    # target_files 内の変更と、target_files 外の未追跡ファイルを作成
    (repo / "src" / "main.rs").write_text('fn main() { println!("ok"); }\n', encoding="utf-8")
    (repo / "src" / "helper.rs").write_text("pub fn h() {}\n", encoding="utf-8")
    # ランタイム一時ファイルは無視されるべき対象として同梱して確認
    (repo / ".agy.session.json").write_text("{}", encoding="utf-8")

    state: GraphState = {
        "issue_id": "TFG-0097",
        "project_key": "TFG",
        "target_files": ["src/main.rs"],
        "instruction": "update main",
        "cwd": str(repo),
        "base_branch": "develop",
    }
    res = done_node(state)

    assert res["status"] == "PR_FAILED"
    assert res["error_category"] == "PR_ERROR"
    assert res.get("boundary_warning") is not None
    assert "src/helper.rs" in str(res["boundary_warning"])
    assert ".agy.session.json" not in str(res["boundary_warning"])

    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head_after == head_before

    staged_after = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert staged_after == ""

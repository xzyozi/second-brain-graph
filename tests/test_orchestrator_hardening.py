"""orchestrator_graph の堅牢化 (Issue #87-#90) に関するテスト。"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from langgraph.errors import GraphRecursionError

from tools.orchestrator_graph import (
    GraphState,
    ProjectLockManager,
    _fail_system,
    _route_unknown_status,
    compute_recursion_limit,
    execute_issue,
)


def test_route_unknown_status_goes_to_escalate() -> None:
    """想定外の status は escalate_node へ送られる (Issue #89)。"""
    # 型に存在しない status を意図的に注入するため Any 経由で渡す
    unexpected_status: Any = "unexpected"
    state = GraphState(issue_id="TFG-0001", status=unexpected_status)
    assert _route_unknown_status("lint_node", state) == "escalate_node"


def test_fail_system_records_state_and_history() -> None:
    """error 指定時は state.json と実行履歴の両方を更新する (Issue #88)。"""
    with (
        patch("tools.orchestrator_graph.update_task_state") as mock_update,
        patch("tools.orchestrator_graph.safe_record_execution_history") as mock_history,
    ):
        _fail_system(
            "TFG",
            "TFG-0001",
            "boom",
            cwd="/tmp/sat",
            metadata_dir=Path("metadata"),
            history_file=None,
        )

    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs["status"] == "FAILED_SYSTEM"
    assert mock_update.call_args.kwargs["error_category"] == "SYSTEM_ERROR"
    record = mock_history.call_args.args[0]
    assert record["error"] == "boom"
    assert record["cwd"] == "/tmp/sat"
    assert mock_history.call_args.kwargs["final_status"] == "FAILED_SYSTEM"


def test_fail_system_without_error_skips_history() -> None:
    """error が None の場合は state.json のみ更新する (auto-stash 失敗時の従来挙動)。"""
    with (
        patch("tools.orchestrator_graph.update_task_state") as mock_update,
        patch("tools.orchestrator_graph.safe_record_execution_history") as mock_history,
    ):
        _fail_system(
            "TFG",
            "TFG-0001",
            None,
            cwd=None,
            metadata_dir=Path("metadata"),
            history_file=None,
        )

    mock_update.assert_called_once()
    mock_history.assert_not_called()


def _setup_satellite(project_root: Path) -> Path:
    """execute_issue 用の最小サテライト構成とメタデータを作成する。"""
    metadata_dir = project_root / "metadata"
    sat_dir = project_root / "projects" / "test_file_grep"
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    target_file = sat_dir / "src" / "grep" / "office_parser.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Target file", encoding="utf-8")

    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    (meta_tfg / "project.json").write_text(
        json.dumps(
            {"key": "TFG", "base_branch": "develop", "target_files": ["src/grep/office_parser.py"]}
        ),
        encoding="utf-8",
    )
    (metadata_dir / ".project-registry.json").write_text(
        json.dumps(
            {
                "projects": {
                    "TFG": {
                        "name": "test_file_grep",
                        "dir": "projects/test_file_grep",
                        "meta": "metadata/projects/TFG",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return metadata_dir


def _run_fresh_execute(tmp_path: Path, unmerged_stdout: str, branch_mv_rc: int = 0) -> list[str]:
    """Fresh モードで execute_issue を実行し、発行された git コマンド一覧を返す。"""
    metadata_dir = _setup_satellite(tmp_path)
    executed: list[str] = []

    def mock_run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> MagicMock:
        cmd_str = " ".join(cmd)
        executed.append(cmd_str)
        if "log develop..sbos/TFG-0004" in cmd_str:
            return MagicMock(returncode=0, stdout=unmerged_stdout, stderr="")
        if "branch -m" in cmd_str:
            return MagicMock(returncode=branch_mv_rc, stdout="", stderr="mv failed")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(ProjectLockManager, "_acquire_lock"),
        patch.object(ProjectLockManager, "_release_lock"),
        patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True),
        patch("tools.orchestrator_graph.run_cmd", side_effect=mock_run_cmd),
        patch("tools.orchestrator_graph.StateGraph") as mock_state_graph,
    ):
        mock_app = MagicMock()
        mock_app.invoke.return_value = {"status": "COMPLETED"}
        mock_state_graph.return_value.compile.return_value = mock_app

        execute_issue(
            "TFG-0004",
            "TFG",
            metadata_dir=metadata_dir,
            history_file=tmp_path / "tools" / ".cache" / "execution_history.json",
            project_root=tmp_path,
        )
    return executed


def test_fresh_mode_backs_up_branch_with_unmerged_commits(tmp_path: Path) -> None:
    """未マージコミットがある作業ブランチは強制削除せず backup/ へ退避される (Issue #90)。"""
    executed = _run_fresh_execute(tmp_path, unmerged_stdout="abc123 wip commit\n")

    assert any("branch -m sbos/TFG-0004 backup/sbos/TFG-0004-" in c for c in executed)
    assert not any("branch -D sbos/TFG-0004" in c for c in executed)
    assert any("switch -c sbos/TFG-0004 develop" in c for c in executed)


def test_fresh_mode_deletes_branch_without_unmerged_commits(tmp_path: Path) -> None:
    """未マージコミットが無い場合は従来どおり branch -D で再作成される。"""
    executed = _run_fresh_execute(tmp_path, unmerged_stdout="")

    assert any("branch -D sbos/TFG-0004" in c for c in executed)
    assert not any("branch -m" in c for c in executed)


def test_fresh_mode_aborts_when_backup_fails(tmp_path: Path) -> None:
    """退避に失敗した場合はブランチを再作成せず FAILED_SYSTEM で中断する。"""
    executed = _run_fresh_execute(tmp_path, unmerged_stdout="abc123 wip\n", branch_mv_rc=1)

    assert not any("branch -D sbos/TFG-0004" in c for c in executed)
    assert not any("switch -c sbos/TFG-0004" in c for c in executed)
    state_file = tmp_path / "metadata" / "projects" / "TFG" / "state.json"
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["TFG-0004"]["status"] == "FAILED_SYSTEM"


def test_compute_recursion_limit_exceeds_langgraph_default() -> None:
    """既定 max_round=3 の最悪経路は LangGraph 既定 (25) を超えるため、明示的に引き上げる (Issue #87)。"""
    assert compute_recursion_limit(3) > 25
    # max_round が大きいほど上限も単調に増える
    assert compute_recursion_limit(5) > compute_recursion_limit(3)


def _run_execute_with_invoke(
    tmp_path: Path, invoke_side_effect: Exception | None
) -> tuple[MagicMock, Path]:
    """StateGraph をモックして execute_issue を実行し、(mock_app, state.json パス) を返す。"""
    metadata_dir = _setup_satellite(tmp_path)

    with (
        patch.object(ProjectLockManager, "_acquire_lock"),
        patch.object(ProjectLockManager, "_release_lock"),
        patch("tools.orchestrator_graph.is_in_git_workspace", return_value=False),
        patch("tools.orchestrator_graph.escalate_node", side_effect=lambda s: s),
        patch("tools.orchestrator_graph.StateGraph") as mock_state_graph,
    ):
        mock_app = MagicMock()
        if invoke_side_effect is not None:
            mock_app.invoke.side_effect = invoke_side_effect
        else:
            mock_app.invoke.return_value = {"status": "COMPLETED"}
        mock_state_graph.return_value.compile.return_value = mock_app

        execute_issue(
            "TFG-0004",
            "TFG",
            metadata_dir=metadata_dir,
            history_file=tmp_path / "tools" / ".cache" / "execution_history.json",
            project_root=tmp_path,
        )
    return mock_app, metadata_dir / "projects" / "TFG" / "state.json"


def test_execute_issue_passes_recursion_limit(tmp_path: Path) -> None:
    """app.invoke に計算済みの recursion_limit が渡される (Issue #87)。"""
    mock_app, _ = _run_execute_with_invoke(tmp_path, None)

    config = mock_app.invoke.call_args.kwargs["config"]
    assert config["recursion_limit"] == compute_recursion_limit(3)


def test_execute_issue_recursion_error_becomes_failed_b7(tmp_path: Path) -> None:
    """GraphRecursionError は FAILED_SYSTEM ではなく FAILED_B7 として記録される (Issue #87)。"""
    _, state_file = _run_execute_with_invoke(tmp_path, GraphRecursionError("limit"))

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["TFG-0004"]["status"] == "FAILED_B7"

"""連続 FAILED_B7 ガード (Issue #91) のテスト。"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.test_orchestrator_hardening import _setup_satellite
from tools.metadata_store import MAX_CONSECUTIVE_B7, next_consecutive_b7, update_task_state
from tools.orchestrator_graph import ProjectLockManager, execute_issue

ISSUE_ID = "TFG-0004"


@pytest.mark.parametrize(
    ("previous", "final_status", "expected"),
    [
        (0, "FAILED_B7", 1),
        (1, "FAILED_B7", 2),
        (2, "COMPLETED", 0),
        (1, "FAILED_SYSTEM", 1),
        (1, "PR_FAILED", 1),
        # escalate_node が書き換える最終 status は数えない (自動 Resume の対象外のため)
        (1, "ESCALATED_NEEDS_REVISION", 1),
    ],
)
def test_next_consecutive_b7(previous: int, final_status: str, expected: int) -> None:
    assert next_consecutive_b7(previous, final_status) == expected


def test_update_task_state_carries_over_consecutive_b7(tmp_path: Path) -> None:
    """consecutive_b7 を省略した更新 (FAILED_SYSTEM 等) でカウンタが消えない。"""
    state_file = tmp_path / "state.json"

    update_task_state("TFG", ISSUE_ID, "FAILED_B7", consecutive_b7=2, state_file=state_file)
    update_task_state("TFG", ISSUE_ID, "FAILED_SYSTEM", state_file=state_file)

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["status"] == "FAILED_SYSTEM"
    assert saved[ISSUE_ID]["consecutive_b7"] == 2


def test_update_task_state_defaults_to_zero_for_legacy_entry(tmp_path: Path) -> None:
    """consecutive_b7 を持たない旧形式のエントリは 0 として扱う。"""
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({ISSUE_ID: {"status": "FAILED_B7", "review_round": 1}}), encoding="utf-8"
    )

    update_task_state("TFG", ISSUE_ID, "FAILED_B7", state_file=state_file)

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["consecutive_b7"] == 0


def _write_state(metadata_dir: Path, status: str, consecutive_b7: int) -> Path:
    state_file = metadata_dir / "projects" / "TFG" / "state.json"
    state_file.write_text(
        json.dumps(
            {
                ISSUE_ID: {
                    "status": status,
                    "review_round": 3,
                    "max_round": 3,
                    "error_category": "REVIEW_REJECTED",
                    "consecutive_b7": consecutive_b7,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    return state_file


def _run(tmp_path: Path, final_status: str = "COMPLETED", **kwargs: Any) -> MagicMock:
    """StateGraph をモックして execute_issue を実行し、mock_app を返す。"""
    metadata_dir = tmp_path / "metadata"
    with (
        patch.object(ProjectLockManager, "_acquire_lock"),
        patch.object(ProjectLockManager, "_release_lock"),
        patch("tools.orchestrator_graph.is_in_git_workspace", return_value=False),
        patch("tools.orchestrator_graph.StateGraph") as mock_state_graph,
    ):
        mock_app = MagicMock()
        mock_app.invoke.return_value = {"status": final_status}
        mock_state_graph.return_value.compile.return_value = mock_app

        execute_issue(
            ISSUE_ID,
            "TFG",
            metadata_dir=metadata_dir,
            history_file=tmp_path / "tools" / ".cache" / "execution_history.json",
            project_root=tmp_path,
            **kwargs,
        )
    return mock_app


def test_auto_resume_blocked_after_consecutive_b7(tmp_path: Path) -> None:
    """連続 FAILED_B7 が上限に達していると、自動 Resume は実行されず state も変わらない。"""
    _setup_satellite(tmp_path)
    state_file = _write_state(tmp_path / "metadata", "FAILED_B7", MAX_CONSECUTIVE_B7)
    before = state_file.read_text(encoding="utf-8")

    mock_app = _run(tmp_path)

    mock_app.invoke.assert_not_called()
    assert state_file.read_text(encoding="utf-8") == before
    history = json.loads(
        (tmp_path / "tools" / ".cache" / "execution_history.json").read_text(encoding="utf-8")
    )
    assert "Auto-resume blocked" in history["records"][-1]["error_message"]


def test_auto_resume_allowed_below_limit(tmp_path: Path) -> None:
    """上限未満なら従来どおり自動 Resume で実行される。"""
    _setup_satellite(tmp_path)
    _write_state(tmp_path / "metadata", "FAILED_B7", MAX_CONSECUTIVE_B7 - 1)

    mock_app = _run(tmp_path, final_status="FAILED_B7")

    mock_app.invoke.assert_called_once()


@pytest.mark.parametrize("kwargs", [{"resume": True}, {"fresh": True}])
def test_explicit_resume_or_fresh_bypasses_guard(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    """明示的な --resume / --fresh は上限に達していても実行できる。"""
    _setup_satellite(tmp_path)
    _write_state(tmp_path / "metadata", "FAILED_B7", MAX_CONSECUTIVE_B7)

    mock_app = _run(tmp_path, **kwargs)

    mock_app.invoke.assert_called_once()


def test_counter_increments_on_failed_b7_and_resets_on_completed(tmp_path: Path) -> None:
    """FAILED_B7 終了で +1、COMPLETED 終了で 0 に戻る。"""
    _setup_satellite(tmp_path)
    state_file = _write_state(tmp_path / "metadata", "FAILED_B7", 1)

    _run(tmp_path, final_status="FAILED_B7")
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["consecutive_b7"] == 2

    _run(tmp_path, final_status="COMPLETED", resume=True)
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["consecutive_b7"] == 0


def test_fresh_restarts_count_from_zero(tmp_path: Path) -> None:
    """--fresh での実行は 0 から数え直す。"""
    _setup_satellite(tmp_path)
    state_file = _write_state(tmp_path / "metadata", "FAILED_B7", MAX_CONSECUTIVE_B7)

    _run(tmp_path, final_status="FAILED_B7", fresh=True)

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["consecutive_b7"] == 1

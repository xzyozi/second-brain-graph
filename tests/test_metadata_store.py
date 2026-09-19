"""Unit tests for tools/metadata_store.py

Issue #22 (DD-003 §10.4) メタデータ・状態管理モジュールの単体テスト。
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.metadata_store import (
    ErrorCategory,
    ProjectLockManager,
    TaskStatus,
    record_execution_history,
    resolve_project_context,
    safe_record_execution_history,
    update_task_state,
    validate_issue_id,
    validate_project_consistency,
    write_event,
)

# ==============================================================================
# 1. TaskStatus & ErrorCategory Tests
# ==============================================================================


def test_task_status_enum_values() -> None:
    """TaskStatus Enum が主要なステータス文字列を正しく保持していることを確認する。"""
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.CODE_COMPLETED.value == "code_completed"
    assert TaskStatus.COMPLETED.value == "COMPLETED"
    assert TaskStatus.FAILED_SYSTEM.value == "FAILED_SYSTEM"
    assert TaskStatus.ESCALATED_NEEDS_REVISION.value == "ESCALATED_NEEDS_REVISION"
    # 文字列比較で透過的に扱えること
    assert TaskStatus.COMPLETED == "COMPLETED"


def test_error_category_enum_values() -> None:
    """ErrorCategory Enum が 7 分類のエラーカテゴリを正しく保持していることを確認する。"""
    assert ErrorCategory.LINT_ERROR.value == "LINT_ERROR"
    assert ErrorCategory.TEST_ERROR.value == "TEST_ERROR"
    assert ErrorCategory.REVIEW_REJECTED.value == "REVIEW_REJECTED"
    assert ErrorCategory.LLM_TIMEOUT.value == "LLM_TIMEOUT"
    assert ErrorCategory.SYSTEM_ERROR.value == "SYSTEM_ERROR"
    assert ErrorCategory.LOCKED.value == "LOCKED"
    assert ErrorCategory.PR_ERROR.value == "PR_ERROR"


# ==============================================================================
# 2. Issue ID Validation Tests
# ==============================================================================


def test_validate_issue_id_valid() -> None:
    """妥当な Issue ID 形式 (0001〜9999, サブタスクサフィックス) を検証する。"""
    assert validate_issue_id("SBOS-0001") is True
    assert validate_issue_id("TFG-0042") is True
    assert validate_issue_id("MULTI-9999") is True
    assert validate_issue_id("SBOS-0001-A") is True


def test_validate_issue_id_invalid() -> None:
    """不正な Issue ID 形式 (0000, 連番範囲外, 小文字) が拒絶されることを確認する。"""
    assert validate_issue_id("SBOS-0000") is False
    assert validate_issue_id("sbos-0001") is False
    assert validate_issue_id("INVALID") is False
    assert validate_issue_id("TOOLONGPREFIX-0001") is False


# ==============================================================================
# 3. Project Consistency Validation Tests
# ==============================================================================


def test_validate_project_consistency_mismatch_prefix() -> None:
    """Issue ID のプレフィックスと project_key が不一致の場合に例外となることを確認する。"""
    with pytest.raises(ValueError, match="Project key mismatch"):
        validate_project_consistency("SBOS-0001", "TFG")


def test_validate_project_consistency_invalid_issue_id() -> None:
    """不正な Issue ID の場合に例外となることを確認する。"""
    with pytest.raises(ValueError, match="Invalid Issue ID format"):
        validate_project_consistency("invalid-id", "invalid")


def test_validate_project_consistency_registry_not_found(tmp_path: Path) -> None:
    """台帳ファイルが存在しない場合に例外となることを確認する。"""
    with pytest.raises(ValueError, match="Project registry file .* does not exist"):
        validate_project_consistency("SBOS-0001", "SBOS", metadata_dir=tmp_path)


# ==============================================================================
# 4. Project Lock Manager Tests
# ==============================================================================


def test_project_lock_manager_acquire_and_release(tmp_path: Path) -> None:
    """ProjectLockManager が正常に排他ロックを取得・解放できることを確認する。"""
    lock_mgr = ProjectLockManager("TEST_PROJ", metadata_dir=tmp_path)
    with lock_mgr:
        assert (tmp_path / "projects" / "TEST_PROJ" / ".lock").exists()


def test_project_lock_manager_timeout(tmp_path: Path) -> None:
    """すでにロックされているプロジェクトへの再ロックがタイムアウト例外となることを確認する。"""
    lock1 = ProjectLockManager("TEST_PROJ", metadata_dir=tmp_path)
    lock2 = ProjectLockManager("TEST_PROJ", metadata_dir=tmp_path)

    with lock1:
        with pytest.raises(TimeoutError):
            with lock2:
                pass


# ==============================================================================
# 5. Task State (state.json) & History Tests
# ==============================================================================


def test_update_task_state_creates_and_updates(tmp_path: Path) -> None:
    """update_task_state が state.json を新規作成し、アトミックに更新できることを確認する。"""
    update_task_state(
        project_key="TEST_PROJ",
        issue_id="TEST-0001",
        status=TaskStatus.RUNNING,
        review_round=1,
        max_round=3,
        metadata_dir=tmp_path,
    )

    state_file = tmp_path / "projects" / "TEST_PROJ" / "state.json"
    assert state_file.exists()

    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "TEST-0001" in data
    assert data["TEST-0001"]["status"] == "running"
    assert data["TEST-0001"]["review_round"] == 1

    # 別 Issue の追記
    update_task_state(
        project_key="TEST_PROJ",
        issue_id="TEST-0002",
        status=TaskStatus.COMPLETED,
        metadata_dir=tmp_path,
    )

    with open(state_file, "r", encoding="utf-8") as f:
        data2 = json.load(f)

    assert "TEST-0001" in data2
    assert "TEST-0002" in data2
    assert data2["TEST-0002"]["status"] == "COMPLETED"


def test_record_execution_history_and_safe_wrapper(tmp_path: Path) -> None:
    """record_execution_history および safe_record_execution_history の動作を確認する。"""
    history_file = tmp_path / "execution_history.json"
    state = {
        "issue_id": "TEST-0001",
        "project_key": "TEST_PROJ",
        "cwd": "/path/to/repo",
        "lint_round": 1,
        "test_round": 1,
        "review_round": 1,
        "lint_result": {"returncode": 0},
        "test_result": {"returncode": 0},
        "review_verdict": "LGTM",
    }

    record_execution_history(state, final_status=TaskStatus.COMPLETED, history_file=history_file)
    assert history_file.exists()

    with open(history_file, "r", encoding="utf-8") as f:
        hdata = json.load(f)

    records = hdata.get("records", [])
    assert len(records) == 1
    assert records[0]["issue_id"] == "TEST-0001"
    assert records[0]["final_status"] == "COMPLETED"
    assert records[0]["history_summary"]["lint_passed"] is True

    # safe ラッパーで例外が起きてもクラッシュしないこと
    with patch(
        "tools.metadata_store.record_execution_history", side_effect=Exception("Disk error")
    ):
        safe_record_execution_history(state, final_status="FAILED", history_file=history_file)


def test_write_event(tmp_path: Path) -> None:
    """write_event がイベント JSON ファイルを所定ディレクトリに書き出すことを確認する。"""
    event_data = {"execution_id": "exec-1234", "event": "TASK_START"}
    write_event("TEST_PROJ", event_data, metadata_dir=tmp_path)

    events_dir = tmp_path / "projects" / "TEST_PROJ" / "events"
    assert events_dir.exists()

    event_files = list(events_dir.glob("event_exec-1234_*.json"))
    assert len(event_files) == 1
    with open(event_files[0], "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["event"] == "TASK_START"


def test_resolve_project_context_nonexistent(tmp_path: Path) -> None:
    """存在しないプロジェクトキーに対して安全に無効な辞書を返すことを確認する。"""
    ctx = resolve_project_context("NONEXISTENT", metadata_dir=tmp_path)
    assert ctx["valid"] is False
    assert ctx["cwd"] is None


def test_record_execution_history_sanitizes_secrets(tmp_path: Path) -> None:
    """Issue #20: 実行履歴保存時に機密情報（APIキー、トークン、パスワード）がマスクされることを確認する。"""
    history_file = tmp_path / "execution_history.json"
    state = {
        "issue_id": "TEST-0001",
        "project_key": "TEST_PROJ",
        "cwd": "/path/to/repo",
        "error": "Failed connection: postgresql://admin:super_secret_pw@db.local:5432/main",
        "review_rounds": [
            {
                "round": 1,
                "comments": [
                    {
                        "file": "config.py",
                        "message": (
                            "Found token: "
                            + "ghp_"
                            + "123456789012345678901234567890123456"
                            + " with secret='my_token'"
                        ),
                    }
                ],
            }
        ],
    }

    record_execution_history(
        state, final_status=TaskStatus.FAILED_SYSTEM, history_file=history_file
    )

    with open(history_file, "r", encoding="utf-8") as f:
        hdata = json.load(f)

    record = hdata["records"][0]
    # エラーメッセージ内のパスワードがマスクされていること
    assert "super_secret_pw" not in record["error_message"]
    assert "[REDACTED]@" in record["error_message"]

    # レビューコメント内のGitHubトークンおよびKVシークレットがマスクされていること
    comment_msg = record["review_rounds"][0]["comments"][0]["message"]
    assert "ghp_" + "123456789012345678901234567890123456" not in comment_msg
    assert "my_token" not in comment_msg
    assert "[REDACTED]" in comment_msg


def test_write_event_sanitizes_secrets(tmp_path: Path) -> None:
    """Issue #20: 個別イベント保存時に機密情報がマスクされることを確認する。"""
    event_data = {
        "execution_id": "exec-9999",
        "event": "OLLAMA_TIMEOUT",
        "details": "Timeout with key: " + "sk-" + "1234567890abcdef1234567890abcdef",
    }
    write_event("TEST_PROJ", event_data, metadata_dir=tmp_path)

    events_dir = tmp_path / "projects" / "TEST_PROJ" / "events"
    event_files = list(events_dir.glob("event_exec-9999_*.json"))
    assert len(event_files) == 1

    with open(event_files[0], "r", encoding="utf-8") as f:
        saved = json.load(f)

    assert "sk-" + "1234567890abcdef1234567890abcdef" not in saved["details"]
    assert "[REDACTED]" in saved["details"]

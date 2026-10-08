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
    get_runtime_cache_dir,
    mark_task_completed_in_tasks_md,
    record_execution_history,
    reset_task_state,
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


def test_validate_project_consistency_self_heals_missing_project_json(tmp_path: Path) -> None:
    """サテライトの docs/project.json が欠落している場合、自動自己修復されて検証がパスすることを確認する。"""
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "TFG": {
                "name": "test_file_grep",
                "dir": "projects/test_file_grep",
                "meta": "projects/test_file_grep/docs",
                "github_repo": "xzyozi/test_file_grep",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    sat_dir = tmp_path / "projects" / "test_file_grep"
    sat_dir.mkdir(parents=True, exist_ok=True)

    # project.json が未存在の状態で呼び出す
    pjson_path = sat_dir / "docs" / "project.json"
    assert not pjson_path.exists()

    # 例外なく成功すること
    validate_project_consistency(
        "TFG-0005", "TFG", metadata_dir=meta_dir, project_root=tmp_path
    )

    # project.json が自動生成されていること
    assert pjson_path.exists()
    pdata = json.loads(pjson_path.read_text(encoding="utf-8"))
    assert pdata["key"] == "TFG"
    assert pdata["name"] == "test_file_grep"
    assert pdata["github_repo"] == "xzyozi/test_file_grep"



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


# ==============================================================================
# 6. Issue #45: Runtime Cache Isolation & Satellite Docs Priority Tests
# ==============================================================================


def test_get_runtime_cache_dir(tmp_path: Path) -> None:
    """get_runtime_cache_dir が指定 project_root 配下の tools/.cache/projects/<KEY> を生成して返すことを確認する。"""
    cache_dir = get_runtime_cache_dir("TEST_PROJ", project_root=tmp_path)
    assert cache_dir == tmp_path / "tools" / ".cache" / "projects" / "TEST_PROJ"
    assert cache_dir.exists()


def test_project_lock_manager_runtime_cache_isolation(tmp_path: Path) -> None:
    """Issue #45: デフォルト (metadata_dir=None) 時に tools/.cache 配下に .lock が生成され、排他制御できることを確認する。"""
    custom_lock_file = tmp_path / "tools" / ".cache" / "projects" / "TEST_PROJ" / ".lock"
    lock_mgr = ProjectLockManager("TEST_PROJ", lock_file=custom_lock_file)
    with lock_mgr:
        assert custom_lock_file.exists()


def test_update_task_state_runtime_cache_isolation(tmp_path: Path) -> None:
    """Issue #45: state_file を明示またはデフォルト隔離時に指定ファイルに状態が保存されることを確認する。"""
    custom_state_file = tmp_path / "tools" / ".cache" / "projects" / "TEST_PROJ" / "state.json"
    update_task_state(
        project_key="TEST_PROJ",
        issue_id="TEST-0001",
        status=TaskStatus.RUNNING,
        state_file=custom_state_file,
    )
    assert custom_state_file.exists()
    with open(custom_state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["TEST-0001"]["status"] == "running"


def test_write_event_runtime_cache_isolation(tmp_path: Path) -> None:
    """Issue #45: events_dir を明示またはデフォルト隔離時に指定ディレクトリにイベントが保存されることを確認する。"""
    custom_events_dir = tmp_path / "tools" / ".cache" / "projects" / "TEST_PROJ" / "events"
    write_event(
        project_key="TEST_PROJ",
        event_data={"execution_id": "test-iso-001", "event": "ISOLATION_TEST"},
        events_dir=custom_events_dir,
    )
    assert custom_events_dir.exists()
    files = list(custom_events_dir.glob("event_test-iso-001_*.json"))
    assert len(files) == 1


def test_validate_project_consistency_satellite_docs(tmp_path: Path) -> None:
    """Issue #45: サテライト側の docs/project.json に定義されたプロジェクトの整合性が検証できることを確認する。"""
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir(parents=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "SAT": {
                "name": "satellite_repo",
                "dir": "projects/satellite_repo",
                "meta": "metadata/projects/SAT",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    # サテライト側の docs/project.json を作成（母艦側の meta には project.json なし）
    sat_docs = tmp_path / "projects" / "satellite_repo" / "docs"
    sat_docs.mkdir(parents=True)
    sat_proj_json = sat_docs / "project.json"
    sat_proj_json.write_text(json.dumps({"key": "SAT", "name": "satellite_repo"}), encoding="utf-8")

    # 例外がスローされずに通過すること
    validate_project_consistency(
        "SAT-0001",
        "SAT",
        metadata_dir=meta_dir,
        project_root=tmp_path,
    )


def test_resolve_project_context_prioritizes_satellite_docs(tmp_path: Path) -> None:
    """Issue #45: resolve_project_context がサテライト側の docs/project.json と docs/tasks.md を母艦より優先して読み込むことを確認する。"""
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir(parents=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "SAT": {
                "name": "satellite_repo",
                "dir": "projects/satellite_repo",
                "meta": "metadata/projects/SAT",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    # サテライトディレクトリ（Git リポジトリ）の模擬作成
    sat_dir = tmp_path / "projects" / "satellite_repo"
    sat_dir.mkdir(parents=True)
    (sat_dir / ".git").mkdir()
    (sat_dir / "satellite_code.py").write_text("print('hello')", encoding="utf-8")

    # 母艦側の meta/project.json (旧設定: base_branch = master)
    host_meta = tmp_path / "metadata" / "projects" / "SAT"
    host_meta.mkdir(parents=True)
    (host_meta / "project.json").write_text(
        json.dumps({"key": "SAT", "base_branch": "master", "target_files": ["host_file.py"]}),
        encoding="utf-8",
    )

    # サテライト側の docs/project.json (新設定: base_branch = develop, target_files = ['satellite_code.py'])
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True)
    (sat_docs / "project.json").write_text(
        json.dumps({"key": "SAT", "base_branch": "develop", "target_files": ["satellite_code.py"]}),
        encoding="utf-8",
    )

    ctx = resolve_project_context(
        "SAT",
        metadata_dir=meta_dir,
        project_root=tmp_path,
    )

    assert ctx["valid"] is True
    assert ctx["base_branch"] == "develop"
    assert ctx["target_files"] == ["satellite_code.py"]


def test_reset_task_state(tmp_path: Path) -> None:
    """Issue #80: reset_task_state が指定した issue_id を安全に削除し、他タスクを保持することを検証する。"""
    state_file = tmp_path / "state.json"

    # 1. 2つのタスクを追加
    update_task_state("PROJ", "TASK-0001", TaskStatus.FAILED_SYSTEM, state_file=state_file)
    update_task_state("PROJ", "TASK-0002", TaskStatus.COMPLETED, state_file=state_file)

    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "TASK-0001" in data
    assert "TASK-0002" in data

    # 2. TASK-0001 をリセット
    res = reset_task_state("PROJ", "TASK-0001", state_file=state_file)
    assert res is True

    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "TASK-0001" not in data
    assert "TASK-0002" in data

    # 3. 再度 TASK-0001 をリセットしようとすると False
    res_again = reset_task_state("PROJ", "TASK-0001", state_file=state_file)
    assert res_again is False

    # 4. 存在しない state_file に対する呼び出しでも例外にならず False
    non_existent = tmp_path / "non_existent.json"
    assert reset_task_state("PROJ", "TASK-9999", state_file=non_existent) is False


def test_mark_task_completed_in_tasks_md(tmp_path: Path) -> None:
    """Issue #80: mark_task_completed_in_tasks_md が該当タスクを安全に完了チェックに更新することを検証する。"""
    sat_docs = tmp_path / "docs"
    sat_docs.mkdir(parents=True)
    tasks_file = sat_docs / "tasks.md"

    initial_content = (
        "# Tasks\n\n"
        "- [x] [CW-0001] タスク1 <!-- priority:medium issue:#7 completed:2026-10-01 -->\n"
        "- [ ] [CW-0038] 除外アプリ判定 <!-- priority:medium issue:#109 stage:ready -->\n"
        "- [ ] [CW-0039] 別のタスク <!-- priority:medium issue:#110 stage:ideation -->\n"
    )
    tasks_file.write_text(initial_content, encoding="utf-8")

    # CW-0038 を完了に更新
    updated = mark_task_completed_in_tasks_md(str(tmp_path), "CW-0038")
    assert updated is True

    new_content = tasks_file.read_text(encoding="utf-8")
    lines = new_content.splitlines()

    # CW-0001 は変更なし
    assert (
        lines[2] == "- [x] [CW-0001] タスク1 <!-- priority:medium issue:#7 completed:2026-10-01 -->"
    )
    # CW-0038 は - [x] になり completed: が付与
    assert lines[3].startswith("- [x] [CW-0038] 除外アプリ判定")
    assert "completed:" in lines[3]
    # CW-0039 は未完了のまま
    assert (
        lines[4] == "- [ ] [CW-0039] 別のタスク <!-- priority:medium issue:#110 stage:ideation -->"
    )


def test_parse_github_issue_url() -> None:
    """GitHub Issue URL のパース処理を検証する。"""
    from tools.metadata_store import parse_github_issue_url

    res = parse_github_issue_url("https://github.com/xzyozi/test_file_grep/issues/5")
    assert res == ("xzyozi/test_file_grep", 5)

    res_param = parse_github_issue_url("https://github.com/org/repo/issues/123#issuecomment-456")
    assert res_param == ("org/repo", 123)

    assert parse_github_issue_url("invalid-url") is None
    assert parse_github_issue_url("https://github.com/org/repo/pull/123") is None


def test_resolve_target_spec_url_and_task_id(tmp_path: Path) -> None:
    """URL および task_id から project_key, task_id, issue_number が正しく解決されることを検証する。"""
    project_root = tmp_path
    metadata_dir = project_root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    reg_file = metadata_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "TFG": {
                "name": "test_file_grep",
                "github_repo": "xzyozi/test_file_grep",
                "dir": "projects/test_file_grep",
                "meta": "metadata/projects/TFG",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    sat_dir = project_root / "projects" / "test_file_grep"
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)

    # tasks.md に TFG-0005 (issue:#5) を配置
    tasks_content = "# Tasks\n- [ ] [TFG-0005] パス検証関数を追加 (issue:#5)\n"
    (sat_docs / "tasks.md").write_text(tasks_content, encoding="utf-8")

    from tools.metadata_store import resolve_target_spec

    # 1. URL からの解決
    res_url = resolve_target_spec(
        "https://github.com/xzyozi/test_file_grep/issues/5",
        project_root=project_root,
    )
    assert res_url["type"] == "url"
    assert res_url["project_key"] == "TFG"
    assert res_url["task_id"] == "TFG-0005"
    assert res_url["issue_number"] == 5

    # 2. task_id からの解決
    res_task = resolve_target_spec("TFG-0005", project_root=project_root)
    assert res_task["type"] == "task_id"
    assert res_task["project_key"] == "TFG"
    assert res_task["task_id"] == "TFG-0005"
    assert res_task["issue_number"] == 5

    # 3. CWD サテライト配下での数値指定 (5) からの解決
    res_num = resolve_target_spec(
        "5",
        cwd=sat_dir,
        project_root=project_root,
    )
    assert res_num["type"] == "issue_number"
    assert res_num["project_key"] == "TFG"
    assert res_num["task_id"] == "TFG-0005"
    assert res_num["issue_number"] == 5


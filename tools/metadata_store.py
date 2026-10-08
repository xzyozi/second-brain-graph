"""metadata_store.py - Second Brain OS メタデータ・状態管理モジュール

Issue #22 (DD-003 §10.4) リファクタリング。
orchestrator_graph.py からプロジェクト台帳・状態(state.json)・履歴(history.jsonl)・排他ロック管理を
独立モジュールとして分離し、単一責任とテスト容易性を向上させる。
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from filelock import FileLock, Timeout

from tools.sanitizer import sanitize_data

logger = logging.getLogger("metadata_store")

ISSUE_ID_PATTERN = re.compile(r"^[A-Z]{2,5}-(?!0000)\d{4}(-[A-Z])?$")


# ==============================================================================
# 1. Status & Error Category Types (Enum & Literal)
# ==============================================================================


class TaskStatus(str, Enum):
    """タスクのライフサイクル状態 (DD-003 §4.1.1)."""

    # 中間・遷移状態
    RUNNING = "running"
    CODE_COMPLETED = "code_completed"
    LINT_PASSED = "lint_passed"
    TEST_PASSED = "test_passed"
    REVIEW_LGTM = "review_lgtm"
    RETRY_SPEC_DRAFT = "retry_spec_draft"
    RETRY_CODE = "retry_code"
    RETRY_REVIEW = "retry_review"

    # 終端状態
    COMPLETED = "COMPLETED"
    FAILED_SYSTEM = "FAILED_SYSTEM"
    FAILED_B7 = "FAILED_B7"
    PR_FAILED = "PR_FAILED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"
    ESCALATED_NEEDS_REVISION = "ESCALATED_NEEDS_REVISION"


class ErrorCategory(str, Enum):
    """DD-003 §2.1 のエラー分類（7分類）."""

    LINT_ERROR = "LINT_ERROR"
    TEST_ERROR = "TEST_ERROR"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    LOCKED = "LOCKED"
    PR_ERROR = "PR_ERROR"


# 後方互換性および TypedDict アノテーション用の Literal エイリアス
StatusLiteral = Literal[
    "running",
    "code_completed",
    "lint_passed",
    "test_passed",
    "review_lgtm",
    "retry_spec_draft",
    "retry_code",
    "retry_review",
    "COMPLETED",
    "FAILED_SYSTEM",
    "FAILED_B7",
    "PR_FAILED",
    "SKIPPED_LOCKED",
    "ESCALATED_NEEDS_REVISION",
]

ErrorCategoryLiteral = Literal[
    "LINT_ERROR",
    "TEST_ERROR",
    "REVIEW_REJECTED",
    "LLM_TIMEOUT",
    "SYSTEM_ERROR",
    "LOCKED",
    "PR_ERROR",
]


# ==============================================================================
# 2. Issue ID & Project Consistency Validation
# ==============================================================================


def validate_issue_id(issue_id: str) -> bool:
    """Issue ID の形式および連番範囲 (0001〜9999) を検証する (MULTI-001 §2②・§4)."""
    return bool(ISSUE_ID_PATTERN.match(issue_id))


def get_runtime_cache_dir(
    project_key: str,
    project_root: Optional[Path] = None,
) -> Path:
    """ランタイム動的データ（.lock, state.json, events/ 等）を格納するキャッシュディレクトリパスを返す。
    母艦の Git 管理から完全に除外された tools/.cache/projects/<PROJECT_KEY>/ 配下に配置される。
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    cache_dir = project_root / "tools" / ".cache" / "projects" / project_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def self_heal_satellite_project_json(
    project_key: str,
    proj_entry: dict[str, Any],
    project_root: Path,
) -> Optional[Path]:
    """サテライトの docs/project.json が未存在の場合、.project-registry.json 情報から自己修復生成する。"""
    dir_rel = proj_entry.get("dir")
    if not dir_rel:
        return None
    sat_dir = project_root / dir_rel
    if not sat_dir.exists():
        return None

    docs_dir = sat_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    proj_json_path = docs_dir / "project.json"

    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proj_data = {
        "key": project_key,
        "name": proj_entry.get("name", project_key),
        "base_branch": proj_entry.get("base_branch", "develop"),
        "created_at": now_date,
        "description": proj_entry.get("description", f"{proj_entry.get('name', project_key)} satellite project"),
    }
    if "github_repo" in proj_entry:
        proj_data["github_repo"] = proj_entry["github_repo"]

    try:
        proj_json_path.write_text(
            json.dumps(proj_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info(f"Self-healed: created missing project.json at '{proj_json_path}'.")
        return proj_json_path
    except Exception as e:
        logger.warning(f"Failed to self-heal project.json at '{proj_json_path}': {e}")
        return None


def validate_project_consistency(
    issue_id: str,
    project_key: str,
    metadata_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> None:
    """Issue ID 形式、プレフィックス、CLI project_key、台帳キー、
    ディレクトリ、project.json、project.json["key"] の必須存在と一致性を検証する (MULTI-001 §2②・§4)。
    サテライト（<dir>/docs/project.json）または母艦（<meta>/project.json）の存在を許容・検証する。
    欠落している場合は自己修復を試行する (Zero-Failure 実行)。
    """
    if not validate_issue_id(issue_id):
        raise ValueError(
            f"Invalid Issue ID format: '{issue_id}'. Expected pattern: 'PROJECT-0001' (range 0001-9999)."
        )

    prefix = issue_id.split("-")[0]
    if prefix != project_key:
        raise ValueError(
            f"Project key mismatch: Issue ID prefix '{prefix}' does not match project_key '{project_key}'."
        )

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    if metadata_dir is None:
        metadata_dir = project_root / "metadata"

    reg_file = metadata_dir / ".project-registry.json"
    if not reg_file.exists():
        raise ValueError(f"Project registry file '{reg_file}' does not exist.")

    with open(reg_file, "r", encoding="utf-8") as f:
        reg = json.load(f)

    projects_dict = reg.get("projects", {})
    if project_key not in projects_dict:
        raise ValueError(
            f"Project key '{project_key}' is not registered in .project-registry.json."
        )

    proj_entry = projects_dict[project_key]
    dir_rel = proj_entry.get("dir")
    meta_rel = proj_entry.get("meta")

    # project.json の探索: 1. サテライト (projects/<name>/docs/project.json) -> 2. 母艦 (metadata/projects/<KEY>/project.json)
    candidate_proj_json: Optional[Path] = None
    if dir_rel:
        satellite_proj_json = project_root / dir_rel / "docs" / "project.json"
        if satellite_proj_json.exists():
            candidate_proj_json = satellite_proj_json

    if candidate_proj_json is None and meta_rel:
        meta_dir_path = project_root / meta_rel
        if meta_dir_path.exists():
            fallback_proj_json = meta_dir_path / "project.json"
            if fallback_proj_json.exists():
                candidate_proj_json = fallback_proj_json

    # 探索失敗時: サテライトディレクトリが存在すれば自己修復を試行 (Zero-Failure)
    if candidate_proj_json is None:
        healed_path = self_heal_satellite_project_json(project_key, proj_entry, project_root)
        if healed_path and healed_path.exists():
            candidate_proj_json = healed_path

    if candidate_proj_json is None:
        if not meta_rel and not dir_rel:
            raise ValueError(
                f"Missing 'meta' and 'dir' field for project '{project_key}' in .project-registry.json."
            )
        expected_path = (
            (project_root / dir_rel / "docs" / "project.json")
            if dir_rel
            else (project_root / meta_rel / "project.json")
        )
        raise ValueError(
            f"project.json does not exist at '{expected_path}'. "
            f"Please check if satellite branch is initialized or run 'uv run python tools/add_project.py --key {project_key} ...'."
        )

    with open(candidate_proj_json, "r", encoding="utf-8") as pf:
        pdata = json.load(pf)
        pkey = pdata.get("key")
        if not pkey:
            raise ValueError(f"Missing 'key' field in project.json at '{candidate_proj_json}'.")
        if pkey != project_key:
            raise ValueError(
                f"Project key mismatch in project.json: expected '{project_key}', got '{pkey}'."
            )


def _is_default_metadata_dir(metadata_dir: Optional[Path]) -> bool:
    """渡された metadata_dir が未指定、または母艦標準の metadata ディレクトリであるかを判定する。"""
    if metadata_dir is None:
        return True
    default_meta = Path(__file__).resolve().parent.parent / "metadata"
    try:
        return metadata_dir.resolve() == default_meta.resolve()
    except Exception:
        return False


# ==============================================================================
# 3. Project Exclusive Lock Management
# ==============================================================================


class ProjectLockManager:
    """衛星プロジェクトの排他制御（ロック機構）を管理するクラス (PM-037)."""

    def __init__(
        self,
        project_key: str,
        metadata_dir: Optional[Path] = None,
        lock_file: Optional[Path] = None,
    ) -> None:
        self.project_key = project_key
        if lock_file is not None:
            self.lock_file = lock_file
            self.lock_dir = lock_file.parent
        elif not _is_default_metadata_dir(metadata_dir) and metadata_dir is not None:
            # テスト環境等で一時ディレクトリが明示指定された場合
            self.lock_dir = metadata_dir / "projects" / project_key
            self.lock_file = self.lock_dir / ".lock"
        else:
            # 本番・標準環境: tools/.cache/projects/<KEY>/.lock に完全隔離
            self.lock_dir = get_runtime_cache_dir(project_key)
            self.lock_file = self.lock_dir / ".lock"
        self.lock = FileLock(str(self.lock_file), timeout=0)

    def __enter__(self) -> "ProjectLockManager":
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._release_lock()

    def _acquire_lock(self) -> None:
        try:
            logger.info(f"Waiting for lock on project {self.project_key}...")
            self.lock.acquire()
            logger.info(f"Lock acquired for project {self.project_key}")
        except Timeout as e:
            logger.error(f"Failed to acquire project lock for {self.project_key} within timeout.")
            raise TimeoutError(
                f"Failed to acquire project lock for {self.project_key} within timeout."
            ) from e

    def _release_lock(self) -> None:
        try:
            self.lock.release()
            logger.info(f"Lock released for project {self.project_key}")
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")


def force_unlock_project(
    project_key: str,
    metadata_dir: Optional[Path] = None,
    lock_file: Optional[Path] = None,
) -> bool:
    """残留したプロジェクトロック (.lock) を安全に強制解除する (Issue #80)。"""
    if lock_file is not None:
        target_lock_file = lock_file
    elif not _is_default_metadata_dir(metadata_dir) and metadata_dir is not None:
        target_lock_file = metadata_dir / "projects" / project_key / ".lock"
    else:
        target_lock_file = get_runtime_cache_dir(project_key) / ".lock"

    if target_lock_file.exists():
        try:
            target_lock_file.unlink(missing_ok=True)
            logger.info(f"Forcefully removed lock file: {target_lock_file}")
            return True
        except Exception as e:
            logger.warning(f"Failed to remove lock file {target_lock_file}: {e}")
    return False


# ==============================================================================
# 4. Task State (state.json) & History (execution_history.json) Operations
# ==============================================================================


def update_task_state(
    project_key: str,
    issue_id: str,
    status: str,
    review_round: int = 0,
    max_round: int = 3,
    error_category: Optional[str] = None,
    metadata_dir: Optional[Path] = None,
    state_file: Optional[Path] = None,
) -> None:
    """state.json 内の該当 issue_id の状態項目をアトミックにマージ更新する (DD-003 §4.1.1)。
    state_file または非デフォルトの metadata_dir が明示された場合はそちらを優先（後方互換・テスト支援）。
    未指定または標準母艦 metadata_dir の場合は tools/.cache/projects/<PROJECT_KEY>/state.json へ隔離保存する。
    """
    if state_file is not None:
        target_state_file = state_file
    elif not _is_default_metadata_dir(metadata_dir) and metadata_dir is not None:
        target_state_file = metadata_dir / "projects" / project_key / "state.json"
    else:
        target_state_file = get_runtime_cache_dir(project_key) / "state.json"
    target_state_file.parent.mkdir(parents=True, exist_ok=True)

    state_data: Dict[str, Any] = {}
    if target_state_file.exists():
        try:
            with open(target_state_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                if "issue_id" in raw_data and not any(
                    isinstance(v, dict) for v in raw_data.values()
                ):
                    old_id = raw_data.get("issue_id", issue_id)
                    state_data[old_id] = {
                        "status": raw_data.get("status", "PENDING"),
                        "review_round": raw_data.get("review_round", 0),
                        "max_round": raw_data.get("max_round", 3),
                        "error_category": raw_data.get("error_category"),
                        "updated_at": raw_data.get(
                            "updated_at", datetime.now(timezone.utc).isoformat()
                        ),
                    }
                else:
                    state_data = raw_data
        except Exception as e:
            logger.warning(f"Failed to read existing state.json for {project_key}: {e}")
    elif metadata_dir is None and state_file is None:
        # 新パスに state.json がまだ存在しない場合、旧パス (metadata/projects/<KEY>/state.json) があればフォールバック読み込み
        legacy_state_file = (
            Path(__file__).resolve().parent.parent
            / "metadata"
            / "projects"
            / project_key
            / "state.json"
        )
        if legacy_state_file.exists():
            try:
                with open(legacy_state_file, "r", encoding="utf-8") as lf:
                    state_data = json.load(lf)
            except Exception as e:
                logger.warning(f"Failed to read legacy state.json for {project_key}: {e}")

    status_str = status.value if isinstance(status, Enum) else str(status)
    err_cat_str = (
        error_category.value
        if isinstance(error_category, Enum)
        else (str(error_category) if error_category else None)
    )

    state_data[issue_id] = {
        "status": status_str,
        "review_round": review_round,
        "max_round": max_round,
        "error_category": err_cat_str,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    temp_file = target_state_file.with_name(f"state.json.{uuid.uuid4().hex}.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp_file, target_state_file)


def reset_task_state(
    project_key: str,
    issue_id: str,
    metadata_dir: Optional[Path] = None,
    state_file: Optional[Path] = None,
) -> bool:
    """state.json 内の該当 issue_id の状態項目を安全に削除・初期化する (Issue #80)。
    他タスクの状態は安全に保持する。
    削除に成功した場合は True、該当エントリが存在しなかった場合は False を返す。
    """
    if state_file is not None:
        target_state_file = state_file
    elif not _is_default_metadata_dir(metadata_dir) and metadata_dir is not None:
        target_state_file = metadata_dir / "projects" / project_key / "state.json"
    else:
        target_state_file = get_runtime_cache_dir(project_key) / "state.json"

    removed = False
    if target_state_file.exists():
        try:
            with open(target_state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            if issue_id in state_data:
                del state_data[issue_id]
                removed = True

                temp_file = target_state_file.with_name(f"state.json.{uuid.uuid4().hex}.tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_file, target_state_file)
                logger.info(
                    f"Successfully reset task state for '{issue_id}' in {target_state_file}"
                )
        except Exception as e:
            logger.warning(f"Failed to reset task state for {project_key}/{issue_id}: {e}")

    # 旧パス (metadata/projects/<KEY>/state.json) も存在する場合は削除
    if metadata_dir is None and state_file is None:
        legacy_state_file = (
            Path(__file__).resolve().parent.parent
            / "metadata"
            / "projects"
            / project_key
            / "state.json"
        )
        if legacy_state_file.exists():
            try:
                with open(legacy_state_file, "r", encoding="utf-8") as lf:
                    legacy_data = json.load(lf)
                if issue_id in legacy_data:
                    del legacy_data[issue_id]
                    removed = True
                    temp_legacy = legacy_state_file.with_name(f"state.json.{uuid.uuid4().hex}.tmp")
                    with open(temp_legacy, "w", encoding="utf-8") as lf:
                        json.dump(legacy_data, lf, indent=2, ensure_ascii=False)
                        lf.flush()
                        os.fsync(lf.fileno())
                    os.replace(temp_legacy, legacy_state_file)
            except Exception as e:
                logger.warning(
                    f"Failed to reset legacy state.json for {project_key}/{issue_id}: {e}"
                )

    return removed


def mark_task_completed_in_tasks_md(
    cwd: Optional[str],
    issue_id: str,
    project_key: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> bool:
    """サテライト (docs/tasks.md) および母艦 (metadata/projects/<KEY>/tasks.md) の
    該当タスク行を完了状態 (- [x] ... completed:YYYY-MM-DD) に更新する (Issue #80)。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = False

    target_paths: List[Path] = []
    if cwd:
        sat_tasks = Path(cwd) / "docs" / "tasks.md"
        if sat_tasks.exists():
            target_paths.append(sat_tasks)

    if project_key and project_root:
        meta_tasks = project_root / "metadata" / "projects" / project_key / "tasks.md"
        if meta_tasks.exists():
            target_paths.append(meta_tasks)

    for tpath in target_paths:
        try:
            content = tpath.read_text(encoding="utf-8")
            new_lines: List[str] = []
            modified = False
            for line in content.splitlines():
                # 該当 Issue ID の未完了行 (- [ ] [ID] または - [/] [ID])
                if f"[{issue_id}]" in line and (
                    line.strip().startswith("- [ ]") or line.strip().startswith("- [/]")
                ):
                    # - [ ] または - [/] を - [x] に置換
                    new_line = re.sub(r"^(\s*-\s*)\[[ /]?\]", r"\1[x]", line)
                    if "completed:" not in new_line:
                        if "-->" in new_line:
                            new_line = re.sub(r"(-->|\Z)", f"completed:{today} \\1", new_line)
                        else:
                            new_line = f"{new_line} <!-- completed:{today} -->"
                    new_lines.append(new_line)
                    modified = True
                    updated = True
                else:
                    new_lines.append(line)

            if modified:
                tpath.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logger.info(f"Marked task '{issue_id}' as completed in {tpath}")
        except Exception as e:
            logger.warning(f"Failed to update tasks.md at {tpath} for {issue_id}: {e}")

    return updated


def record_execution_history(
    state: Dict[str, Any],
    final_status: str,
    review_round: int = 0,
    history_file: Optional[Path] = None,
) -> None:
    """tools/.cache/execution_history.json へ実行完了・エスカレーション結果を
    DD-003 §4.1.1 監査スキーマ (actual_round = max(...), review_rounds, history_summary.review_verdict,
    lint_passed/test_passed の returncode 正本化) に従って専用の FileLock 保護のもとアトミックに追記保存する。
    """
    if history_file is None:
        history_file = (
            Path(__file__).resolve().parent.parent / "tools" / ".cache" / "execution_history.json"
        )
    history_file.parent.mkdir(parents=True, exist_ok=True)

    lock_file = history_file.with_name(".execution_history.lock")
    with FileLock(str(lock_file), timeout=10):
        history_data: Dict[str, Any] = {"records": []}
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read execution_history.json: {e}")

        lint_round = state.get("lint_round", 0)
        test_round = state.get("test_round", 0)
        rev_round = state.get("review_round", review_round)
        actual_round = max(lint_round, test_round, rev_round)
        rev_verdict = state.get("review_verdict", "PENDING")

        lint_res = state.get("lint_result")
        test_res = state.get("test_result")
        lint_passed = (
            lint_res.get("returncode") == 0
            if isinstance(lint_res, dict) and "returncode" in lint_res
            else None
        )
        test_passed = (
            test_res.get("returncode") == 0
            if isinstance(test_res, dict) and "returncode" in test_res
            else None
        )

        final_status_str = (
            final_status.value if isinstance(final_status, Enum) else str(final_status)
        )
        err_cat = state.get("error_category")
        err_cat_str = (
            err_cat.value if isinstance(err_cat, Enum) else (str(err_cat) if err_cat else None)
        )

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issue_id": state.get("issue_id", "unknown"),
            "project_key": state.get("project_key", "unknown"),
            "project_path": state.get("cwd", "unknown"),
            "final_status": final_status_str,
            "actual_round": actual_round,
            "review_round": rev_round,
            "max_round": state.get("max_round", 3),
            "lint_round": lint_round,
            "test_round": test_round,
            "error_category": err_cat_str,
            "error_message": state.get("error"),
            "llm_timeout_count": state.get("llm_timeout_count", 0),
            "review_rounds": state.get("review_rounds", []),
            "reviewdog_result": state.get("reviewdog_result"),
            "history_summary": {
                "lint_passed": lint_passed,
                "test_passed": test_passed,
                "review_verdict": rev_verdict,
            },
        }

        # #20 (DD-003 §10.3): 永続化前の機密情報サニタイズ
        clean_record = sanitize_data(record)
        records = history_data.get("records", [])
        records.append(clean_record)
        history_data["records"] = records

        temp_file = history_file.with_name(f"execution_history.json.{uuid.uuid4().hex}.tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_file, history_file)


def safe_record_execution_history(
    state: Dict[str, Any],
    final_status: str,
    review_round: int = 0,
    history_file: Optional[Path] = None,
) -> None:
    """履歴保存時の例外を捕捉し、確定済み state.json を汚染させない統一保護ヘルパー。"""
    try:
        record_execution_history(
            state, final_status=final_status, review_round=review_round, history_file=history_file
        )
    except Exception as e:
        logger.warning(
            f"Failed to record execution history safely (keeping state '{final_status}'): {e}"
        )


def write_event(
    project_key: str,
    event_data: Dict[str, Any],
    metadata_dir: Optional[Path] = None,
    events_dir: Optional[Path] = None,
) -> None:
    """Graph の状態に影響を与えない個別ファイルイベント記録 (PM-050)。
    events_dir または metadata_dir が明示された場合はそちらを使用（後方互換）。
    未指定の場合は tools/.cache/projects/<PROJECT_KEY>/events/ へ隔離保存する。
    """
    if events_dir is not None:
        target_events_dir = events_dir
    elif not _is_default_metadata_dir(metadata_dir) and metadata_dir is not None:
        target_events_dir = metadata_dir / "projects" / project_key / "events"
    else:
        target_events_dir = get_runtime_cache_dir(project_key) / "events"

    target_events_dir.mkdir(parents=True, exist_ok=True)

    execution_id = event_data.get("execution_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    # #20 (DD-003 §10.3): 永続化前の機密情報サニタイズ
    clean_event_data = sanitize_data(event_data)
    event_file = target_events_dir / f"event_{execution_id}_{timestamp}.json"

    with open(event_file, "w", encoding="utf-8") as f:
        json.dump(clean_event_data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


# ==============================================================================
# 5. Project Context Resolution
# ==============================================================================


def resolve_project_context(
    project_key: str,
    metadata_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """.project-registry.json からプロジェクトの dir, meta を解決し、
    サテライト本体 (docs/) を最優先として設定・タスクを読み込み、
    特定のファイル名にハードコードせず、任意の衛星リポジトリの対象ファイルを動的に検出・解決する (MULTI-001 §2③・§4)。
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    if metadata_dir is None:
        metadata_dir = project_root / "metadata"

    registry_file = metadata_dir / ".project-registry.json"
    if not registry_file.exists():
        logger.warning(f"Project registry file {registry_file} does not exist.")
        return {"cwd": None, "target_files": [], "base_branch": "develop", "valid": False}

    try:
        with open(registry_file, "r", encoding="utf-8") as f:
            registry = json.load(f)

        proj_info = registry.get("projects", {}).get(project_key)
        if not proj_info:
            return {"cwd": None, "target_files": [], "base_branch": "develop", "valid": False}

        rel_dir = proj_info.get("dir")
        meta_dir = proj_info.get("meta")

        if not rel_dir:
            return {"cwd": None, "target_files": [], "base_branch": "develop", "valid": False}

        cwd_path = project_root / rel_dir
        cwd = str(cwd_path)

        # フェイルセーフ: 実在するディレクトリかつ Git リポジトリであることを検証
        if not (cwd_path.exists() and cwd_path.is_dir() and (cwd_path / ".git").exists()):
            logger.error(f"Resolved cwd {cwd} is not a valid git repository space.")
            return {"cwd": cwd, "target_files": [], "base_branch": "develop", "valid": False}

        base_branch = "develop"
        work_branch_prefix = "sbos/"
        raw_target_files: List[str] = []
        exclude_files: List[str] = []

        # 優先順位1: サテライト側の docs/project.json
        # 優先順位2: 母艦側の meta_dir/project.json
        project_json_candidates = [cwd_path / "docs" / "project.json"]
        if meta_dir:
            project_json_candidates.append(project_root / meta_dir / "project.json")

        for pjson_path in project_json_candidates:
            if pjson_path.exists():
                try:
                    with open(pjson_path, "r", encoding="utf-8") as pf:
                        pdata = json.load(pf)
                        base_branch = pdata.get("base_branch", "develop")
                        work_branch_prefix = pdata.get("work_branch_prefix", "sbos/")
                        if (
                            "target_files" in pdata
                            and isinstance(pdata["target_files"], list)
                            and pdata["target_files"]
                        ):
                            raw_target_files.extend(pdata["target_files"])
                        if "exclude_files" in pdata and isinstance(pdata["exclude_files"], list):
                            exclude_files.extend(pdata["exclude_files"])
                        break
                except Exception as ex:
                    logger.warning(f"Failed to read project.json at {pjson_path}: {ex}")

        # tasks.md からの target_files 探索（未設定時）: サテライト docs/tasks.md 優先、フォールバックで母艦 meta_dir/tasks.md
        if not raw_target_files:
            tasks_candidates = [cwd_path / "docs" / "tasks.md"]
            if meta_dir:
                tasks_candidates.append(project_root / meta_dir / "tasks.md")
            for tpath in tasks_candidates:
                if tpath.exists():
                    try:
                        text = tpath.read_text(encoding="utf-8")
                        matches = re.findall(r"[\w/.-]+\.py", text)
                        for m in matches:
                            if m not in raw_target_files:
                                raw_target_files.append(m)
                        if raw_target_files:
                            break
                    except Exception as ex:
                        logger.warning(f"Failed to parse tasks.md at {tpath}: {ex}")

        # 上記メタデータから未検出の場合、衛星ディレクトリ内の実在する Python ファイルを自動検出
        if not raw_target_files:
            for py_file in cwd_path.rglob("*.py"):
                rel_p = str(py_file.relative_to(cwd_path)).replace("\\", "/")
                if not any(
                    excluded in rel_p
                    for excluded in [".venv", "venv", "__pycache__", "build", "dist"]
                ):
                    raw_target_files.append(rel_p)

        # ターゲットファイルの有効性を検証し、除外ファイルを適用
        valid_target_files = []
        for tf in raw_target_files:
            if tf in exclude_files:
                continue
            abs_tf = cwd_path / tf
            if abs_tf.exists() or (not tf.startswith("..") and not os.path.isabs(tf)):
                valid_target_files.append(tf)

        if not valid_target_files:
            logger.error(
                f"No valid target files found in satellite repo for project {project_key}."
            )
            return {
                "cwd": cwd,
                "target_files": [],
                "base_branch": base_branch,
                "work_branch_prefix": work_branch_prefix,
                "valid": False,
            }

        return {
            "cwd": cwd,
            "target_files": valid_target_files,
            "base_branch": base_branch,
            "work_branch_prefix": work_branch_prefix,
            "valid": True,
        }
    except Exception as e:
        logger.error(f"Failed to resolve project context for {project_key}: {e}")
        return {
            "cwd": None,
            "target_files": [],
            "base_branch": "develop",
            "work_branch_prefix": "sbos/",
            "valid": False,
        }


# ==============================================================================
# 10. URL Driven & CWD Target Resolution Helpers (Issue #83)
# ==============================================================================


def load_project_registry(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """metadata/.project-registry.json を読み込み、projects 辞書を返す。"""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    reg_file = project_root / "metadata" / ".project-registry.json"
    if not reg_file.exists():
        return {}
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("projects", {})
    except Exception as e:
        logger.error(f"Failed to load project registry from {reg_file}: {e}")
        return {}


def parse_github_issue_url(url: str) -> Optional[Tuple[str, int]]:
    """GitHub Issue URL をパースし、(owner_repo, issue_number) を返す。
    例: https://github.com/xzyozi/test_file_grep/issues/5 -> ('xzyozi/test_file_grep', 5)
    """
    if not isinstance(url, str):
        return None
    match = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:[/?#].*)?$", url.strip()
    )
    if match:
        owner = match.group(1)
        repo = match.group(2)
        issue_num = int(match.group(3))
        return f"{owner}/{repo}", issue_num
    return None


def resolve_project_key_from_repo_or_name(
    repo_or_name: str, project_root: Optional[Path] = None
) -> Optional[str]:
    """owner/repo, repo 名、またはプロジェクト名から登録済みの project_key を逆引きする。"""
    if not repo_or_name:
        return None
    projects = load_project_registry(project_root)
    # 1. key 直接一致
    if repo_or_name in projects:
        return repo_or_name

    clean = repo_or_name.strip()
    repo_basename = clean.split("/")[-1] if "/" in clean else clean

    # 2. github_repo または name 一致
    for key, pdata in projects.items():
        if pdata.get("github_repo") == clean:
            return key
        if pdata.get("name") == clean or pdata.get("name") == repo_basename:
            return key
        pdir = pdata.get("dir", "")
        if pdir and Path(pdir).name == repo_basename:
            return key

    return None


def resolve_project_from_cwd(
    cwd: Optional[Path] = None, project_root: Optional[Path] = None
) -> Optional[str]:
    """CWD（または指定パス）がサテライト配下にある場合、該当する project_key を判定して返す。"""
    if cwd is None:
        cwd = Path.cwd().resolve()
    else:
        cwd = cwd.resolve()

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    project_root = project_root.resolve()

    # 1. CWD から上位ディレクトリを遡り docs/project.json を探索
    curr = cwd
    while True:
        pjson = curr / "docs" / "project.json"
        if pjson.exists():
            try:
                data = json.loads(pjson.read_text(encoding="utf-8"))
                if "key" in data and data["key"]:
                    return str(data["key"])
            except Exception:
                pass
        if curr == curr.parent or curr == project_root:
            break
        curr = curr.parent

    # 2. .project-registry.json の各 dir と CWD の包含関係を検証
    projects = load_project_registry(project_root)
    for key, pdata in projects.items():
        dir_rel = pdata.get("dir")
        if dir_rel:
            abs_sat_dir = (project_root / dir_rel).resolve()
            try:
                if cwd == abs_sat_dir or abs_sat_dir in cwd.parents:
                    return key
            except Exception:
                pass

    return None


def resolve_task_id_for_issue(
    project_key: str, issue_number: int, project_root: Optional[Path] = None
) -> Optional[str]:
    """project_key と GitHub Issue 番号からサテライト内の対応する task_id（例: TFG-0005）を逆引きする。"""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    projects = load_project_registry(project_root)
    pdata = projects.get(project_key, {})
    dir_rel = pdata.get("dir", f"projects/{pdata.get('name', '')}")
    sat_dir = project_root / dir_rel

    # 1. docs/tasks.md を探索: [KEY-XXXX] ... issue:#<NUM>
    tasks_md = sat_dir / "docs" / "tasks.md"
    if tasks_md.exists():
        try:
            content = tasks_md.read_text(encoding="utf-8")
            pattern = rf"\[({project_key}-\d{{4}}(?:-[A-Z])?)\].*?(?:issue:#{issue_number}\b|#{issue_number}\b)"
            m = re.search(pattern, content)
            if m:
                return m.group(1)
        except Exception as e:
            logger.debug(f"tasks.md 解析エラー: {e}")

    # 2. docs/issues/*.md のフロントマター探索
    issues_dir = sat_dir / "docs" / "issues"
    if issues_dir.exists():
        for md_file in issues_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                if re.search(rf"^issue(?:_number)?:\s*#?{issue_number}\b", text, re.MULTILINE):
                    m_task = re.search(r"^task_id:\s*([A-Za-z0-9_]+-\d+)", text, re.MULTILINE)
                    if m_task:
                        return m_task.group(1)
                    if ISSUE_ID_PATTERN.match(md_file.stem):
                        return md_file.stem
            except Exception:
                pass

    # 3. ゼロ埋め4桁の候補
    candidate = f"{project_key}-{issue_number:04d}"
    return candidate


def resolve_issue_number_for_task(
    task_id: str, project_root: Optional[Path] = None
) -> Optional[int]:
    """task_id (例: TFG-0005) から対応する GitHub Issue 番号を逆引きする。"""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    project_key = task_id.split("-")[0]
    projects = load_project_registry(project_root)
    pdata = projects.get(project_key, {})
    dir_rel = pdata.get("dir", f"projects/{pdata.get('name', '')}")
    sat_dir = project_root / dir_rel

    # 1. docs/issues/{task_id}.md
    spec_md = sat_dir / "docs" / "issues" / f"{task_id}.md"
    if spec_md.exists():
        try:
            text = spec_md.read_text(encoding="utf-8")
            m = re.search(r"^issue(?:_number)?:\s*#?(\d+)\b", text, re.MULTILINE)
            if m:
                return int(m.group(1))
        except Exception:
            pass

    # 2. docs/tasks.md
    tasks_md = sat_dir / "docs" / "tasks.md"
    if tasks_md.exists():
        try:
            text = tasks_md.read_text(encoding="utf-8")
            pattern = rf"\[{re.escape(task_id)}\].*?(?:issue:#(\d+)|#(\d+))"
            m = re.search(pattern, text)
            if m:
                num_str = m.group(1) or m.group(2)
                if num_str:
                    return int(num_str)
        except Exception:
            pass

    # 3. フォールバック: task_id の末尾数値 (例: TFG-0005 -> 5)
    m_num = re.search(r"-0*(\d+)(?:-[A-Z])?$", task_id)
    if m_num:
        return int(m_num.group(1))

    return None


def resolve_target_spec(
    target: str,
    project_hint: Optional[str] = None,
    cwd: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """任意の形式の指定 (URL, task_id, 数値) と CWD / project_hint から
    project_key, task_id, issue_number, github_repo を高精度に解決する。
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    target = target.strip()

    # 1. URL 形式の判定
    url_info = parse_github_issue_url(target)
    if url_info:
        repo_str, issue_num = url_info
        resolved_key = resolve_project_key_from_repo_or_name(repo_str, project_root)
        if not resolved_key and project_hint:
            resolved_key = resolve_project_key_from_repo_or_name(project_hint, project_root)
        task_id = (
            resolve_task_id_for_issue(resolved_key, issue_num, project_root)
            if resolved_key
            else None
        )
        return {
            "type": "url",
            "project_key": resolved_key,
            "task_id": task_id,
            "issue_number": issue_num,
            "github_repo": repo_str,
            "target": target,
        }

    # 2. タスクID形式 (例: TFG-0005) の判定
    if ISSUE_ID_PATTERN.match(target) or re.match(r"^[A-Za-z0-9_]+-\d+", target):
        task_pkey = target.split("-")[0]
        task_issue_num: Optional[int] = resolve_issue_number_for_task(target, project_root)
        projects = load_project_registry(project_root)
        pdata = projects.get(task_pkey, {})
        return {
            "type": "task_id",
            "project_key": task_pkey,
            "task_id": target,
            "issue_number": task_issue_num,
            "github_repo": pdata.get("github_repo"),
            "target": target,
        }

    # 3. 単なる数値 (例: 5 or #5) の判定
    target_clean = target.lstrip("#")
    if target_clean.isdigit():
        num_issue: int = int(target_clean)
        num_pkey: Optional[str] = None
        if project_hint:
            num_pkey = resolve_project_key_from_repo_or_name(project_hint, project_root)
        if not num_pkey:
            num_pkey = resolve_project_from_cwd(cwd, project_root)

        num_task_id = (
            resolve_task_id_for_issue(num_pkey, num_issue, project_root)
            if num_pkey
            else None
        )
        projects = load_project_registry(project_root)
        pdata = projects.get(num_pkey, {}) if num_pkey else {}
        return {
            "type": "issue_number",
            "project_key": num_pkey,
            "task_id": num_task_id,
            "issue_number": num_issue,
            "github_repo": pdata.get("github_repo"),
            "target": target,
        }

    # 4. それ以外（未解決）
    unknown_pkey: Optional[str] = resolve_project_key_from_repo_or_name(target, project_root)
    return {
        "type": "unknown",
        "project_key": unknown_pkey,
        "task_id": None,
        "issue_number": None,
        "github_repo": None,
        "target": target,
    }


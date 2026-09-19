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
from typing import Any, Dict, List, Literal, Optional

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


def validate_project_consistency(
    issue_id: str,
    project_key: str,
    metadata_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> None:
    """Issue ID 形式、プレフィックス、CLI project_key、台帳キー、
    meta ディレクトリ、project.json、project.json["key"] の必須存在と一致性を検証する (MULTI-001 §2②・§4)。
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

    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

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

    meta_rel = projects_dict[project_key].get("meta")
    if not meta_rel:
        raise ValueError(
            f"Missing 'meta' field for project '{project_key}' in .project-registry.json."
        )

    meta_dir_path = project_root / meta_rel
    if not meta_dir_path.exists():
        raise ValueError(f"Project metadata directory '{meta_dir_path}' does not exist.")

    proj_json = meta_dir_path / "project.json"
    if not proj_json.exists():
        raise ValueError(f"project.json does not exist at '{proj_json}'.")

    with open(proj_json, "r", encoding="utf-8") as pf:
        pdata = json.load(pf)
        pkey = pdata.get("key")
        if not pkey:
            raise ValueError(f"Missing 'key' field in project.json at '{proj_json}'.")
        if pkey != project_key:
            raise ValueError(
                f"Project key mismatch in project.json: expected '{project_key}', got '{pkey}'."
            )


# ==============================================================================
# 3. Project Exclusive Lock Management
# ==============================================================================


class ProjectLockManager:
    """衛星プロジェクトの排他制御（ロック機構）を管理するクラス (PM-037)."""

    def __init__(self, project_key: str, metadata_dir: Optional[Path] = None) -> None:
        self.project_key = project_key
        if metadata_dir is None:
            metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
        self.lock_dir = metadata_dir / "projects" / project_key
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
) -> None:
    """metadata/projects/<PROJECT_KEY>/state.json 内の該当 issue_id の状態項目を
    アトミックにマージ更新する (DD-003 §4.1.1)。旧フラットデータの自動マイグレーションを含む。
    """
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    state_file = metadata_dir / "projects" / project_key / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state_data: Dict[str, Any] = {}
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
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

    temp_file = state_file.with_name(f"state.json.{uuid.uuid4().hex}.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp_file, state_file)


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
    project_key: str, event_data: Dict[str, Any], metadata_dir: Optional[Path] = None
) -> None:
    """Graph の状態に影響を与えない個別ファイルイベント記録 (PM-050)"""
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    events_dir = metadata_dir / "projects" / project_key / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    execution_id = event_data.get("execution_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    # #20 (DD-003 §10.3): 永続化前の機密情報サニタイズ
    clean_event_data = sanitize_data(event_data)
    event_file = events_dir / f"event_{execution_id}_{timestamp}.json"

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
    特定のファイル名にハードコードせず、任意の衛星リポジトリの対象ファイルを動的に検出・解決する (MULTI-001 §2③・§4)。
    """
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

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

        if meta_dir:
            project_json = project_root / meta_dir / "project.json"
            if project_json.exists():
                with open(project_json, "r", encoding="utf-8") as pf:
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

            if not raw_target_files:
                tasks_md = project_root / meta_dir / "tasks.md"
                if tasks_md.exists():
                    text = tasks_md.read_text(encoding="utf-8")
                    matches = re.findall(r"[\w/.-]+\.py", text)
                    for m in matches:
                        if m not in raw_target_files:
                            raw_target_files.append(m)

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

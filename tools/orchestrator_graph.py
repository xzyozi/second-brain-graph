#!/usr/bin/env python3
"""
orchestrator_graph.py - LangGraph ベースの Issue 実行エントリポイント

Rev.2.7 〜 新アーキテクチャ。
本スクリプトは、日次バッチや人間の /work コマンドから呼び出され、
指定された Issue に対して Graph (plan, code, lint, test, review, done, escalate) を実行する。
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from filelock import FileLock, Timeout
from langgraph.graph import END, StateGraph

# プロジェクトルートをsys.pathに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.aider_runner import AiderRunError, get_git_diff, run_aider

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s %(levelname)s: %(message)s'
)
logger = logging.getLogger("orchestrator_graph")

ISSUE_ID_PATTERN = re.compile(r"^[A-Z]{2,5}-(?!0000)\d{4}(-[A-Z])?$")


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
        raise ValueError(f"Invalid Issue ID format: '{issue_id}'. Expected pattern: 'PROJECT-0001' (range 0001-9999).")

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
        raise ValueError(f"Project key '{project_key}' is not registered in .project-registry.json.")

    meta_rel = projects_dict[project_key].get("meta")
    if not meta_rel:
        raise ValueError(f"Missing 'meta' field for project '{project_key}' in .project-registry.json.")

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
            raise TimeoutError(f"Failed to acquire project lock for {self.project_key} within timeout.") from e

    def _release_lock(self) -> None:
        try:
            self.lock.release()
            logger.info(f"Lock released for project {self.project_key}")
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")


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
                if "issue_id" in raw_data and not any(isinstance(v, dict) for v in raw_data.values()):
                    old_id = raw_data.get("issue_id", issue_id)
                    state_data[old_id] = {
                        "status": raw_data.get("status", "PENDING"),
                        "review_round": raw_data.get("review_round", 0),
                        "max_round": raw_data.get("max_round", 3),
                        "error_category": raw_data.get("error_category"),
                        "updated_at": raw_data.get("updated_at", datetime.now(timezone.utc).isoformat()),
                    }
                else:
                    state_data = raw_data
        except Exception as e:
            logger.warning(f"Failed to read existing state.json for {project_key}: {e}")

    state_data[issue_id] = {
        "status": status,
        "review_round": review_round,
        "max_round": max_round,
        "error_category": error_category,
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
    DD-003 §4.1.1 監査スキーマ (actual_round = max(...), review_rounds, history_summary.review_verdict)
    に従って専用の FileLock 保護のもとアトミックに追記保存する。
    """
    if history_file is None:
        history_file = Path(__file__).resolve().parent.parent / "tools" / ".cache" / "execution_history.json"
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

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issue_id": state.get("issue_id", "unknown"),
            "project_key": state.get("project_key", "unknown"),
            "project_path": state.get("cwd", "unknown"),
            "final_status": final_status,
            "actual_round": actual_round,
            "review_round": rev_round,
            "max_round": state.get("max_round", 3),
            "lint_round": lint_round,
            "test_round": test_round,
            "error_category": state.get("error_category"),
            "error_message": state.get("error"),
            "llm_timeout_count": state.get("llm_timeout_count", 0),
            "review_rounds": state.get("review_rounds", []),
            "history_summary": {
                "lint_passed": state.get("status") in ["lint_passed", "test_passed", "review_lgtm", "COMPLETED"],
                "test_passed": state.get("status") in ["test_passed", "review_lgtm", "COMPLETED"],
                "review_verdict": rev_verdict,
            },
        }

        records = history_data.get("records", [])
        records.append(record)
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
        record_execution_history(state, final_status=final_status, review_round=review_round, history_file=history_file)
    except Exception as e:
        logger.warning(f"Failed to record execution history safely (keeping state '{final_status}'): {e}")


def write_event(project_key: str, event_data: Dict[str, Any], metadata_dir: Optional[Path] = None) -> None:
    """Graph の状態に影響を与えない個別ファイルイベント記録 (PM-050)"""
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    events_dir = metadata_dir / "projects" / project_key / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    execution_id = event_data.get("execution_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    event_file = events_dir / f"event_{execution_id}_{timestamp}.json"

    with open(event_file, "w", encoding="utf-8") as f:
        json.dump(event_data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def resolve_project_context(
    project_key: str,
    metadata_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """.project-registry.json からプロジェクトの dir, meta を解決し、
    実在する対象ファイル target_files と base_branch を特定する (MULTI-001 §2③・§2④・§5)。
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
        raw_target_files = []

        if meta_dir:
            project_json = project_root / meta_dir / "project.json"
            if project_json.exists():
                with open(project_json, "r", encoding="utf-8") as pf:
                    pdata = json.load(pf)
                    base_branch = pdata.get("base_branch", "develop")

            tasks_md = project_root / meta_dir / "tasks.md"
            if tasks_md.exists():
                text = tasks_md.read_text(encoding="utf-8")
                if "office_parser" in text or "TFG" in project_key:
                    raw_target_files.append("src/grep/office_parser.py")

        if not raw_target_files:
            raw_target_files.append("src/grep/office_parser.py")

        # ターゲットファイルの実在性を検証
        valid_target_files = []
        for tf in raw_target_files:
            abs_tf = cwd_path / tf
            if abs_tf.exists() and abs_tf.is_file():
                valid_target_files.append(tf)

        if not valid_target_files:
            logger.error(f"No valid target files found in satellite repo for project {project_key}.")
            return {"cwd": cwd, "target_files": [], "base_branch": base_branch, "valid": False}

        return {"cwd": cwd, "target_files": valid_target_files, "base_branch": base_branch, "valid": True}
    except Exception as e:
        logger.error(f"Failed to resolve project context for {project_key}: {e}")
        return {"cwd": None, "target_files": [], "base_branch": "develop", "valid": False}


class GraphState(TypedDict):
    issue_id: str
    project_key: str
    execution_id: str
    generation: int
    status: str
    error: Optional[str]
    error_category: Optional[str]
    llm_timeout_count: int
    review_round: int
    lint_round: int
    test_round: int
    max_round: int
    target_files: List[str]
    instruction: str
    cwd: Optional[str]
    base_branch: str
    aider_message: str
    impl_plan: Optional[str]
    lint_result: Optional[Dict[str, Any]]
    test_result: Optional[Dict[str, Any]]
    review_verdict: Optional[str]
    review_comments: Optional[List[str]]
    review_rounds: List[Dict[str, Any]]
    history_summary: Optional[Dict[str, Any]]
    rdjson: Optional[Dict[str, Any]]


def spec_draft_node(state: GraphState) -> GraphState:
    """Issue に対する実装方針計画を策定し、impl_plan へ構造保存するノード (DD-003 §4)."""
    logger.info("Executing spec_draft_node")
    from tools.llm_client import call_llm
    try:
        res = call_llm(
            role="planner",
            intent="spec_draft",
            system_prompt="You are a planner",
            user_prompt=f"Draft spec for {state['issue_id']}"
        )
        plan_str = res.get("content", str(res)) if isinstance(res, dict) else str(res)
        state["impl_plan"] = plan_str
    except Exception as e:
        if "timeout" in str(e).lower():
            logger.warning(f"Timeout caught in spec_draft_node: {e}")
            state["llm_timeout_count"] = state.get("llm_timeout_count", 0) + 1
            state["error_category"] = "LLM_TIMEOUT"
            state["error"] = str(e)
            if state["llm_timeout_count"] >= 2:
                state["status"] = "FAILED_SYSTEM"
            else:
                state["status"] = "retry_spec_draft"
        else:
            logger.error(f"Error in spec_draft_node: {e}")
            state["status"] = "FAILED_SYSTEM"
            state["error_category"] = "SYSTEM_ERROR"
            state["error"] = str(e)
    return state


def code_node(state: GraphState) -> GraphState:
    """Aider CLI を呼んでコード編集を実施するノード。
    ・AiderRunError 発生時: LLM_TIMEOUT としてカウンタ加算、1回目は再試行、2回目は FAILED_SYSTEM とする。
    ・False 返却時: 即座に FAILED_SYSTEM に正規化して終端停止する。
    """
    logger.info("Executing code_node with AiderRunner")
    instruction = state.get("instruction", "Apply edits")
    if state.get("impl_plan"):
        instruction += f"\n\nImplementation Plan:\n{state['impl_plan']}"
    if state.get("aider_message"):
        instruction += f"\n\nFeedback:\n{state['aider_message']}"

    target_files = state.get("target_files", [])
    cwd = state.get("cwd")

    try:
        success = run_aider(instruction=instruction, target_files=target_files, cwd=cwd)
        if success:
            state["status"] = "code_completed"
        else:
            logger.error("Aider execution returned False (non-zero exit code or CLI missing).")
            state["status"] = "FAILED_SYSTEM"
            state["error_category"] = "SYSTEM_ERROR"
            state["error"] = "Aider execution returned False"
    except AiderRunError as e:
        logger.warning(f"AiderRunError caught in code_node: {e}")
        state["llm_timeout_count"] = state.get("llm_timeout_count", 0) + 1
        state["error_category"] = "LLM_TIMEOUT"
        state["error"] = str(e)
        if state["llm_timeout_count"] >= 2:
            state["status"] = "FAILED_SYSTEM"
        else:
            state["status"] = "retry_code"
    return state


def lint_node(state: GraphState) -> GraphState:
    """Ruff による静的解析を実行するノード (DD-003 §4)。
    例外発生時は FAILED_SYSTEM / SYSTEM_ERROR に設定して安全停止する。
    """
    logger.info("Executing lint_node (Ruff check)")
    cwd = state.get("cwd")
    try:
        res = subprocess.run(["ruff", "check", "."], cwd=cwd, capture_output=True, text=True)
        state["lint_result"] = {"returncode": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        if res.returncode == 0:
            state["status"] = "lint_passed"
        else:
            state["lint_round"] = state.get("lint_round", 0) + 1
            state["error_category"] = "LINT_ERROR"
            state["aider_message"] = f"Ruff lint failed:\n{res.stdout}"
            if state["lint_round"] >= state.get("max_round", 3):
                state["status"] = "FAILED_B7"
            else:
                state["status"] = "retry_code"
    except Exception as e:
        logger.error(f"Error running lint: {e}")
        state["status"] = "FAILED_SYSTEM"
        state["error_category"] = "SYSTEM_ERROR"
        state["error"] = str(e)
    return state


def run_pytest_node(state: GraphState) -> GraphState:
    """Pytest による単体テストを実行するノード (DD-003 §4)。
    例外発生時は FAILED_SYSTEM / SYSTEM_ERROR に設定して安全停止する。
    """
    logger.info("Executing test_node (Pytest)")
    cwd = state.get("cwd")
    try:
        res = subprocess.run(["pytest"], cwd=cwd, capture_output=True, text=True)
        state["test_result"] = {"returncode": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        if res.returncode == 0:
            state["status"] = "test_passed"
        else:
            state["test_round"] = state.get("test_round", 0) + 1
            state["error_category"] = "TEST_ERROR"
            state["aider_message"] = f"Pytest failed:\n{res.stdout}"
            if state["test_round"] >= state.get("max_round", 3):
                state["status"] = "FAILED_B7"
            else:
                state["status"] = "retry_code"
    except Exception as e:
        logger.error(f"Error running pytest: {e}")
        state["status"] = "FAILED_SYSTEM"
        state["error_category"] = "SYSTEM_ERROR"
        state["error"] = str(e)
    return state


def review_node(state: GraphState) -> GraphState:
    """Reviewer LLM 呼び出しノード (DD-003 §4)。
    プロンプトに Git diff を注入し、応答形式の厳格検証、RDJSON 標準入力による Reviewdog パイプ連携、
    および LGTM を含む全レビューの review_rounds 履歴原子的保存を行う。
    例外発生時または不整合時は FAILED_SYSTEM / SYSTEM_ERROR に設定して安全停止する。
    """
    logger.info("Executing review_node")
    from tools.llm_client import call_llm
    cwd = state.get("cwd")
    diff_text = get_git_diff(cwd) if cwd else ""
    user_prompt = (
        f"Review changes for {state['issue_id']}.\n\n"
        f"Git diff:\n{diff_text if diff_text else '(No git diff detected)'}"
    )

    try:
        res = call_llm(
            role="reviewer",
            intent="code_review",
            system_prompt=(
                "You are a reviewer. You must respond with JSON containing a 'verdict' "
                "('LGTM' or 'changes_requested') and 'comments'."
            ),
            user_prompt=user_prompt,
            expect_json=True
        )

        if not isinstance(res, dict) or "verdict" not in res or res.get("verdict") not in ["LGTM", "changes_requested"]:
            logger.error(f"Invalid review response structure: {res}")
            state["status"] = "FAILED_SYSTEM"
            state["error_category"] = "SYSTEM_ERROR"
            state["error"] = f"Invalid review response structure from LLM: {res}"
            return state

        verdict = res["verdict"]
        rev_comments = res.get("comments", [])
        rev_round = state.get("review_round", 0) + 1
        state["review_round"] = rev_round
        state["review_verdict"] = verdict
        state["review_comments"] = rev_comments if isinstance(rev_comments, list) else [str(rev_comments)]

        # RDJSON 構造化
        rd_diagnostics = [
            {
                "message": str(c),
                "location": {"path": state.get("target_files", [""])[0], "range": {"start": {"line": 1}}},
                "severity": "WARNING",
            }
            for c in (rev_comments if isinstance(rev_comments, list) else [rev_comments])
        ]
        state["rdjson"] = {
            "source": {"name": "ReviewerLLM", "url": ""},
            "diagnostics": rd_diagnostics,
        }

        # 全レビュー (LGTM を含む) を review_rounds に記録
        rounds = state.get("review_rounds", [])
        rounds.append({
            "review_round": rev_round,
            "verdict": verdict,
            "comments": rev_comments,
            "rdjson": state["rdjson"],
        })
        state["review_rounds"] = rounds

        # Reviewdog 標準入力 (input=...) パイプ連携
        if cwd and Path(cwd).exists() and (Path(cwd) / ".git").exists():
            try:
                rd_input = json.dumps(state["rdjson"])
                res_rd = subprocess.run(
                    ["reviewdog", "-f=rdjson", "-diff=git diff HEAD"],
                    input=rd_input, text=True, cwd=cwd, capture_output=True
                )
                logger.info(f"Reviewdog pipe execution code: {res_rd.returncode}")
            except Exception as rde:
                logger.warning(f"Reviewdog pipe execution skipped or unavailable: {rde}")

        if verdict == "LGTM":
            state["status"] = "review_lgtm"
        else:
            state["error_category"] = "REVIEW_REJECTED"
            state["aider_message"] = f"Review comments:\n{rev_comments}"
            if rev_round >= state.get("max_round", 3):
                state["status"] = "FAILED_B7"
            else:
                state["status"] = "retry_code"
    except Exception as e:
        if "timeout" in str(e).lower():
            logger.warning(f"Timeout caught in review_node: {e}")
            state["llm_timeout_count"] = state.get("llm_timeout_count", 0) + 1
            state["error_category"] = "LLM_TIMEOUT"
            state["error"] = str(e)
            if state["llm_timeout_count"] >= 2:
                state["status"] = "FAILED_SYSTEM"
            else:
                state["status"] = "retry_review"
        else:
            logger.error(f"Error in review_node: {e}")
            state["status"] = "FAILED_SYSTEM"
            state["error_category"] = "SYSTEM_ERROR"
            state["error"] = str(e)
    return state


def done_node(state: GraphState) -> GraphState:
    """PR 作成および完了ノード (DD-003 §4)。
    既存インデックス非空チェック -> 明示的 git add -> git commit -> git push -> gh pr create パイプラインを実行。
    失敗時は PR_FAILED / PR_ERROR としてブランチと差分を安全保持する。
    """
    logger.info("Executing done_node (PR creation pipeline)")
    cwd = state.get("cwd")
    base_branch = state.get("base_branch", "develop")
    head_branch = f"sbos/{state['issue_id']}"
    target_files = state.get("target_files", [])

    try:
        if cwd and Path(cwd).exists() and (Path(cwd) / ".git").exists():
            # インデックス混入防止: 既存 staged 変更の有無を確認
            diff_cached = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=cwd, capture_output=True, text=True
            )
            if diff_cached.returncode != 0:
                logger.error(f"git diff --cached failed: {diff_cached.stderr}")
                state["status"] = "PR_FAILED"
                state["error_category"] = "PR_ERROR"
                state["error"] = f"git diff --cached failed: {diff_cached.stderr}"
                return state

            if diff_cached.stdout.strip():
                logger.error("Existing staged changes detected in git index before commit. Aborting.")
                state["status"] = "PR_FAILED"
                state["error_category"] = "PR_ERROR"
                state["error"] = "Existing staged changes detected in index before commit"
                return state

            # 1. 明示的な git add
            if target_files:
                add_res = subprocess.run(["git", "add", "--"] + target_files, cwd=cwd, capture_output=True, text=True)
                if add_res.returncode != 0:
                    logger.error(f"git add failed: {add_res.stderr}")
                    state["status"] = "PR_FAILED"
                    state["error_category"] = "PR_ERROR"
                    state["error"] = f"git add failed: {add_res.stderr}"
                    return state

            # 2. 未コミット差分の存在確認とコミット
            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True)
            if status_res.returncode != 0:
                logger.error(f"git status failed: {status_res.stderr}")
                state["status"] = "PR_FAILED"
                state["error_category"] = "PR_ERROR"
                state["error"] = f"git status failed: {status_res.stderr}"
                return state

            if status_res.stdout.strip():
                commit_res = subprocess.run(
                    ["git", "commit", "-m", f"feat: [{state['issue_id']}] 自動実装完了"],
                    cwd=cwd, capture_output=True, text=True
                )
                if commit_res.returncode != 0:
                    logger.error(f"git commit failed: {commit_res.stderr}")
                    state["status"] = "PR_FAILED"
                    state["error_category"] = "PR_ERROR"
                    state["error"] = f"git commit failed: {commit_res.stderr}"
                    return state

            # 3. リモートへ Push
            push_res = subprocess.run(
                ["git", "push", "-u", "origin", head_branch],
                cwd=cwd, capture_output=True, text=True
            )
            if push_res.returncode != 0:
                logger.warning(f"Git push failed: {push_res.stderr}")
                state["status"] = "PR_FAILED"
                state["error_category"] = "PR_ERROR"
                state["error"] = f"Git push failed: {push_res.stderr}"
                return state

        # 4. PR の作成
        pr_res = subprocess.run(
            ["gh", "pr", "create", "--base", base_branch, "--head", head_branch,
             "--title", f"[{state['issue_id']}] 自動実装完了", "--body", "Agent生成PR"],
            cwd=cwd, capture_output=True, text=True
        )
        if pr_res.returncode == 0:
            state["status"] = "COMPLETED"
        else:
            logger.warning(f"PR creation failed: {pr_res.stderr}")
            state["status"] = "PR_FAILED"
            state["error_category"] = "PR_ERROR"
            state["error"] = f"PR creation failed: {pr_res.stderr}"
    except Exception as e:
        logger.warning(f"Error in done_node: {e}")
        state["status"] = "PR_FAILED"
        state["error_category"] = "PR_ERROR"
        state["error"] = str(e)
    return state


def escalate_node(state: GraphState) -> GraphState:
    """上限到達時・例外発生時のエスカレーション停止ノード (DD-003 §4.1)。"""
    logger.info(f"Executing escalate_node for {state['issue_id']}")
    if state.get("status") not in ["FAILED_B7", "FAILED_SYSTEM"]:
        state["status"] = "FAILED_B7" if state.get("error_category") in [
            "LINT_ERROR", "TEST_ERROR", "REVIEW_REJECTED"
        ] else "FAILED_SYSTEM"
    return state


def execute_issue(
    issue_id: str,
    project_key: str,
    metadata_dir: Optional[Path] = None,
    history_file: Optional[Path] = None,
    project_root: Optional[Path] = None,
    allow_offline_git: bool = False,
) -> None:
    execution_id = uuid.uuid4().hex
    try:
        # 規約準拠の Issue ID 範囲およびプロジェクトキー整合検証
        validate_project_consistency(issue_id, project_key, metadata_dir=metadata_dir, project_root=project_root)

        logger.info(f"Starting execution for Issue: {issue_id}, Execution ID: {execution_id}")

        ctx = resolve_project_context(project_key, metadata_dir=metadata_dir, project_root=project_root)
        cwd = ctx.get("cwd")
        target_files = ctx.get("target_files", [])
        base_branch = ctx.get("base_branch", "develop")
        is_valid = ctx.get("valid", False)

        # 母艦誤編集防止フェイルセーフ (MULTI-001 §2③・§5)
        if not (is_valid and cwd and target_files):
            logger.error(f"Failsafe triggered: Invalid satellite context for project {project_key}. Aborting.")
            update_task_state(
                project_key,
                issue_id,
                status="FAILED_SYSTEM",
                error_category="SYSTEM_ERROR",
                metadata_dir=metadata_dir,
            )
            safe_record_execution_history(
                {
                    "issue_id": issue_id,
                    "project_key": project_key,
                    "cwd": cwd,
                    "error_category": "SYSTEM_ERROR",
                    "error": "Failsafe triggered: Invalid project directory or missing target_files",
                },
                final_status="FAILED_SYSTEM",
                history_file=history_file,
            )
            return

        with ProjectLockManager(project_key, metadata_dir=metadata_dir):
            # 作業ブランチ (sbos/<issue-id>) の安全な準備 (git switch / pull) (PM-036)
            if cwd and Path(cwd).exists() and (Path(cwd) / ".git").exists():
                try:
                    sw_base = subprocess.run(
                        ["git", "switch", base_branch],
                        cwd=cwd, capture_output=True, text=True
                    )
                    if sw_base.returncode != 0:
                        logger.error(f"git switch {base_branch} failed: {sw_base.stderr}")
                        update_task_state(
                            project_key, issue_id, status="FAILED_SYSTEM",
                            error_category="SYSTEM_ERROR", metadata_dir=metadata_dir
                        )
                        safe_record_execution_history(
                            {
                                "issue_id": issue_id, "project_key": project_key, "cwd": cwd,
                                "error_category": "SYSTEM_ERROR",
                                "error": f"git switch {base_branch} failed: {sw_base.stderr}",
                            },
                            final_status="FAILED_SYSTEM", history_file=history_file
                        )
                        return

                    pull_res = subprocess.run(
                        ["git", "pull", "--ff-only", "origin", base_branch],
                        cwd=cwd, capture_output=True, text=True
                    )
                    if pull_res.returncode != 0 and not allow_offline_git:
                        logger.error(f"git pull --ff-only failed: {pull_res.stderr}")
                        update_task_state(
                            project_key, issue_id, status="FAILED_SYSTEM",
                            error_category="SYSTEM_ERROR", metadata_dir=metadata_dir
                        )
                        safe_record_execution_history(
                            {
                                "issue_id": issue_id, "project_key": project_key, "cwd": cwd,
                                "error_category": "SYSTEM_ERROR",
                                "error": f"git pull --ff-only failed: {pull_res.stderr}",
                            },
                            final_status="FAILED_SYSTEM", history_file=history_file
                        )
                        return

                    head_branch = f"sbos/{issue_id}"
                    sw_head = subprocess.run(["git", "switch", head_branch], cwd=cwd, capture_output=True, text=True)
                    if sw_head.returncode != 0:
                        sw_c = subprocess.run(
                            ["git", "switch", "-c", head_branch, base_branch],
                            cwd=cwd, capture_output=True, text=True
                        )
                        if sw_c.returncode != 0:
                            logger.error(f"git switch -c {head_branch} failed: {sw_c.stderr}")
                            update_task_state(
                                project_key, issue_id, status="FAILED_SYSTEM",
                                error_category="SYSTEM_ERROR", metadata_dir=metadata_dir
                            )
                            safe_record_execution_history(
                                {
                                    "issue_id": issue_id, "project_key": project_key, "cwd": cwd,
                                    "error_category": "SYSTEM_ERROR",
                                    "error": f"git switch -c failed: {sw_c.stderr}",
                                },
                                final_status="FAILED_SYSTEM", history_file=history_file
                            )
                            return
                except Exception as ge:
                    logger.error(f"Failed git branch setup in {cwd}: {ge}")
                    update_task_state(
                        project_key,
                        issue_id,
                        status="FAILED_SYSTEM",
                        error_category="SYSTEM_ERROR",
                        metadata_dir=metadata_dir,
                    )
                    safe_record_execution_history(
                        {
                            "issue_id": issue_id,
                            "project_key": project_key,
                            "cwd": cwd,
                            "error_category": "SYSTEM_ERROR",
                            "error": f"Git branch setup failed: {ge}",
                        },
                        final_status="FAILED_SYSTEM",
                        history_file=history_file,
                    )
                    return

            logger.info("Setting up context and starting graph execution...")
            workflow = StateGraph(GraphState)
            workflow.add_node("spec_draft", spec_draft_node)
            workflow.add_node("code_node", code_node)
            workflow.add_node("lint_node", lint_node)
            workflow.add_node("test_node", run_pytest_node)
            workflow.add_node("review_node", review_node)
            workflow.add_node("done_node", done_node)
            workflow.add_node("escalate_node", escalate_node)

            workflow.set_entry_point("spec_draft")

            def route_after_spec(s: GraphState) -> str:
                if s.get("status") == "FAILED_SYSTEM":
                    return "escalate_node"
                if s.get("status") == "retry_spec_draft":
                    return "spec_draft"
                return "code_node"

            workflow.add_conditional_edges("spec_draft", route_after_spec, {
                "escalate_node": "escalate_node",
                "spec_draft": "spec_draft",
                "code_node": "code_node",
            })

            def route_after_code(s: GraphState) -> str:
                if s.get("status") == "FAILED_SYSTEM":
                    return "escalate_node"
                if s.get("status") == "retry_code":
                    return "code_node"
                return "lint_node"

            workflow.add_conditional_edges("code_node", route_after_code, {
                "escalate_node": "escalate_node",
                "code_node": "code_node",
                "lint_node": "lint_node",
            })

            def route_after_lint(s: GraphState) -> str:
                if s.get("status") == "FAILED_SYSTEM":
                    return "escalate_node"
                if s.get("status") == "lint_passed":
                    return "test_node"
                if s.get("status") == "FAILED_B7":
                    return "escalate_node"
                return "code_node"

            workflow.add_conditional_edges("lint_node", route_after_lint, {
                "test_node": "test_node",
                "escalate_node": "escalate_node",
                "code_node": "code_node",
            })

            def route_after_test(s: GraphState) -> str:
                if s.get("status") == "FAILED_SYSTEM":
                    return "escalate_node"
                if s.get("status") == "test_passed":
                    return "review_node"
                if s.get("status") == "FAILED_B7":
                    return "escalate_node"
                return "code_node"

            workflow.add_conditional_edges("test_node", route_after_test, {
                "review_node": "review_node",
                "escalate_node": "escalate_node",
                "code_node": "code_node",
            })

            def route_after_review(s: GraphState) -> str:
                if s.get("status") == "FAILED_SYSTEM":
                    return "escalate_node"
                if s.get("status") == "retry_review":
                    return "review_node"
                if s.get("status") == "review_lgtm":
                    return "done_node"
                if s.get("status") == "FAILED_B7":
                    return "escalate_node"
                return "code_node"

            workflow.add_conditional_edges("review_node", route_after_review, {
                "done_node": "done_node",
                "escalate_node": "escalate_node",
                "review_node": "review_node",
                "code_node": "code_node",
            })

            workflow.add_edge("done_node", END)
            workflow.add_edge("escalate_node", END)

            app = workflow.compile()

            initial_state = GraphState(
                issue_id=issue_id,
                project_key=project_key,
                execution_id=execution_id,
                generation=0,
                status="running",
                error=None,
                error_category=None,
                llm_timeout_count=0,
                review_round=0,
                lint_round=0,
                test_round=0,
                max_round=3,
                target_files=target_files,
                instruction=f"Implement issue {issue_id}",
                cwd=cwd,
                base_branch=base_branch,
                aider_message="",
                impl_plan=None,
                lint_result=None,
                test_result=None,
                review_verdict=None,
                review_comments=None,
                review_rounds=[],
                history_summary=None,
                rdjson=None,
            )
            final_state = app.invoke(initial_state)

            final_status = final_state.get("status", "COMPLETED")
            error_cat = final_state.get("error_category")

            # 1. アトミックに state.json 更新
            update_task_state(
                project_key,
                issue_id,
                status=final_status,
                review_round=final_state.get("review_round", 0),
                max_round=final_state.get("max_round", 3),
                error_category=error_cat,
                metadata_dir=metadata_dir,
            )
            # 2. 確定済ステートを保護する統一ヘルパーで execution_history.json 追記保存
            safe_record_execution_history(
                final_state,
                final_status=final_status,
                review_round=final_state.get("review_round", 0),
                history_file=history_file,
            )
            logger.info(f"Execution completed for Issue: {issue_id} with status: {final_status}")

    except TimeoutError:
        logger.warning(f"Execution skipped for {issue_id} due to lock timeout.")
        update_task_state(
            project_key,
            issue_id,
            status="SKIPPED_LOCKED",
            error_category="LOCKED",
            metadata_dir=metadata_dir,
        )
        safe_record_execution_history(
            {
                "issue_id": issue_id,
                "project_key": project_key,
                "cwd": None,
                "error_category": "LOCKED",
                "error": "Failed to acquire lock within timeout",
            },
            final_status="SKIPPED_LOCKED",
            history_file=history_file,
        )
        write_event(
            project_key,
            {
                "event": "SKIPPED_LOCKED",
                "issue_id": issue_id,
                "execution_id": execution_id,
                "timestamp": datetime.now().isoformat(),
            },
            metadata_dir=metadata_dir,
        )
    except Exception as e:
        logger.error(f"Unexpected error outside lock for {issue_id}: {e}")
        update_task_state(
            project_key,
            issue_id,
            status="FAILED_SYSTEM",
            error_category="SYSTEM_ERROR",
            metadata_dir=metadata_dir,
        )
        safe_record_execution_history(
            {
                "issue_id": issue_id,
                "project_key": project_key,
                "cwd": None,
                "error_category": "SYSTEM_ERROR",
                "error": str(e),
            },
            final_status="FAILED_SYSTEM",
            history_file=history_file,
        )
        raise


def cmd_orchestrate(project_key: Optional[str] = None, cache_file: Optional[Path] = None) -> None:
    """tools/.cache/priority-cache.json を読み込み、未完了 Issue の上位3件および提案を表示する (DD-003 §5, §6).
    正本構造 {"issues": [{"id": "...", "score": ...}]} を最優先パースする。
    """
    if cache_file is None:
        cache_file = Path(__file__).resolve().parent.parent / "tools" / ".cache" / "priority-cache.json"
    logger.info(f"Orchestrating uncompleted issues (project_key: {project_key or 'ALL'})")

    if not cache_file.exists():
        logger.info("Priority cache file does not exist. Please run priority cache generator.")
        return

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cdata = json.load(f)

        raw_items = cdata.get("issues") or cdata.get("tasks") or []
        items = []
        for item in raw_items:
            iid = item.get("id") or item.get("issue_id")
            title = item.get("title", "")
            score = item.get("score", 0)
            pkey = item.get("project_key") or (iid.split("-")[0] if iid and "-" in iid else None)
            if iid:
                items.append({"issue_id": iid, "title": title, "score": score, "project_key": pkey})

        if project_key:
            items = [i for i in items if i.get("project_key") == project_key]

        if not items:
            logger.info("No uncompleted issues found in priority cache.")
            return

        sorted_items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
        top_items = sorted_items[:3]

        logger.info("=== Top 3 Priority Issues ===")
        for idx, item in enumerate(top_items, 1):
            logger.info(f"[{idx}] ID: {item.get('issue_id')} | Title: {item.get('title')} | Score: {item.get('score')}")

        top_issue = top_items[0].get("issue_id")
        logger.info(f"Suggested Command: python tools/orchestrator_graph.py execute --issue-id {top_issue}")
    except Exception as e:
        logger.error(f"Failed to read priority cache: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph Orchestrator")
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommands")

    exec_parser = subparsers.add_parser("execute", help="Execute task for issue")
    exec_parser.add_argument("--issue-id", required=True, help="Target Issue ID (e.g. TFG-0004)")
    exec_parser.add_argument("--project-key", help="Target Project Key (Resolved from Issue ID if omitted)")

    orch_parser = subparsers.add_parser("orchestrate", help="Orchestrate uncompleted issues")
    orch_parser.add_argument("--project-key", help="Target Project Key (All if omitted)")

    args = parser.parse_args()

    if args.subcommand == "execute":
        issue_id = args.issue_id
        project_key = args.project_key
        if not project_key and "-" in issue_id:
            project_key = issue_id.split("-")[0]
        if not project_key:
            logger.error("Could not resolve project-key from issue-id.")
            sys.exit(1)

        validate_project_consistency(issue_id, project_key)
        execute_issue(issue_id, project_key)
    elif args.subcommand == "orchestrate":
        cmd_orchestrate(args.project_key)
    else:
        legacy_parser = argparse.ArgumentParser()
        legacy_parser.add_argument("--issue-id", help="Target Issue ID")
        legacy_parser.add_argument("--project-key", help="Target Project Key")
        leg_args, _ = legacy_parser.parse_known_args()
        if leg_args.issue_id and leg_args.project_key:
            validate_project_consistency(leg_args.issue_id, leg_args.project_key)
            execute_issue(leg_args.issue_id, leg_args.project_key)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()

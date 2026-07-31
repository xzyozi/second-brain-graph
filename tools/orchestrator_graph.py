#!/usr/bin/env python3
"""
orchestrator_graph.py - LangGraph ベースの Issue 実行エントリポイント

Rev.2.7 〜 新アーキテクチャ。
本スクリプトは、日次バッチや人間の /work コマンドから呼び出され、
指定された Issue に対して Graph (plan, code, lint, test, review, done, escalate) を実行する。
"""

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, TypedDict
import uuid

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
        except Timeout:
            logger.error(f"Failed to acquire project lock for {self.project_key} within timeout.")
            raise TimeoutError(f"Failed to acquire project lock for {self.project_key} within timeout.")

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
                        "updated_at": raw_data.get("updated_at", datetime.now().isoformat()),
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
        "updated_at": datetime.now().isoformat(),
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
    専用の FileLock 保護のもとアトミックに追記保存する (DD-003 §4.1.1)。
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

        record = {
            "timestamp": datetime.now().isoformat(),
            "issue_id": state.get("issue_id", "unknown"),
            "project_key": state.get("project_key", "unknown"),
            "project_path": state.get("cwd", "unknown"),
            "final_status": final_status,
            "review_round": review_round,
            "max_round": state.get("max_round", 3),
            "lint_round": state.get("lint_round", 0),
            "test_round": state.get("test_round", 0),
            "error_category": state.get("error_category"),
            "error_message": state.get("error"),
            "llm_timeout_count": state.get("llm_timeout_count", 0),
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


def spec_draft_node(state: GraphState) -> GraphState:
    logger.info("Executing spec_draft_node")
    from tools.llm_client import call_llm
    call_llm(
        role="planner",
        intent="spec_draft",
        system_prompt="You are a planner",
        user_prompt=f"Draft spec for {state['issue_id']}"
    )
    return state


def code_node(state: GraphState) -> GraphState:
    """Aider CLI を呼んでコード編集を実施するノード。
    ・AiderRunError 発生時: LLM_TIMEOUT としてカウンタ加算、1回目は再試行、2回目は FAILED_SYSTEM とする。
    ・False 返却時: 即座に FAILED_SYSTEM に正規化して終端停止する。
    """
    logger.info("Executing code_node with AiderRunner")
    instruction = state.get("instruction", "Apply edits")
    if state.get("aider_message"):
        instruction += f"\n\n{state['aider_message']}"

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
    プロンプトに Git diff を注入し、応答形式の厳格検証を行う。
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
        if verdict == "LGTM":
            state["status"] = "review_lgtm"
        else:
            state["review_round"] = state.get("review_round", 0) + 1
            state["error_category"] = "REVIEW_REJECTED"
            state["aider_message"] = f"Review comments:\n{res.get('comments', [])}"
            if state["review_round"] >= state.get("max_round", 3):
                state["status"] = "FAILED_B7"
            else:
                state["status"] = "retry_code"
    except Exception as e:
        logger.error(f"Error in review_node: {e}")
        state["status"] = "FAILED_SYSTEM"
        state["error_category"] = "SYSTEM_ERROR"
        state["error"] = str(e)
    return state


def done_node(state: GraphState) -> GraphState:
    """PR 作成および完了ノード (DD-003 §4)。
    明示的 git add -> git commit -> git push -> gh pr create パイプラインを実行。
    失敗時は PR_FAILED / PR_ERROR としてブランチと差分を安全保持する。
    """
    logger.info("Executing done_node (PR creation pipeline)")
    cwd = state.get("cwd")
    base_branch = state.get("base_branch", "develop")
    head_branch = f"sbos/{state['issue_id']}"
    target_files = state.get("target_files", [])

    try:
        if cwd and Path(cwd).exists() and (Path(cwd) / ".git").exists():
            # 1. 明示的な git add
            if target_files:
                subprocess.run(["git", "add", "--"] + target_files, cwd=cwd, capture_output=True, text=True)

            # 2. 未コミット差分の存在確認とコミット
            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True)
            if status_res.stdout.strip():
                subprocess.run(
                    ["git", "commit", "-m", f"feat: [{state['issue_id']}] 自動実装完了"],
                    cwd=cwd, check=True, capture_output=True, text=True
                )

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
) -> None:
    execution_id = uuid.uuid4().hex
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
        record_execution_history(
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

    try:
        with ProjectLockManager(project_key, metadata_dir=metadata_dir):
            # 作業ブランチ (sbos/<issue-id>) の安全な準備 (git switch / pull) (PM-036)
            if cwd and Path(cwd).exists() and (Path(cwd) / ".git").exists():
                try:
                    subprocess.run(
                        ["git", "switch", base_branch],
                        cwd=cwd, check=True, capture_output=True, text=True
                    )
                    try:
                        subprocess.run(
                            ["git", "pull", "--ff-only", "origin", base_branch],
                            cwd=cwd, capture_output=True, text=True
                        )
                    except Exception:
                        pass  # remote may not exist in test env

                    head_branch = f"sbos/{issue_id}"
                    sw_res = subprocess.run(["git", "switch", head_branch], cwd=cwd, capture_output=True, text=True)
                    if sw_res.returncode != 0:
                        subprocess.run(
                            ["git", "switch", "-c", head_branch, base_branch],
                            cwd=cwd, check=True, capture_output=True, text=True
                        )
                except Exception as ge:
                    logger.error(f"Failed git branch setup in {cwd}: {ge}")
                    update_task_state(
                        project_key,
                        issue_id,
                        status="FAILED_SYSTEM",
                        error_category="SYSTEM_ERROR",
                        metadata_dir=metadata_dir,
                    )
                    record_execution_history(
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

            try:
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
                workflow.add_edge("spec_draft", "code_node")

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
                    if s.get("status") == "review_lgtm":
                        return "done_node"
                    if s.get("status") == "FAILED_B7":
                        return "escalate_node"
                    return "code_node"

                workflow.add_conditional_edges("review_node", route_after_review, {
                    "done_node": "done_node",
                    "escalate_node": "escalate_node",
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
                )
                final_state = app.invoke(initial_state)

                final_status = final_state.get("status", "COMPLETED")
                error_cat = final_state.get("error_category")

                # アトミックに state.json 更新および execution_history.json 追記保存 (DD-003 §4.1.1)
                update_task_state(
                    project_key,
                    issue_id,
                    status=final_status,
                    review_round=final_state.get("review_round", 0),
                    max_round=final_state.get("max_round", 3),
                    error_category=error_cat,
                    metadata_dir=metadata_dir,
                )
                record_execution_history(
                    final_state,
                    final_status=final_status,
                    review_round=final_state.get("review_round", 0),
                    history_file=history_file,
                )
                logger.info(f"Execution completed for Issue: {issue_id} with status: {final_status}")

            except Exception as e:
                logger.error(f"Execution failed for {issue_id}: {e}")
                update_task_state(
                    project_key,
                    issue_id,
                    status="FAILED_SYSTEM",
                    error_category="SYSTEM_ERROR",
                    metadata_dir=metadata_dir,
                )
                record_execution_history(
                    {
                        "issue_id": issue_id,
                        "project_key": project_key,
                        "cwd": cwd,
                        "error_category": "SYSTEM_ERROR",
                        "error": str(e),
                    },
                    final_status="FAILED_SYSTEM",
                    history_file=history_file,
                )

    except TimeoutError:
        logger.warning(f"Execution skipped for {issue_id} due to lock timeout.")
        update_task_state(
            project_key,
            issue_id,
            status="SKIPPED_LOCKED",
            error_category="LOCKED",
            metadata_dir=metadata_dir,
        )
        record_execution_history(
            {
                "issue_id": issue_id,
                "project_key": project_key,
                "cwd": cwd,
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
        raise


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
        execute_issue(issue_id, project_key)
    elif args.subcommand == "orchestrate":
        project_key = args.project_key
        logger.info(f"Orchestrating uncompleted issues for project_key: {project_key or 'ALL'}")
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
        registry_file = metadata_dir / ".project-registry.json"
        if registry_file.exists():
            with open(registry_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
            logger.info(f"Registered projects in registry: {list(reg.get('projects', {}).keys())}")
    else:
        # 互換性のためフラグ引数での直接呼び出しもサポート
        legacy_parser = argparse.ArgumentParser()
        legacy_parser.add_argument("--issue-id", help="Target Issue ID")
        legacy_parser.add_argument("--project-key", help="Target Project Key")
        leg_args, _ = legacy_parser.parse_known_args()
        if leg_args.issue_id and leg_args.project_key:
            execute_issue(leg_args.issue_id, leg_args.project_key)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()

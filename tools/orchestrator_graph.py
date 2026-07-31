#!/usr/bin/env python3
"""
orchestrator_graph.py - LangGraph ベースの Issue 実行エントリポイント

Rev.2.7 〜 新アーキテクチャ。
本スクリプトは、日次バッチや人間の /work コマンドから呼び出され、
指定された Issue に対して Graph (plan_node, code_node, etc.) を実行する。
"""

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, TypedDict
import uuid

from filelock import FileLock, Timeout
from langgraph.graph import END, StateGraph

# プロジェクトルートをsys.pathに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.aider_runner import AiderRunError, run_aider

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s %(levelname)s: %(message)s'
)
logger = logging.getLogger("orchestrator_graph")


class ProjectLockManager:
    """
    衛星プロジェクトの排他制御（ロック機構）を管理するクラス
    PM-037 ワーキングツリーの競合を防ぐためのアトミックなロック取得とStale Lock対策
    """
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
    アトミックにマージ更新する (DD-003 §4.1.1)。
    """
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    state_file = metadata_dir / "projects" / project_key / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state_data: Dict[str, Any] = {}
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
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
    actual_round: int = 0,
    history_file: Optional[Path] = None,
) -> None:
    """tools/.cache/execution_history.json へ実行完了・エスカレーション結果を
    アトミックに追記保存する (DD-003 §4.1.1)。
    """
    if history_file is None:
        history_file = Path(__file__).resolve().parent.parent / "tools" / ".cache" / "execution_history.json"
    history_file.parent.mkdir(parents=True, exist_ok=True)

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
        "actual_round": actual_round,
        "max_round": state.get("max_round", 3),
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


def resolve_project_context(project_key: str, metadata_dir: Optional[Path] = None) -> Dict[str, Any]:
    """.project-registry.json からプロジェクトの dir および meta パスを自動解決する (MULTI-001 §2③・§2④・§5)."""
    if metadata_dir is None:
        metadata_dir = Path(__file__).resolve().parent.parent / "metadata"
    registry_file = metadata_dir / ".project-registry.json"

    if not registry_file.exists():
        logger.warning(f"Project registry file {registry_file} does not exist.")
        return {"cwd": None, "target_files": [], "base_branch": "develop"}

    try:
        with open(registry_file, "r", encoding="utf-8") as f:
            registry = json.load(f)
        proj_info = registry.get("projects", {}).get(project_key, {})
        rel_dir = proj_info.get("dir")
        meta_dir = proj_info.get("meta")

        root_dir = Path(__file__).resolve().parent.parent
        cwd = str(root_dir / rel_dir) if rel_dir else None

        base_branch = "develop"
        if meta_dir:
            project_json = root_dir / meta_dir / "project.json"
            if project_json.exists():
                with open(project_json, "r", encoding="utf-8") as pf:
                    pdata = json.load(pf)
                    base_branch = pdata.get("base_branch", "develop")

        return {"cwd": cwd, "target_files": [], "base_branch": base_branch}
    except Exception as e:
        logger.error(f"Failed to resolve project context for {project_key}: {e}")
        return {"cwd": None, "target_files": [], "base_branch": "develop"}


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
    max_round: int
    target_files: List[str]
    instruction: str
    cwd: Optional[str]


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
    ・AiderRunError (タイムアウト) 発生時: LLM_TIMEOUT としてカウンタ加算、1回目は再試行、2回目は FAILED_SYSTEM とする。
    ・False (実行失敗/CLIなし) 返却時: 即座に FAILED_SYSTEM に正規化して終端停止する。
    """
    logger.info("Executing code_node with AiderRunner")
    instruction = state.get("instruction", "Apply edits")
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


def task_decomposition_node(state: GraphState) -> GraphState:
    logger.info("Executing task_decomposition_node")
    from tools.llm_client import call_llm
    call_llm(
        role="planner",
        intent="task_decomposition",
        system_prompt="You are a planner",
        user_prompt=f"Decompose tasks for {state['issue_id']}"
    )
    return state


def task_prioritization_node(state: GraphState) -> GraphState:
    logger.info("Executing task_prioritization_node")
    from tools.llm_client import call_llm
    call_llm(
        role="planner",
        intent="task_prioritization",
        system_prompt="You are a planner",
        user_prompt=f"Prioritize tasks for {state['issue_id']}"
    )
    state["status"] = "COMPLETED"
    return state


def execute_issue(issue_id: str, project_key: str, metadata_dir: Optional[Path] = None) -> None:
    execution_id = uuid.uuid4().hex
    logger.info(f"Starting execution for Issue: {issue_id}, Execution ID: {execution_id}")

    ctx = resolve_project_context(project_key, metadata_dir=metadata_dir)
    cwd = ctx.get("cwd")
    target_files = ctx.get("target_files", [])

    try:
        with ProjectLockManager(project_key, metadata_dir=metadata_dir):
            try:
                logger.info("Setting up context and starting graph execution...")
                workflow = StateGraph(GraphState)
                workflow.add_node("spec_draft", spec_draft_node)
                workflow.add_node("code_node", code_node)
                workflow.add_node("task_decomposition", task_decomposition_node)
                workflow.add_node("task_prioritization", task_prioritization_node)

                workflow.set_entry_point("spec_draft")
                workflow.add_edge("spec_draft", "code_node")

                def route_after_code(s: GraphState) -> str:
                    if s.get("status") == "FAILED_SYSTEM":
                        return END
                    if s.get("status") == "retry_code":
                        return "code_node"
                    return "task_decomposition"

                workflow.add_conditional_edges("code_node", route_after_code, {
                    END: END,
                    "code_node": "code_node",
                    "task_decomposition": "task_decomposition",
                })
                workflow.add_edge("task_decomposition", "task_prioritization")
                workflow.add_edge("task_prioritization", END)

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
                    max_round=3,
                    target_files=target_files,
                    instruction=f"Implement issue {issue_id}",
                    cwd=cwd,
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
                    actual_round=final_state.get("review_round", 0),
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
    parser.add_argument("--issue-id", required=True, help="対象のIssue ID (例: TFG-0004)")
    parser.add_argument("--project-key", required=True, help="対象プロジェクトのキー (例: TFG)")
    args = parser.parse_args()

    execute_issue(args.issue_id, args.project_key)


if __name__ == "__main__":
    main()

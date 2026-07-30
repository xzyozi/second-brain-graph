#!/usr/bin/env python3
"""
orchestrator_graph.py - LangGraph ベースの Issue 実行エントリポイント

Rev.2.7 〜 新アーキテクチャ。
本スクリプトは、日次バッチや人間の /work コマンドから呼び出され、
指定された Issue に対して Graph (plan_node, code_node, etc.) を実行する。
"""

import os
import sys
import time
import logging
import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict
from filelock import FileLock, Timeout
from langgraph.graph import StateGraph, END

# プロジェクトルートをsys.pathに追加
sys.path.insert(0, str(Path(__file__).parent.parent))



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

def write_state(project_key: str, state: Dict[str, Any], filename: str = "state.json") -> None:
    """Graph の状態を原子的に保存する (PM-046).
    
    注意: 状態の世代(generation)を安全にインクリメントするため、
    この関数は必ず ProjectLockManager のロック保有中にのみ呼び出すこと。
    """
    state_file = Path(__file__).resolve().parent.parent / "metadata" / "projects" / project_key / filename
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Load previous state to increment generation if writing state.json
    if filename == "state.json":
        prev_generation = 0
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    prev_state = json.load(f)
                    prev_generation = prev_state.get("generation", 0)
            except Exception:
                pass
        state["generation"] = prev_generation + 1

    temp_file = state_file.with_name(f"{filename}.{uuid.uuid4().hex}.tmp")
    
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        
    os.replace(temp_file, state_file)


def write_event(project_key: str, event_data: Dict[str, Any]) -> None:
    """Graph の状態に影響を与えない個別ファイルイベント記録 (PM-050)"""
    events_dir = Path(__file__).resolve().parent.parent / "metadata" / "projects" / project_key / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    
    execution_id = event_data.get("execution_id", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    event_file = events_dir / f"event_{execution_id}_{timestamp}.json"
    
    with open(event_file, "w", encoding="utf-8") as f:
        json.dump(event_data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

class GraphState(TypedDict):
    issue_id: str
    project_key: str
    execution_id: str
    generation: int
    status: str
    error: Optional[str]

def spec_draft_node(state: GraphState) -> GraphState:
    logger.info("Executing spec_draft_node")
    from tools.llm_client import call_llm
    call_llm(role="planner", intent="spec_draft", system_prompt="You are a planner", user_prompt=f"Draft spec for {state['issue_id']}")
    return state

def task_decomposition_node(state: GraphState) -> GraphState:
    logger.info("Executing task_decomposition_node")
    from tools.llm_client import call_llm
    call_llm(role="planner", intent="task_decomposition", system_prompt="You are a planner", user_prompt=f"Decompose tasks for {state['issue_id']}")
    return state

def task_prioritization_node(state: GraphState) -> GraphState:
    logger.info("Executing task_prioritization_node")
    from tools.llm_client import call_llm
    call_llm(role="planner", intent="task_prioritization", system_prompt="You are a planner", user_prompt=f"Prioritize tasks for {state['issue_id']}")
    state["status"] = "success"
    return state

def execute_issue(issue_id: str, project_key: str) -> None:
    execution_id = uuid.uuid4().hex
    logger.info(f"Starting execution for Issue: {issue_id}, Execution ID: {execution_id}")
    try:
        with ProjectLockManager(project_key):
            try:
                logger.info("Setting up context and starting graph execution...")
                
                logger.info("Initializing Graph nodes...")
                workflow = StateGraph(GraphState)
                workflow.add_node("spec_draft", spec_draft_node)
                workflow.add_node("task_decomposition", task_decomposition_node)
                workflow.add_node("task_prioritization", task_prioritization_node)
                
                workflow.set_entry_point("spec_draft")
                workflow.add_edge("spec_draft", "task_decomposition")
                workflow.add_edge("task_decomposition", "task_prioritization")
                workflow.add_edge("task_prioritization", END)
                
                app = workflow.compile()
                
                initial_state = GraphState(
                    issue_id=issue_id,
                    project_key=project_key,
                    execution_id=execution_id,
                    generation=0,  # will be populated by write_state
                    status="running",
                    error=None
                )
                final_state = app.invoke(initial_state)
                
                write_state(project_key, final_state)
                logger.info(f"Execution completed for Issue: {issue_id}")
                
            except Exception as e:
                logger.error(f"Execution failed for {issue_id}: {e}")
                write_state(project_key, {"status": "FAILED_SYSTEM", "issue_id": issue_id, "execution_id": execution_id, "error": str(e), "timestamp": datetime.now().isoformat()})
            
    except TimeoutError:
        logger.warning(f"Execution skipped for {issue_id} due to lock timeout.")
        write_event(project_key, {"event": "SKIPPED_LOCKED", "issue_id": issue_id, "execution_id": execution_id, "timestamp": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Unexpected error outside lock for {issue_id}: {e}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph Orchestrator")
    parser.add_argument("--issue-id", required=True, help="対象のIssue ID (例: EC-001)")
    parser.add_argument("--project-key", required=True, help="対象プロジェクトのキー (例: EC)")
    args = parser.parse_args()

    execute_issue(args.issue_id, args.project_key)

if __name__ == "__main__":
    main()

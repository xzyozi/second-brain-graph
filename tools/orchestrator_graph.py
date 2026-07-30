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
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict
import json
import os
import uuid
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
    """Graph 実行状態を安全に記録する (PM-037 安全停止ルール準拠)"""
    state_file = Path(__file__).resolve().parent.parent / "metadata" / "projects" / project_key / filename
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.with_name(f"{filename}.{uuid.uuid4().hex}.tmp")
    
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        
    os.replace(temp_file, state_file)


class GraphState(TypedDict):
    issue_id: str
    project_key: str
    status: str
    error: Optional[str]

def execute_issue(issue_id: str, project_key: str) -> None:
    logger.info(f"Starting execution for Issue: {issue_id}")
    try:
        with ProjectLockManager(project_key):
            logger.info("Setting up context and starting graph execution...")
            from tools.llm_client import call_llm
            
            def spec_draft_node(state: GraphState) -> GraphState:
                logger.info("Executing spec_draft_node")
                call_llm(role="planner", intent="spec_draft", system_prompt="You are a planner", user_prompt=f"Draft spec for {state['issue_id']}")
                return state

            def task_decomposition_node(state: GraphState) -> GraphState:
                logger.info("Executing task_decomposition_node")
                call_llm(role="planner", intent="task_decomposition", system_prompt="You are a planner", user_prompt=f"Decompose tasks for {state['issue_id']}")
                return state

            def task_prioritization_node(state: GraphState) -> GraphState:
                logger.info("Executing task_prioritization_node")
                call_llm(role="planner", intent="task_prioritization", system_prompt="You are a planner", user_prompt=f"Prioritize tasks for {state['issue_id']}")
                state["status"] = "success"
                return state
            
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
                status="running",
                error=None
            )
            final_state = app.invoke(initial_state)
            
            write_state(project_key, final_state)
            logger.info(f"Execution completed for Issue: {issue_id}")
    except TimeoutError:
        logger.warning(f"Execution skipped for {issue_id} due to lock timeout.")
        write_state(project_key, {"status": "SKIPPED_LOCKED", "issue_id": issue_id, "timestamp": datetime.now().isoformat()}, filename="skipped.json")
    except Exception as e:
        logger.error(f"Execution failed for {issue_id}: {e}")
        write_state(project_key, {"status": "FAILED_SYSTEM", "issue_id": issue_id, "error": str(e), "timestamp": datetime.now().isoformat()})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph Orchestrator")
    parser.add_argument("--issue-id", required=True, help="対象のIssue ID (例: EC-001)")
    parser.add_argument("--project-key", required=True, help="対象プロジェクトのキー (例: EC)")
    args = parser.parse_args()

    execute_issue(args.issue_id, args.project_key)

if __name__ == "__main__":
    main()

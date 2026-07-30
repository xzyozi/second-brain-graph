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
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

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
        self.stale_timeout_seconds = 7200  # 2時間
        self.owner_token = uuid.uuid4().hex

    def __enter__(self) -> "ProjectLockManager":
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._release_lock()

    def _acquire_lock(self) -> None:
        start_time = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL でアトミックにファイル作成を試みる
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                # ロック取得成功。pid:uuid を書いて閉じる
                with os.fdopen(fd, 'w') as f:
                    f.write(f"{os.getpid()}:{self.owner_token}")
                logger.info(f"Lock acquired for project {self.project_key}")
                return
            except FileExistsError:
                # ロックがすでに存在する場合、Stale Lock かどうか判定
                try:
                    with open(self.lock_file, 'r') as f:
                        content = f.read().strip()
                        if ":" in content:
                            pid_str, _ = content.split(":", 1)
                        else:
                            pid_str = content
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        try:
                            # 自身のプロセスでない、かつ対象のPIDのプロセスが存在するかチェック
                            os.kill(pid, 0)
                        except OSError:
                            # プロセスが存在しない -> Stale Lock
                            logger.warning(f"Stale lock detected for {self.project_key} (PID {pid} is dead). Removing...")
                            self.lock_file.unlink(missing_ok=True)
                            continue
                except Exception as e:
                    logger.debug(f"Error checking lock owner: {e}")
                
                if time.time() - start_time > self.stale_timeout_seconds:
                    raise TimeoutError(f"Failed to acquire project lock for {self.project_key} within timeout.")
                
                logger.info(f"Waiting for lock on project {self.project_key}...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")
                raise

    def _release_lock(self) -> None:
        try:
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()
            
            expected_content = f"{os.getpid()}:{self.owner_token}"
            if content == expected_content:
                self.lock_file.unlink()
                logger.info(f"Lock released for project {self.project_key}")
            else:
                logger.debug(f"Lock for project {self.project_key} is owned by another process. Skipping release.")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")

def write_state(project_key: str, state: Dict[str, Any]) -> None:
    """Graph 実行状態を安全に記録する (PM-037 安全停止ルール準拠)"""
    state_file = Path(__file__).resolve().parent.parent / "metadata" / "projects" / project_key / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def execute_issue(issue_id: str, project_key: str) -> None:
    logger.info(f"Starting execution for Issue: {issue_id}")
    try:
        with ProjectLockManager(project_key):
            logger.info("Setting up context and starting graph execution...")
            from tools.llm_client import call_llm
            
            def spec_draft_node() -> None:
                logger.info("Executing spec_draft_node")
                call_llm(role="planner", intent="spec_draft", system_prompt="You are a planner", user_prompt=f"Draft spec for {issue_id}")

            def task_decomposition_node() -> None:
                logger.info("Executing task_decomposition_node")
                call_llm(role="planner", intent="task_decomposition", system_prompt="You are a planner", user_prompt=f"Decompose tasks for {issue_id}")

            def task_prioritization_node() -> None:
                logger.info("Executing task_prioritization_node")
                call_llm(role="planner", intent="task_prioritization", system_prompt="You are a planner", user_prompt=f"Prioritize tasks for {issue_id}")
            
            logger.info("Initializing Graph nodes...")
            spec_draft_node()
            task_decomposition_node()
            task_prioritization_node()
            
            write_state(project_key, {"status": "success", "issue_id": issue_id})
            logger.info(f"Execution completed for Issue: {issue_id}")
    except Exception as e:
        logger.error(f"Execution failed for {issue_id}: {e}")
        write_state(project_key, {"status": "error", "issue_id": issue_id, "error": str(e), "timestamp": datetime.now().isoformat()})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph Orchestrator")
    parser.add_argument("--issue-id", required=True, help="対象のIssue ID (例: EC-001)")
    parser.add_argument("--project-key", required=True, help="対象プロジェクトのキー (例: EC)")
    args = parser.parse_args()

    execute_issue(args.issue_id, args.project_key)

if __name__ == "__main__":
    main()

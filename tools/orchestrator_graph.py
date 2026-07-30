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
    def __init__(self, project_key: str, metadata_dir: Path = Path("metadata")):
        self.project_key = project_key
        self.lock_dir = metadata_dir / "projects" / project_key
        self.lock_file = self.lock_dir / ".lock"
        self.stale_timeout_seconds = 7200  # 2時間

    def __enter__(self):
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release_lock()

    def _acquire_lock(self):
        start_time = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL でアトミックにファイル作成を試みる
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                # ロック取得成功。pid を書いて閉じる
                with os.fdopen(fd, 'w') as f:
                    f.write(str(os.getpid()))
                logger.info(f"Lock acquired for project {self.project_key}")
                return
            except FileExistsError:
                # ロックがすでに存在する場合、Stale Lock かどうか判定
                try:
                    with open(self.lock_file, 'r') as f:
                        pid_str = f.read().strip()
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

    def _release_lock(self):
        try:
            self.lock_file.unlink()
            logger.info(f"Lock released for project {self.project_key}")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")

# TODO: 今後 build_graph などを実装する
def execute_issue(issue_id: str, project_key: str):
    logger.info(f"Starting execution for Issue: {issue_id}")
    with ProjectLockManager(project_key):
        # ロック取得後の処理
        logger.info("Setting up context and starting graph execution...")
        
        # 将来の実装に向けたグラフ構成のモック
        # 実際には以下のような LangGraph ノードが連携して処理を実行する。
        #
        # def spec_draft_node(state):
        #     # intent: "spec_draft"
        #     call_llm(role="planner", intent="spec_draft", ...)
        #
        # def task_decomposition_node(state):
        #     # intent: "task_decomposition"
        #     call_llm(role="planner", intent="task_decomposition", ...)
        #
        # def task_prioritization_node(state):
        #     # intent: "task_prioritization"
        #     call_llm(role="planner", intent="task_prioritization", ...)
        #
        # def code_node(state):
        #     # intent: "code_edit"
        #     # または Aider
        #     run_aider(..., intent="aider_edit")
        
        logger.info("Initializing Graph... (Dummy)")
        # (ここに Graph の初期化と実行処理が入る)
        time.sleep(1) # mock
            
        logger.info(f"Execution completed for Issue: {issue_id}")


def main():
    parser = argparse.ArgumentParser(description="LangGraph Orchestrator")
    parser.add_argument("--issue-id", required=True, help="対象のIssue ID (例: EC-001)")
    parser.add_argument("--project-key", required=True, help="対象プロジェクトのキー (例: EC)")
    args = parser.parse_args()

    execute_issue(args.issue_id, args.project_key)

if __name__ == "__main__":
    main()

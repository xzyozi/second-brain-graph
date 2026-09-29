#!/usr/bin/env python3
"""tools/nightly_task_worker.py - 自律夜間バッチ（Nightly Task Worker）スクリプト.

外部 TOML 設定ファイル (config/nightly_worker.toml) を読み込み、
サテライトの tasks.md から stage:ready の未着手タスクを優先度順にスキャンし、
設定された上限件数（デフォルト: 1件）のみを安全に自律実装パイプライン (run_task.py) へ投入します。
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

# ロガー設定: 標準出力を汚さないよう sys.stderr に出力（ユーザーグローバルルール準拠）
logger = logging.getLogger("nightly_worker")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(
    logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


@dataclass
class CandidateTask:
    """自律実装候補タスク情報."""

    task_id: str
    project_key: str
    project_name: str
    satellite_dir: Path
    title: str
    priority: str
    score: float
    stage: str
    issue_num: int | None
    line_raw: str


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """CLI 引数をパースする."""
    parser = argparse.ArgumentParser(
        description="自律夜間バッチ（Nightly Task Worker）: stage:ready タスクを優先度順に1件自律実装"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/nightly_worker.toml"),
        help="TOML 設定ファイルのパス（デフォルト: config/nightly_worker.toml）",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="実行最大タスク数（設定ファイルの max_tasks_per_run をオーバーライド）",
    )
    parser.add_argument(
        "--target",
        default="",
        help="対象サテライト名（省略時は設定ファイルの target_projects に準拠）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際のコード実装や PR 作成を行わず、選定タスクのプレビューのみを出力する",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細デバッグログを出力する",
    )
    return parser.parse_args(args)


def load_config(config_path: Path) -> dict[str, Any]:
    """TOML 設定ファイルを読み込む (Python 3.11+ tomllib)."""
    if not config_path.is_file():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")
    with config_path.open("rb") as f:
        return tomllib.load(f)


def load_project_registry(root_dir: Path) -> dict[str, Any]:
    """metadata/.project-registry.json を読み込む."""
    reg_path = root_dir / "metadata" / ".project-registry.json"
    if not reg_path.is_file():
        logger.warning(f"プロジェクトレジストリが見つかりません: {reg_path}")
        return {}
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"レジストリ読み込み失敗: {e}")
        return {}


def parse_tasks_md_candidates(
    tasks_path: Path,
    project_key: str,
    project_name: str,
    satellite_dir: Path,
    require_label: str = "stage:ready",
    skip_blocked: bool = True,
) -> list[CandidateTask]:
    """サテライトの tasks.md から自律実装候補タスクを抽出する."""
    if not tasks_path.is_file():
        return []

    content = tasks_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    task_pattern = re.compile(
        r"^-\s+\[(?P<status>[ x/])\]\s+\[(?P<id>[A-Z0-9_-]+)\]\s+(?P<title>.*?)(?:\s+<!--(?P<comment>.*?)-->)?$"
    )

    candidates: list[CandidateTask] = []
    priority_weights = {"critical": 100.0, "high": 75.0, "medium": 50.0, "low": 25.0}

    for line in lines:
        match = task_pattern.match(line.strip())
        if not match:
            continue

        status = match.group("status")
        # 未着手 [ ] のみ対象 ([x] 完了や [/] 進行中は除外)
        if status != " ":
            continue

        task_id = match.group("id")
        title = match.group("title").strip()
        comment = match.group("comment") or ""

        # コメントメタデータをパース (例: priority:high issue:#109 theme:security stage:ready added:2026-09-29)
        meta: dict[str, str] = {}
        for token in comment.strip().split():
            if ":" in token:
                k, v = token.split(":", 1)
                meta[k.strip().lower()] = v.strip()

        stage = meta.get("stage", "ideation")
        # require_label のチェック (stage:ready のみ対象)
        if (
            require_label
            and stage != require_label.replace("stage:", "")
            and stage != require_label
        ):
            continue

        # ブロッカーチェック
        if skip_blocked and "blockedby" in meta:
            # 他タスク依存がある場合は安全側に倒してスキップ
            continue

        priority = meta.get("priority", "medium").lower()
        score = priority_weights.get(priority, 50.0)

        # 登録日による微小加算 (古いものほど優先度微増)
        if "added" in meta:
            try:
                added_date = datetime.date.fromisoformat(meta["added"])
                days_old = (datetime.date.today() - added_date).days
                score += min(days_old * 0.5, 10.0)
            except Exception:
                pass

        issue_num: int | None = None
        if "issue" in meta:
            clean_issue = meta["issue"].replace("#", "")
            if clean_issue.isdigit():
                issue_num = int(clean_issue)

        candidates.append(
            CandidateTask(
                task_id=task_id,
                project_key=project_key,
                project_name=project_name,
                satellite_dir=satellite_dir,
                title=title,
                priority=priority,
                score=score,
                stage=stage,
                issue_num=issue_num,
                line_raw=line,
            )
        )

    return candidates


def select_best_task(
    candidates: list[CandidateTask],
    max_tasks: int = 1,
) -> list[CandidateTask]:
    """優先度スコア順にソートし、上限件数を抽出する."""
    sorted_candidates = sorted(candidates, key=lambda x: x.score, reverse=True)
    return sorted_candidates[:max_tasks]


def execute_autonomous_task(
    root_dir: Path,
    task: CandidateTask,
    config: dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """run_task.py を呼び出して 1 タスクの自律実装を実行する."""
    exec_cfg = config.get("execution", {})
    auto_stash = exec_cfg.get("auto_stash", True)
    timeout = exec_cfg.get("timeout_seconds", 600)

    logger.info(
        f"【自律実装タスク選定】: [{task.task_id}] {task.title} (スコア: {task.score:.1f}, 優先度: {task.priority})"
    )

    if dry_run:
        logger.info(f"[DRY-RUN] タスク {task.task_id} の自律実装をシミュレート（実行スキップ）")
        return True

    cmd = [
        sys.executable,
        str(root_dir / "tools" / "run_task.py"),
        task.task_id,
    ]
    if auto_stash:
        cmd.append("--auto-stash")

    logger.info(f"自律実装パイプラインを起動中: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=root_dir,
            timeout=timeout,
            check=False,
        )
        if proc.returncode == 0:
            logger.info(f"タスク {task.task_id} の自律実装が正常完了しました！")
            return True
        else:
            logger.error(
                f"タスク {task.task_id} の自律実装がエラー終了しました (exit code {proc.returncode})"
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"タスク {task.task_id} の自律実装がタイムアウトしました ({timeout}s)")
        return False
    except Exception as e:
        logger.error(f"タスク {task.task_id} の自律実装実行中に例外が発生しました: {e}")
        return False


def main(args: list[str] | None = None) -> int:
    """メイン実行フロー."""
    opts = parse_args(args)
    if opts.verbose:
        logger.setLevel(logging.DEBUG)

    root_dir = Path(__file__).resolve().parents[1]
    config_path = (
        (root_dir / opts.config).resolve() if not opts.config.is_absolute() else opts.config
    )

    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error(f"設定ファイルのロードに失敗しました: {e}")
        return 1

    # 1. 有効フラグのチェック
    if not config.get("enabled", True):
        logger.info("設定ファイルで enabled = false が指定されているため、バッチを停止します。")
        return 0

    # 2. 上限タスク数の決定
    max_tasks = opts.max_tasks if opts.max_tasks is not None else config.get("max_tasks_per_run", 1)
    logger.info(f"自律夜間バッチ起動: 最大実行タスク数 = {max_tasks} 件")

    # 3. 対象プロジェクトの選定
    registry = load_project_registry(root_dir)
    registered_projects = registry.get("projects", {})
    cfg_targets = config.get("target_projects", ["all"])

    selected_projects: dict[str, Any] = {}
    if opts.target:
        # CLI で個別指定された場合
        for k, v in registered_projects.items():
            if v.get("name") == opts.target or k == opts.target:
                selected_projects[k] = v
                break
    elif "all" in cfg_targets:
        selected_projects = registered_projects
    else:
        for k, v in registered_projects.items():
            if v.get("name") in cfg_targets or k in cfg_targets:
                selected_projects[k] = v

    if not selected_projects:
        logger.warning("対象となるサテライトプロジェクトが見つかりませんでした。")
        return 0

    # 4. タスク選定基準
    task_sel_cfg = config.get("task_selection", {})
    require_label = task_sel_cfg.get("require_label", "stage:ready")
    skip_blocked = task_sel_cfg.get("skip_blocked", True)

    # 5. 全対象サテライトから候補タスクを収集
    all_candidates: list[CandidateTask] = []
    for proj_key, proj_info in selected_projects.items():
        sat_name = proj_info.get("name", "")
        sat_rel_dir = proj_info.get("dir", "")
        sat_dir = root_dir / sat_rel_dir
        tasks_path = sat_dir / "docs" / "tasks.md"

        candidates = parse_tasks_md_candidates(
            tasks_path=tasks_path,
            project_key=proj_key,
            project_name=sat_name,
            satellite_dir=sat_dir,
            require_label=require_label,
            skip_blocked=skip_blocked,
        )
        all_candidates.extend(candidates)

    logger.info(f"スキャン完了: 実装候補タスク ({require_label}) = {len(all_candidates)} 件")

    if not all_candidates:
        logger.info("実行可能な stage:ready タスクはありませんでした。安全に終了します。")
        return 0

    # 6. 最優先タスクの選定
    tasks_to_execute = select_best_task(all_candidates, max_tasks=max_tasks)

    # 7. 自律実装の実行
    success_count = 0
    for task in tasks_to_execute:
        ok = execute_autonomous_task(root_dir, task, config, dry_run=opts.dry_run)
        if ok:
            success_count += 1

    logger.info(
        f"自律夜間バッチ終了: {success_count}/{len(tasks_to_execute)} 件完了 (dry_run={opts.dry_run})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

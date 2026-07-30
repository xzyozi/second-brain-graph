#!/usr/bin/env python3
"""
score-issues.py  ―  Layer 2 / Step 1
roadmap.md を解析し、4軸スコアを計算して priority-cache.json に書き出す。
LLM を一切使用しない決定的スクリプト。

使い方:
  uv run python tools/score-issues.py [--roadmap roadmap.md] [--out tools/.cache/priority-cache.json]
"""

import re
import json
import argparse
import datetime
import sys
from pathlib import Path
import os
import logging
# プロジェクトのルートディレクトリをインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.task_parser import parse_roadmap_file, parse_tasks_file as parser_parse_tasks

# loggerの設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("score-issues")

# ── スコア重み ──────────────────────────────────────────────────
WEIGHTS = {"P": 3.0, "F": 2.0, "E": 1.5, "D": 2.0}
MAX_SCORE = sum(5 * w for w in WEIGHTS.values())   # 42.5

# ── 優先度ラベル → 数値 ──────────────────────────────────────────
PRIORITY_MAP = {
    "critical": 5, "urgent": 5,
    "high":     4,
    "medium":   3, "med": 3,
    "low":      2,
    "none":     1,
}

# ── 工数見積もり → h 換算 ─────────────────────────────────────────
def parse_effort_hours(block: str) -> float:
    """estimate: 2h / 1d / 30m などを時間に変換する"""
    m = re.search(r"estimate:\s*(\d+(?:\.\d+)?)\s*([mhd])", block, re.IGNORECASE)
    if not m:
        return 8.0   # デフォルト1日
    val, unit = float(m.group(1)), m.group(2).lower()
    if unit == "m":  return val / 60
    if unit == "h":  return val
    if unit == "d":  return val * 8
    return 8.0

def effort_score(hours: float) -> int:
    if hours <= 1:   return 5
    if hours <= 4:   return 4
    if hours <= 8:   return 3
    if hours <= 16:  return 2
    return 1

# ── 鮮度スコア ───────────────────────────────────────────────────
def freshness_score(block: str) -> int:
    m = re.search(r"updated:\s*(\d{4}-\d{2}-\d{2})", block)
    if not m:
        return 1   # 日付なし → 陳腐と見なす
    days = (datetime.date.today() - datetime.date.fromisoformat(m.group(1))).days
    if days <= 7:   return 5
    if days <= 30:  return 3
    if days <= 90:  return 1
    return 0

# ── 依存スコア ───────────────────────────────────────────────────
def dependency_score(block: str) -> int:
    deps = len(re.findall(r"blockedby:\s*#?[A-Z0-9\-]+", block, re.IGNORECASE))
    if deps == 0: return 5
    if deps == 1: return 3
    if deps == 2: return 1
    return 0

# ── Issueパーサ ──────────────────────────────────────────────────
def parse_issues(text: str) -> list[dict]:
    """
    roadmap.md をパースし、スコアを計算してリストを返す
    """
    task_items = parse_roadmap_file(text)
    issues = []
    for item in task_items:
        # status と blockedby を辞書に追加して後でフィルタリングできるようにする
        # status は parser_parse_tasks 側で "in-progress" か "open" に統一されるが
        # ここでは生データも残しておく
        status = item.status
        blockedby = re.findall(r"blockedby:\s*#?([A-Z0-9\-]+)", item.raw_content, re.IGNORECASE)
            
        P = PRIORITY_MAP.get(item.priority.lower(), 1)
        
        # freshness_score は raw_content (ブロック全体) から計算
        F = freshness_score(item.raw_content)
        # effort_score も同様
        E = effort_score(parse_effort_hours(item.raw_content))
        # dependency_score も同様
        D = dependency_score(item.raw_content)
        
        total = P * WEIGHTS["P"] + F * WEIGHTS["F"] + E * WEIGHTS["E"] + D * WEIGHTS["D"]
        score = round(total / MAX_SCORE * 100, 1)
        
        # タグ抽出 (raw_content から)
        tags = re.findall(r"#(\w+)", item.raw_content)
        tags = [t for t in tags if not t.isdigit()]
        
        issues.append({
            "id":    item.id,
            "title": item.title,
            "status": status,
            "blockedby": blockedby,
            "score": score,
            "axes":  {"P": P, "F": F, "E": E, "D": D},
            "raw_total": round(total, 2),
            "tags":  tags[:5],
        })
        
    issues.sort(key=lambda x: x["score"], reverse=True)
    return issues


def parse_tasks_file(text: str, project_key: str, project_name: str) -> list[dict]:
    """
    tasks.md のパースとスコアリング
    """
    task_items = parser_parse_tasks(text, project_key, project_name)
    issues = []
    for item in task_items:
            
        # status を score-issues.py 側で使う形式 "in-progress" / "open" に統一
        status = "in-progress" if item.status == "in-progress" else "open"
        
        priority = item.priority
        estimate = item.estimate
        updated = item.updated
        
        extra_lines = []
        for b in item.blockedby:
            dep = b if b.startswith("#") else f"#{b}"
            extra_lines.append(f"- blockedby: {dep}")
        for blocker in item.extra_blockers:
            extra_lines.append(f"- {blocker}: info")
            
        block_text = f"## [{item.id}] {item.title}\n"
        block_text += f"- status: {status}\n"
        block_text += f"- priority-{priority}\n"
        if estimate:
            block_text += f"- estimate: {estimate}\n"
        if updated:
            block_text += f"- updated: {updated}\n"
        for extra in extra_lines:
            block_text += f"{extra}\n"
            
        parsed_list = parse_issues(block_text)
        if parsed_list:
            res_item = parsed_list[0]
            res_item["project"] = project_name
            if item.parent:
                res_item["parent"] = item.parent
            issues.append(res_item)
            
    return issues


def main():
    parser = argparse.ArgumentParser(description="Issue スコアリング（Layer 2 / Step 1）")
    parser.add_argument("--roadmap", default="roadmap.md")
    parser.add_argument("--out",     default="tools/.cache/priority-cache.json")
    args = parser.parse_args()

    all_issues = []

    # 1. 母艦 roadmap.md のパース
    roadmap_path = Path(args.roadmap)
    if roadmap_path.exists():
        text = roadmap_path.read_text(encoding="utf-8")
        issues = parse_issues(text)
        for i in issues:
            i["project"] = "core"
        all_issues.extend(issues)
    else:
        logger.warning(f"roadmap.md が見つかりません: {roadmap_path}")

    # 2. 衛星プロジェクトのパース
    projects_dir = Path("projects")
    if projects_dir.exists():
        for proj_json_path in sorted(projects_dir.glob("*/project.json")):
            try:
                proj_meta = json.loads(proj_json_path.read_text(encoding="utf-8"))
                proj_key = proj_meta.get("key", "")
                proj_name = proj_json_path.parent.name
                
                tasks_path = proj_json_path.parent / "tasks.md"
                if tasks_path.exists():
                    tasks_text = tasks_path.read_text(encoding="utf-8")
                    proj_issues = parse_tasks_file(tasks_text, proj_key, proj_name)
                    all_issues.extend(proj_issues)
            except Exception as e:
                logger.error(f"プロジェクト {proj_json_path.parent.name} の解析失敗: {e}")

    # 3. フィルタリングフェーズ (Pre-filtering)
    # まず全Issueのステータスマップを作成
    status_map = { issue["id"]: issue["status"] for issue in all_issues }
    
    actionable_issues = []
    for issue in all_issues:
        if issue["status"] in ["done", "closed", "cancelled"]:
            continue
            
        # 未完了のブロッカーがあるかチェック
        is_blocked = False
        for blocker_id in issue.get("blockedby", []):
            blocker_status = status_map.get(blocker_id, "unknown")
            if blocker_status not in ["done", "closed", "cancelled"]:
                logger.info(f"[SKIPPED] {issue['id']}: 依存先 {blocker_id} (状態: {blocker_status}) が未完了のため")
                is_blocked = True
                break
                
        if not is_blocked:
            actionable_issues.append(issue)

    # 全プロジェクト横断でソート
    actionable_issues.sort(key=lambda x: x["score"], reverse=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 成果物から不要な一時フィールド (status, blockedby) を削除して書き出す
    final_issues = []
    for issue in actionable_issues:
        clean_issue = issue.copy()
        clean_issue.pop("status", None)
        clean_issue.pop("blockedby", None)
        final_issues.append(clean_issue)

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total":        len(final_issues),
        "issues":       final_issues,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    logger.info(f"{len(final_issues)} issues scored (total parsed: {len(all_issues)}) → {out_path}")
    for i in final_issues[:10]:
        axes = i["axes"]
        proj_str = f"[{i['project']}]"
        logger.info(f"  #{i['id']:<8} {proj_str:<12} score={i['score']:>5}  "
                    f"P={axes['P']} F={axes['F']} E={axes['E']} D={axes['D']}  {i['title'][:40]}")


if __name__ == "__main__":
    main()

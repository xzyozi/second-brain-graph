"""Score Issues Batch Tool.

Scans all satellite project metadata using metadata/.project-registry.json,
filters out blocked issues (PM-039), calculates 4-axis scores (P, F, E, D),
and saves the result to tools/.cache/priority-cache.json.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_registry(root_dir: str = ".") -> Dict[str, Any]:
    """Load project registry from metadata/.project-registry.json."""
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
    if not os.path.exists(reg_path):
        logger.warning(f"Registry file not found at: {reg_path}")
        return {}
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("projects", {})
    except Exception as e:
        logger.error(f"Failed to read project registry {reg_path}: {e}")
        return {}


def parse_metadata_comment(comment_str: str) -> Dict[str, str]:
    """Parse HTML comment metadata, e.g. <!-- priority:high added:2026-07-12 blockedby:TFG-0001 estimate:4h -->."""
    meta: Dict[str, str] = {}
    tokens = comment_str.strip().split()
    for token in tokens:
        if ":" in token:
            k, v = token.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def parse_tasks_md(tasks_path: str, project_key: str) -> List[Dict[str, Any]]:
    """Parse a satellite's tasks.md file and return issue dictionaries."""
    if not os.path.exists(tasks_path):
        return []

    issues: List[Dict[str, Any]] = []
    task_pattern = re.compile(
        r"^-\s+\[(?P<status>[ x/])\]\s+\[(?P<id>[A-Z0-9_-]+)\]\s+(?P<title>.*?)(?:\s+<!--(?P<comment>.*?)-->)?$"
    )

    with open(tasks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            match = task_pattern.match(line)
            if not match:
                continue

            raw_status = match.group("status")
            issue_id = match.group("id")
            title = match.group("title").strip()
            comment = match.group("comment") or ""

            meta = parse_metadata_comment(comment)

            is_completed = raw_status == "x"
            is_in_progress = raw_status == "/"

            blockedby_raw = meta.get("blockedby", "")
            blockedby_list = (
                [b.strip() for b in blockedby_raw.split(",") if b.strip()] if blockedby_raw else []
            )

            issues.append(
                {
                    "id": issue_id,
                    "project_key": project_key,
                    "title": title,
                    "completed": is_completed,
                    "in_progress": is_in_progress,
                    "priority": meta.get("priority", "medium"),
                    "added": meta.get("added"),
                    "estimate": meta.get("estimate"),
                    "blockedby": blockedby_list,
                }
            )

    return issues


def calculate_freshness_score(added_str: Optional[str]) -> float:
    """Calculate freshness score F (0..5)."""
    if not added_str:
        return 5.0

    try:
        added_dt = datetime.strptime(added_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        days = (now_dt - added_dt).days

        if days <= 7:
            return 5.0
        elif days <= 30:
            return 3.0
        elif days <= 90:
            return 1.0
        else:
            return 0.0
    except ValueError:
        return 5.0


def calculate_estimate_score(estimate_str: Optional[str]) -> float:
    """Calculate estimate score E (1..5)."""
    if not estimate_str:
        return 3.0

    m = re.search(r"(\d+(\.\d+)?)", estimate_str)
    if not m:
        return 3.0

    hours = float(m.group(1))
    if hours <= 1.0:
        return 5.0
    elif hours <= 4.0:
        return 4.0
    elif hours <= 8.0:
        return 3.0
    elif hours <= 16.0:
        return 2.0
    else:
        return 1.0


def calculate_priority_score(priority_str: str) -> float:
    """Calculate priority score P (1..5)."""
    p = priority_str.lower()
    if p in ("critical", "urgent"):
        return 5.0
    elif p == "high":
        return 4.0
    elif p == "medium":
        return 3.0
    elif p == "low":
        return 2.0
    else:
        return 1.0


def calculate_issue_score(issue: Dict[str, Any]) -> float:
    """Calculate 4-axis total score (0..100)."""
    p_val = calculate_priority_score(issue.get("priority", "medium"))
    f_val = calculate_freshness_score(issue.get("added"))
    e_val = calculate_estimate_score(issue.get("estimate"))

    blockers = issue.get("blockedby", [])
    num_blockers = len(blockers)
    if num_blockers == 0:
        d_val = 5.0
    elif num_blockers == 1:
        d_val = 3.0
    elif num_blockers == 2:
        d_val = 1.0
    else:
        d_val = 0.0

    total = (p_val * 3.0) + (f_val * 2.0) + (e_val * 1.5) + (d_val * 2.0)
    score = round((total / 42.5) * 100.0, 1)
    return score


def process_scoring(root_dir: str = ".") -> List[Dict[str, Any]]:
    """Scan all projects, filter out completed and blocked issues, calculate score."""
    projects = load_registry(root_dir)

    # Map of issue_id -> completed status
    completed_map: Dict[str, bool] = {}

    project_issues_list: List[Tuple[str, str, List[Dict[str, Any]]]] = []

    for project_key, info in projects.items():
        project_dir = info.get("dir", f"projects/{project_key}")
        meta_dir = info.get("meta", os.path.join("metadata", "projects", project_key))
        # サテライト側 (projects/<name>/docs/tasks.md) を最優先し、存在しない場合は母艦側 (metadata/projects/<KEY>/tasks.md) をフォールバック
        satellite_tasks = os.path.join(root_dir, project_dir, "docs", "tasks.md")
        fallback_tasks = os.path.join(root_dir, meta_dir, "tasks.md")
        tasks_path = satellite_tasks if os.path.exists(satellite_tasks) else fallback_tasks

        issues = parse_tasks_md(tasks_path, project_key)
        for iss in issues:
            iss["project_dir"] = project_dir
            completed_map[iss["id"]] = iss["completed"]

        project_issues_list.append((project_key, project_dir, issues))

    candidate_issues: List[Dict[str, Any]] = []

    for _project_key, _project_dir, issues in project_issues_list:
        for issue in issues:
            # Skip completed issues
            if issue["completed"]:
                continue

            # PM-039: Check for incomplete blockers
            blockers = issue.get("blockedby", [])
            uncompleted_blockers = [b for b in blockers if not completed_map.get(b, False)]

            if uncompleted_blockers:
                logger.info(
                    f"[SKIPPED] Issue {issue['id']} is skipped because it is blocked by uncompleted tasks: {uncompleted_blockers}"
                )
                continue

            score = calculate_issue_score(issue)
            candidate_issues.append(
                {
                    "id": issue["id"],
                    "project_key": issue["project_key"],
                    "project_dir": issue["project_dir"],
                    "score": score,
                    "title": issue["title"],
                    "priority": issue["priority"],
                    "blockedby": issue["blockedby"],
                }
            )

    candidate_issues.sort(key=lambda x: x["score"], reverse=True)
    return candidate_issues


def save_to_cache(candidates: List[Dict[str, Any]], root_dir: str = ".") -> str:
    """Save candidates to priority-cache.json."""
    cache_dir = os.path.join(root_dir, "tools", ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "priority-cache.json")

    tmp_path = cache_path + ".tmp"
    output_data = {"issues": candidates}

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    os.replace(tmp_path, cache_path)
    logger.info(f"Successfully saved {len(candidates)} scored issues to {cache_path}")
    return cache_path


def main() -> None:
    """Main execution function."""
    candidates = process_scoring(root_dir=".")
    save_to_cache(candidates, root_dir=".")


if __name__ == "__main__":
    main()

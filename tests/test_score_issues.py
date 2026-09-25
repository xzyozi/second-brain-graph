"""Tests for tools/score_issues.py."""

import json
import os
from typing import Any, Dict

import pytest

from tools.score_issues import (
    calculate_estimate_score,
    calculate_freshness_score,
    calculate_issue_score,
    calculate_priority_score,
    parse_metadata_comment,
    process_scoring,
    save_to_cache,
)


def test_parse_metadata_comment() -> None:
    comment = " priority:high added:2026-07-12 blockedby:TFG-0001 estimate:4h "
    meta = parse_metadata_comment(comment)
    assert meta["priority"] == "high"
    assert meta["added"] == "2026-07-12"
    assert meta["blockedby"] == "TFG-0001"
    assert meta["estimate"] == "4h"


def test_calculate_scores() -> None:
    assert calculate_priority_score("critical") == 5.0
    assert calculate_priority_score("high") == 4.0
    assert calculate_priority_score("medium") == 3.0
    assert calculate_priority_score("low") == 2.0

    assert calculate_estimate_score("1h") == 5.0
    assert calculate_estimate_score("4h") == 4.0
    assert calculate_estimate_score("8h") == 3.0
    assert calculate_estimate_score("16h") == 2.0
    assert calculate_estimate_score("24h") == 1.0
    assert calculate_estimate_score(None) == 3.0

    assert calculate_freshness_score(None) == 5.0


def test_calculate_issue_score() -> None:
    issue: Dict[str, Any] = {
        "priority": "high",  # P=4
        "added": None,  # F=5
        "estimate": "4h",  # E=4
        "blockedby": [],  # D=5
    }
    # Total = (4*3.0) + (5*2.0) + (4*1.5) + (5*2.0) = 12 + 10 + 6 + 10 = 38
    # Score = (38 / 42.5) * 100 = 89.41... -> 89.4
    score = calculate_issue_score(issue)
    assert score == 89.4


def test_process_scoring_and_pm039_blocker_filtering(tmp_path: pytest.TempPathFactory) -> None:
    root_dir = str(tmp_path)

    meta_dir = os.path.join(root_dir, "metadata", "projects", "TEST")
    os.makedirs(meta_dir, exist_ok=True)

    tasks_content = (
        "# Tasks\n"
        "- [x] [TEST-0001] Base task completed <!-- priority:high -->\n"
        "- [ ] [TEST-0002] Blocked by incomplete task <!-- priority:critical blockedby:TEST-0003 -->\n"
        "- [ ] [TEST-0003] Independent task <!-- priority:high -->\n"
        "- [ ] [TEST-0004] Blocked by completed task <!-- priority:medium blockedby:TEST-0001 -->\n"
    )
    with open(os.path.join(meta_dir, "tasks.md"), "w", encoding="utf-8") as f:
        f.write(tasks_content)

    reg_dir = os.path.join(root_dir, "metadata")
    os.makedirs(reg_dir, exist_ok=True)
    registry_data = {
        "version": "1.0",
        "projects": {
            "TEST": {
                "name": "Test Project",
                "dir": "projects/test",
                "meta": "metadata/projects/TEST",
            }
        },
    }
    with open(os.path.join(reg_dir, ".project-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry_data, f)

    candidates = process_scoring(root_dir=root_dir)

    candidate_ids = [c["id"] for c in candidates]

    # TEST-0001: Completed -> Excluded
    assert "TEST-0001" not in candidate_ids
    # TEST-0002: Blocked by uncompleted TEST-0003 -> Excluded (PM-039)
    assert "TEST-0002" not in candidate_ids
    # TEST-0003: Unblocked -> Included
    assert "TEST-0003" in candidate_ids
    # TEST-0004: Blocked by completed TEST-0001 -> Included
    assert "TEST-0004" in candidate_ids

    # Check cache saving
    cache_path = save_to_cache(candidates, root_dir=root_dir)
    assert os.path.exists(cache_path)
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data["issues"]) == len(candidates)


def test_process_scoring_prioritizes_satellite_tasks_md(tmp_path: pytest.TempPathFactory) -> None:
    """Issue #45: サテライト側の docs/tasks.md が母艦側の tasks.md より優先して読み込まれることを確認する。"""
    root_dir = str(tmp_path)

    # 1. 母艦側の tasks.md（古いタスク）
    meta_dir = os.path.join(root_dir, "metadata", "projects", "TEST")
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, "tasks.md"), "w", encoding="utf-8") as f:
        f.write("- [ ] [TEST-0001] Old host task <!-- priority:low -->\n")

    # 2. サテライト側の docs/tasks.md（最新タスク）
    satellite_docs = os.path.join(root_dir, "projects", "test", "docs")
    os.makedirs(satellite_docs, exist_ok=True)
    with open(os.path.join(satellite_docs, "tasks.md"), "w", encoding="utf-8") as f:
        f.write("- [ ] [TEST-0002] Satellite prioritized task <!-- priority:critical -->\n")

    reg_dir = os.path.join(root_dir, "metadata")
    os.makedirs(reg_dir, exist_ok=True)
    registry_data = {
        "version": "1.0",
        "projects": {
            "TEST": {
                "name": "Test Project",
                "dir": "projects/test",
                "meta": "metadata/projects/TEST",
            }
        },
    }
    with open(os.path.join(reg_dir, ".project-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry_data, f)

    candidates = process_scoring(root_dir=root_dir)
    candidate_ids = [c["id"] for c in candidates]

    # サテライト側の tasks.md が読まれているため TEST-0002 のみが候補になり、TEST-0001 は含まれない
    assert "TEST-0002" in candidate_ids
    assert "TEST-0001" not in candidate_ids


def test_process_scoring_skips_ideation_tasks(tmp_path: pytest.TempPathFactory) -> None:
    """stage:ideation メタデータが付いたタスクが除外されることを確認する。"""
    root_dir = str(tmp_path)

    meta_dir = os.path.join(root_dir, "metadata", "projects", "TEST")
    os.makedirs(meta_dir, exist_ok=True)

    tasks_content = (
        "# Tasks\n"
        "- [ ] [TEST-0001] Ready task <!-- priority:high stage:ready -->\n"
        "- [ ] [TEST-0002] Ideation task <!-- priority:high stage:ideation -->\n"
        "- [ ] [TEST-0003] Draft task <!-- priority:critical stage:draft -->\n"
    )
    with open(os.path.join(meta_dir, "tasks.md"), "w", encoding="utf-8") as f:
        f.write(tasks_content)

    reg_dir = os.path.join(root_dir, "metadata")
    os.makedirs(reg_dir, exist_ok=True)
    registry_data = {
        "version": "1.0",
        "projects": {
            "TEST": {
                "name": "Test Project",
                "dir": "projects/test",
                "meta": "metadata/projects/TEST",
            }
        },
    }
    with open(os.path.join(reg_dir, ".project-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry_data, f)

    candidates = process_scoring(root_dir=root_dir)
    candidate_ids = [c["id"] for c in candidates]

    assert "TEST-0001" in candidate_ids
    assert "TEST-0002" not in candidate_ids
    assert "TEST-0003" not in candidate_ids

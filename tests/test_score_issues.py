"""Tests for tools/score_issues.py."""

import json
import os
from typing import Any, Dict

from tools.score_issues import (
    calculate_estimate_score,
    calculate_freshness_score,
    calculate_issue_score,
    calculate_priority_score,
    parse_metadata_comment,
    process_scoring,
    save_to_cache,
)
from tools.workspace.github_issues import use_issue_fixture


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


def test_process_scoring_and_pm039_blocker_filtering(tmp_path: Any) -> None:
    """tasks.md なしで GitHub Issues SSOT (フィクスチャ) からスコアリング・PM-039除外できること."""
    root_dir = str(tmp_path)
    reg_dir = os.path.join(root_dir, "metadata")
    os.makedirs(reg_dir, exist_ok=True)
    registry_data = {
        "version": "1.0",
        "projects": {
            "TEST": {
                "name": "Test Project",
                "github_repo": "xzyozi/test_project",
                "dir": "projects/test",
                "meta": "metadata/projects/TEST",
            }
        },
    }
    with open(os.path.join(reg_dir, ".project-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry_data, f)

    fixture_issues = {
        "xzyozi/test_project": [
            {
                "number": 1,
                "title": "Base task completed",
                "body": "<!-- priority:high -->",
                "state": "CLOSED",
                "labels": [{"name": "stage:done"}],
            },
            {
                "number": 2,
                "title": "Blocked by incomplete task",
                "body": "Depends on: #3\n<!-- priority:critical -->",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}, {"name": "priority:critical"}],
            },
            {
                "number": 3,
                "title": "Independent task",
                "body": "",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}, {"name": "priority:high"}],
            },
            {
                "number": 4,
                "title": "Blocked by completed task",
                "body": "<!-- priority:medium blockedby:TEST-0001 -->",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}],
            },
        ]
    }

    with use_issue_fixture(fixture_issues):
        candidates = process_scoring(root_dir=root_dir)

    candidate_ids = [c["id"] for c in candidates]

    # TEST-0001: Completed (CLOSED) -> Excluded
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


def test_process_scoring_skips_ideation_and_in_progress_tasks(tmp_path: Any) -> None:
    """stage:ideation / stage:in-progress / on-hold ラベル付き Issue が除外されることを確認する。"""
    root_dir = str(tmp_path)
    reg_dir = os.path.join(root_dir, "metadata")
    os.makedirs(reg_dir, exist_ok=True)
    registry_data = {
        "version": "1.0",
        "projects": {
            "TEST": {
                "name": "Test Project",
                "github_repo": "xzyozi/test_project",
                "dir": "projects/test",
                "meta": "metadata/projects/TEST",
            }
        },
    }
    with open(os.path.join(reg_dir, ".project-registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry_data, f)

    fixture_issues = {
        "xzyozi/test_project": [
            {
                "number": 1,
                "title": "Ready task",
                "body": "",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}, {"name": "priority:high"}],
            },
            {
                "number": 2,
                "title": "Ideation task",
                "body": "",
                "state": "OPEN",
                "labels": [{"name": "stage:ideation"}, {"name": "priority:high"}],
            },
            {
                "number": 3,
                "title": "In progress task",
                "body": "",
                "state": "OPEN",
                "labels": [{"name": "stage:in-progress"}, {"name": "priority:critical"}],
            },
            {
                "number": 4,
                "title": "On hold task",
                "body": "",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}, {"name": "on-hold"}],
            },
        ]
    }

    with use_issue_fixture(fixture_issues):
        candidates = process_scoring(root_dir=root_dir)
    candidate_ids = [c["id"] for c in candidates]

    assert candidate_ids == ["TEST-0001"]

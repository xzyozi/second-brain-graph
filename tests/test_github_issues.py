"""tests/test_github_issues.py - github_issues 共通取得層・モックフィクスチャ機構の単体テスト."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.workspace.github_issues import (
    FIXTURE_ENV_VAR,
    extract_issue_scoring_metadata,
    extract_label_names,
    extract_stage_label,
    fetch_remote_issue,
    fetch_remote_issues,
    normalize_issue_record,
    set_issue_fixture_data,
    use_issue_fixture,
)


def test_legacy_tools_alias_import() -> None:
    """tools.github_issues エイリアスから同一モジュールをインポートできる."""
    import tools.github_issues as alias_mod
    import tools.workspace.github_issues as canonical_mod

    assert alias_mod.fetch_remote_issue is canonical_mod.fetch_remote_issue
    assert alias_mod.fetch_remote_issues is canonical_mod.fetch_remote_issues


def test_extract_label_names_and_stage() -> None:
    issue_dicts = {
        "labels": [{"name": "enhancement"}, {"name": "stage:ready"}],
    }
    assert extract_label_names(issue_dicts) == ["enhancement", "stage:ready"]
    assert extract_stage_label(issue_dicts) == "stage:ready"

    issue_strs = {"labels": ["bug", "stage:in-progress"]}
    assert extract_label_names(issue_strs) == ["bug", "stage:in-progress"]
    assert extract_stage_label(issue_strs) == "stage:in-progress"

    assert extract_stage_label({"labels": [{"name": "enhancement"}]}) is None


def test_normalize_issue_record_with_project_key() -> None:
    raw = {
        "number": 5,
        "title": "テスト機能追加",
        "body": "## Target Files\n- `src/app.py`",
        "state": "open",
        "labels": [{"name": "stage:ready"}, {"name": "priority:high"}],
        "url": "https://github.com/org/repo/issues/5",
    }
    norm = normalize_issue_record(raw, project_key="tfg")
    assert norm["number"] == 5
    assert norm["state"] == "OPEN"
    assert norm["label_names"] == ["stage:ready", "priority:high"]
    assert norm["stage"] == "stage:ready"
    assert norm["task_id"] == "TFG-0005"


def test_use_issue_fixture_list_and_filtering() -> None:
    fixture = [
        {
            "number": 1,
            "title": "Ready issue",
            "body": "body1",
            "state": "OPEN",
            "labels": [{"name": "stage:ready"}, {"name": "enhancement"}],
        },
        {
            "number": 2,
            "title": "Ideation issue",
            "body": "body2",
            "state": "OPEN",
            "labels": [{"name": "stage:ideation"}],
        },
        {
            "number": 3,
            "title": "Closed ready-like",
            "body": "body3",
            "state": "CLOSED",
            "labels": [{"name": "stage:ready"}],
        },
    ]

    with use_issue_fixture(fixture):
        ready_open = fetch_remote_issues(
            "xzyozi/sample",
            state="open",
            labels=["stage:ready"],
            project_key="SMP",
        )
        assert len(ready_open) == 1
        assert ready_open[0]["number"] == 1
        assert ready_open[0]["task_id"] == "SMP-0001"
        assert ready_open[0]["stage"] == "stage:ready"

        single = fetch_remote_issue("xzyozi/sample", 2, project_key="SMP")
        assert single is not None
        assert single["task_id"] == "SMP-0002"
        assert single["stage"] == "stage:ideation"

        missing = fetch_remote_issue("xzyozi/sample", 999)
        assert missing is None


def test_use_issue_fixture_repo_map_and_cleanup() -> None:
    repo_map = {
        "org/repo-a": [{"number": 10, "title": "Repo A", "state": "OPEN", "labels": []}],
        "*": [{"number": 20, "title": "Fallback", "state": "OPEN", "labels": []}],
    }
    try:
        set_issue_fixture_data(repo_map)
        res_a = fetch_remote_issues("org/repo-a")
        assert [item["number"] for item in res_a] == [10]

        res_b = fetch_remote_issues("org/repo-b")
        assert [item["number"] for item in res_b] == [20]
    finally:
        set_issue_fixture_data(None)


def test_env_fixture_json_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_file = tmp_path / "issues.json"
    fixture_file.write_text(
        json.dumps(
            {
                "xzyozi/tfg": [
                    {
                        "number": 7,
                        "title": "Env Fixture Task",
                        "body": "body",
                        "state": "OPEN",
                        "labels": [{"name": "stage:ready"}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(FIXTURE_ENV_VAR, str(fixture_file))

    with patch("tools.workspace.github_issues.subprocess.run") as mock_run:
        items = fetch_remote_issues("xzyozi/tfg", state="open", project_key="TFG")
        assert len(items) == 1
        assert items[0]["task_id"] == "TFG-0007"
        detail = fetch_remote_issue("xzyozi/tfg", 7, normalize=True)
        assert detail is not None
        assert detail["stage"] == "stage:ready"
        mock_run.assert_not_called()


def test_env_fixture_missing_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FIXTURE_ENV_VAR, str(tmp_path / "nonexistent.json"))
    with patch("tools.workspace.github_issues.subprocess.run") as mock_run:
        assert fetch_remote_issues("xzyozi/tfg") == []
        assert fetch_remote_issue("xzyozi/tfg", 1) is None
        mock_run.assert_not_called()


def test_fetch_remote_via_gh_cli() -> None:
    sample_issue = {
        "number": 12,
        "title": "CLI issue",
        "body": "desc",
        "labels": [{"name": "stage:ready"}],
        "state": "OPEN",
        "url": "https://github.com/org/repo/issues/12",
    }
    mock_res = MagicMock(stdout=json.dumps(sample_issue), returncode=0)
    with patch("tools.workspace.github_issues.subprocess.run", return_value=mock_res) as mock_run:
        got = fetch_remote_issue("org/repo", 12, project_key="PRJ")
        assert got is not None
        assert got["task_id"] == "PRJ-0012"
        cmd = mock_run.call_args[0][0]
        assert cmd[:4] == ["gh", "issue", "view", "12"]

    mock_list_res = MagicMock(stdout=json.dumps([sample_issue]), returncode=0)
    with patch(
        "tools.workspace.github_issues.subprocess.run", return_value=mock_list_res
    ) as mock_run:
        items = fetch_remote_issues(
            "org/repo", state="open", labels=["stage:ready"], normalize=True
        )
        assert len(items) == 1
        assert items[0]["stage"] == "stage:ready"
        cmd = mock_run.call_args[0][0]
        assert "--label" in cmd
        assert "stage:ready" in cmd


def test_extract_issue_scoring_metadata() -> None:
    issue = {
        "number": 5,
        "state": "OPEN",
        "createdAt": "2026-10-01T12:34:56Z",
        "labels": [{"name": "stage:ready"}, {"name": "priority:high"}, {"name": "estimate:4h"}],
        "body": "Depends on: #1, TFG-0002\n<!-- blockedby:TFG-0003 -->\n",
    }
    meta = extract_issue_scoring_metadata(issue, project_key="TFG")
    assert meta["priority"] == "high"
    assert meta["estimate"] == "4h"
    assert meta["added"] == "2026-10-01"
    assert meta["stage"] == "stage:ready"
    assert meta["completed"] is False
    assert meta["on_hold"] is False
    assert meta["blockedby"] == ["TFG-0003", "TFG-0001", "TFG-0002"]

    closed_issue = {
        "number": 6,
        "state": "CLOSED",
        "labels": [{"name": "on-hold"}],
        "body": "<!-- priority:low added:2026-09-15 -->",
    }
    meta2 = extract_issue_scoring_metadata(closed_issue, project_key="TFG")
    assert meta2["priority"] == "low"
    assert meta2["added"] == "2026-09-15"
    assert meta2["completed"] is True
    assert meta2["on_hold"] is True

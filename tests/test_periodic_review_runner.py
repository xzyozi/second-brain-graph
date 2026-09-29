#!/usr/bin/env python3
"""periodic_review_runner の単体テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import periodic_review_runner


def test_detect_code_diff_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """git diff 出力からコードファイルのみが抽出されることを検証する."""
    import subprocess

    diff_output = "src/app.py\nREADME.md\nsrc/utils.ts\nassets/icon.png\nconfig.json\n"

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=diff_output, stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = periodic_review_runner.detect_code_diff_files(tmp_path, "commitA", "commitB")
    assert result == ["config.json", "src/app.py", "src/utils.ts"]


def test_sync_issue_statuses_to_tasks_md_closed_and_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub Issue のクローズおよび昇格が tasks.md に反映されることを検証する."""
    tasks_path = tmp_path / "docs" / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    initial_content = (
        "# Tasks\n\n"
        "- [ ] [TEST-0001] Task 1 <!-- priority:high issue:#101 stage:ideation -->\n"
        "- [ ] [TEST-0002] Task 2 <!-- priority:medium issue:#102 stage:ideation -->\n"
    )
    tasks_path.write_text(initial_content, encoding="utf-8")

    mock_issues = [
        {"number": 101, "title": "Task 1", "state": "CLOSED", "labels": []},
        {"number": 102, "title": "Task 2", "state": "OPEN", "labels": [{"name": "stage:ready"}]},
    ]
    monkeypatch.setattr(periodic_review_runner, "fetch_remote_issues", lambda repo: mock_issues)

    updated, added = periodic_review_runner.sync_issue_statuses_to_tasks_md(
        tasks_path, "mock/repo", "TEST", dry_run=False
    )
    assert updated == 2
    assert added == 0

    content = tasks_path.read_text(encoding="utf-8")
    # Issue 101 はクローズされて [x] に更新
    assert "- [x] [TEST-0001] Task 1" in content
    assert "completed:" in content
    # Issue 102 は stage:ready に昇格
    assert "- [ ] [TEST-0002] Task 2 <!-- priority:medium issue:#102 stage:ready -->" in content


def test_sync_issue_statuses_to_tasks_md_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stage:in_progress ラベル時に [/] へ更新されることを検証する."""
    tasks_path = tmp_path / "docs" / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text(
        "# Tasks\n\n- [ ] [TEST-0001] Task 1 <!-- priority:high issue:#101 stage:ready -->\n",
        encoding="utf-8",
    )

    mock_issues = [
        {
            "number": 101,
            "title": "Task 1",
            "state": "OPEN",
            "labels": [{"name": "stage:in_progress"}],
        },
    ]
    monkeypatch.setattr(periodic_review_runner, "fetch_remote_issues", lambda repo: mock_issues)

    updated, added = periodic_review_runner.sync_issue_statuses_to_tasks_md(
        tasks_path, "mock/repo", "TEST", dry_run=False
    )
    assert updated == 1
    assert added == 0

    content = tasks_path.read_text(encoding="utf-8")
    assert "- [/] [TEST-0001] Task 1" in content


def test_sync_issue_statuses_to_tasks_md_import_new_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tasks.md に未登録の Issue が自動インポートされることを検証する."""
    tasks_path = tmp_path / "docs" / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text("# Tasks\n\n", encoding="utf-8")

    mock_issues = [
        {
            "number": 105,
            "title": "New Issue A",
            "state": "OPEN",
            "labels": [{"name": "stage:ready"}, {"name": "theme:security"}],
        },
        {
            "number": 106,
            "title": "New Issue B",
            "state": "CLOSED",
            "labels": [{"name": "theme:edge_cases"}],
        },
    ]
    monkeypatch.setattr(periodic_review_runner, "fetch_remote_issues", lambda repo: mock_issues)

    updated, added = periodic_review_runner.sync_issue_statuses_to_tasks_md(
        tasks_path, "mock/repo", "TEST", dry_run=False
    )
    assert updated == 0
    assert added == 2

    content = tasks_path.read_text(encoding="utf-8")
    assert (
        "- [ ] [TEST-0001] New Issue A <!-- priority:medium issue:#105 theme:security stage:ready"
        in content
    )
    assert (
        "- [x] [TEST-0002] New Issue B <!-- priority:medium issue:#106 theme:edge_cases stage:ideation completed:"
        in content
    )


def test_main_status_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main の --status-only 実行検証."""
    reg_data = {
        "projects": {
            "TEST": {
                "name": "mock_sat",
                "dir": "mock_sat",
                "github_repo": "owner/mock_sat",
            }
        }
    }
    sat_dir = tmp_path / "mock_sat"
    sat_dir.mkdir(parents=True)
    tasks_path = sat_dir / "docs" / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text("# Tasks\n\n", encoding="utf-8")

    monkeypatch.setattr(periodic_review_runner, "load_project_registry", lambda root: reg_data)
    monkeypatch.setattr(periodic_review_runner, "fetch_remote_issues", lambda repo: [])

    # root_dir を tmp_path に向ける
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda p: tmp_path / "tools" / "dummy.py" if "periodic_review_runner.py" in str(p) else p,
    )

    exit_code = periodic_review_runner.main(["--status-only", "--dry-run"])
    assert exit_code == 0

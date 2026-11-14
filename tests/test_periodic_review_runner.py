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


def test_evaluate_remote_issue_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub Issues の状態・stage ラベル集計が正しく動作することを検証する."""
    mock_issues = [
        {
            "number": 101,
            "title": "Task 1",
            "state": "CLOSED",
            "labels": [{"name": "stage:done"}],
        },
        {
            "number": 102,
            "title": "Task 2",
            "state": "OPEN",
            "labels": [{"name": "stage:ready"}],
        },
        {
            "number": 103,
            "title": "Task 3",
            "state": "OPEN",
            "labels": [{"name": "stage:in-progress"}],
        },
        {
            "number": 104,
            "title": "Task 4",
            "state": "OPEN",
            "labels": [{"name": "stage:ideation"}],
        },
    ]
    monkeypatch.setattr(periodic_review_runner, "fetch_remote_issues", lambda repo: mock_issues)

    summary = periodic_review_runner.evaluate_remote_issue_statuses("mock/repo")
    assert summary["total"] == 4
    assert summary["open"] == 3
    assert summary["closed"] == 1
    assert summary["stage:ready"] == 1
    assert summary["stage:in-progress"] == 1
    assert summary["stage:ideation"] == 1
    assert summary["stage:done"] == 1


def test_execute_satellite_review_omits_sync_tasks_md_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """execute_satellite_review が run_review.py へ --sync-tasks-md を渡さないことを検証する."""
    import subprocess

    captured_cmds: list[list[str]] = []

    def mock_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    ok = periodic_review_runner.execute_satellite_review(
        root_dir=tmp_path,
        target_name="mock_sat",
        theme="security",
        files=["src/app.py"],
        timeout=120,
        dry_run=True,
    )
    assert ok is True
    assert len(captured_cmds) == 1
    assert "--sync-tasks-md" not in captured_cmds[0]
    assert "--target" in captured_cmds[0]
    assert "--files" in captured_cmds[0]


def test_main_status_only_does_not_create_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main の --status-only 実行で tasks.md / docs/issues が作成されないことを検証する."""
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

    monkeypatch.setattr(periodic_review_runner, "load_project_registry", lambda root: reg_data)
    monkeypatch.setattr(
        periodic_review_runner,
        "fetch_remote_issues",
        lambda repo: [
            {
                "number": 101,
                "title": "Ready Task",
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}],
            }
        ],
    )

    # root_dir を tmp_path に向ける
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda p: (
            tmp_path / "tools" / "lifecycle" / "dummy.py"
            if "periodic_review_runner.py" in str(p)
            else p
        ),
    )

    exit_code = periodic_review_runner.main(["--status-only"])
    assert exit_code == 0
    assert not (sat_dir / "docs" / "tasks.md").exists()
    assert not (sat_dir / "docs" / "issues").exists()

#!/usr/bin/env python3
"""tests/test_nightly_task_worker.py - nightly_task_worker の単体テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import nightly_task_worker


def test_load_config_valid_toml(tmp_path: Path) -> None:
    """TOML 設定ファイルが正しくロードされることを検証する."""
    cfg_file = tmp_path / "test_config.toml"
    cfg_content = """
    version = "1.0"
    enabled = true
    max_tasks_per_run = 2
    target_projects = ["all"]

    [task_selection]
    require_label = "stage:ready"
    skip_blocked = true

    [execution]
    create_draft_pr = true
    auto_stash = true
    timeout_seconds = 300
    """
    cfg_file.write_text(cfg_content, encoding="utf-8")

    config = nightly_task_worker.load_config(cfg_file)
    assert config["version"] == "1.0"
    assert config["enabled"] is True
    assert config["max_tasks_per_run"] == 2
    assert config["task_selection"]["require_label"] == "stage:ready"
    assert config["execution"]["timeout_seconds"] == 300


def test_parse_tasks_md_candidates(tmp_path: Path) -> None:
    """tasks.md から stage:ready タスクのみが抽出され優先度スコア順に計算されることを検証する."""
    tasks_file = tmp_path / "docs" / "tasks.md"
    tasks_file.parent.mkdir(parents=True)
    tasks_content = """
    # Tasks

    - [ ] [CW-0001] Task Ideation <!-- priority:high stage:ideation issue:#101 -->
    - [ ] [CW-0002] Task Ready High <!-- priority:high stage:ready issue:#102 added:2026-09-01 -->
    - [ ] [CW-0003] Task Ready Medium <!-- priority:medium stage:ready issue:#103 added:2026-09-20 -->
    - [x] [CW-0004] Task Completed <!-- priority:critical stage:ready issue:#104 -->
    - [ ] [CW-0005] Task Blocked <!-- priority:critical stage:ready issue:#105 blockedby:CW-0002 -->
    """
    tasks_file.write_text(tasks_content, encoding="utf-8")

    candidates = nightly_task_worker.parse_tasks_md_candidates(
        tasks_path=tasks_file,
        project_key="CW",
        project_name="clip_watcher",
        satellite_dir=tmp_path,
        require_label="stage:ready",
        skip_blocked=True,
    )

    # CW-0001 (ideation), CW-0004 (completed), CW-0005 (blocked) は除外される
    assert len(candidates) == 2
    task_ids = [c.task_id for c in candidates]
    assert task_ids == ["CW-0002", "CW-0003"]

    # CW-0002 (high) のスコアが CW-0003 (medium) より高いこと
    assert candidates[0].score > candidates[1].score


def test_select_best_task_cap(tmp_path: Path) -> None:
    """複数候補から max_tasks 件数で正しく上位のみが選定されることを検証する."""
    c1 = nightly_task_worker.CandidateTask(
        task_id="T1",
        project_key="CW",
        project_name="clip_watcher",
        satellite_dir=tmp_path,
        title="Title 1",
        priority="medium",
        score=50.0,
        stage="ready",
        issue_num=101,
        line_raw="",
    )
    c2 = nightly_task_worker.CandidateTask(
        task_id="T2",
        project_key="CW",
        project_name="clip_watcher",
        satellite_dir=tmp_path,
        title="Title 2",
        priority="high",
        score=85.0,
        stage="ready",
        issue_num=102,
        line_raw="",
    )

    # 上限 1 件
    best = nightly_task_worker.select_best_task([c1, c2], max_tasks=1)
    assert len(best) == 1
    assert best[0].task_id == "T2"

    # 上限 2 件
    best_two = nightly_task_worker.select_best_task([c1, c2], max_tasks=2)
    assert len(best_two) == 2
    assert best_two[0].task_id == "T2"
    assert best_two[1].task_id == "T1"


def test_main_disabled_config(tmp_path: Path) -> None:
    """enabled = false の設定時に即座に 0 終了することを検証する."""
    cfg_file = tmp_path / "disabled_config.toml"
    cfg_file.write_text("enabled = false\n", encoding="utf-8")

    exit_code = nightly_task_worker.main(["--config", str(cfg_file)])
    assert exit_code == 0


def test_main_dry_run_with_no_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """対象タスクが存在しない場合の正常終了を検証する."""
    cfg_file = tmp_path / "test_config.toml"
    cfg_file.write_text("enabled = true\nmax_tasks_per_run = 1\n", encoding="utf-8")

    monkeypatch.setattr(nightly_task_worker, "load_project_registry", lambda root: {"projects": {}})

    exit_code = nightly_task_worker.main(["--config", str(cfg_file), "--dry-run"])
    assert exit_code == 0

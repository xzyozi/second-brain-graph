#!/usr/bin/env python3
"""tests/test_nightly_task_worker.py - nightly_task_worker の単体テスト."""

from __future__ import annotations

import datetime
import logging
import signal
import threading
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

    [loop]
    enabled = true
    mode = "daily"
    daily_times = ["03:00", "12:00"]
    interval_seconds = 1800

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
    assert config["loop"]["enabled"] is True
    assert config["loop"]["mode"] == "daily"
    assert config["loop"]["daily_times"] == ["03:00", "12:00"]
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


def test_normalize_daily_times() -> None:
    """時刻指定文字列やリストの正規化を検証する."""
    # 単一文字列
    assert nightly_task_worker.normalize_daily_times("03:00") == ["03:00"]
    # カンマ区切り
    assert nightly_task_worker.normalize_daily_times("12:00, 03:00") == ["03:00", "12:00"]
    # リスト形式（ソート＆重複排除）
    assert nightly_task_worker.normalize_daily_times(["18:00", "03:00", "12:00", "03:00"]) == [
        "03:00",
        "12:00",
        "18:00",
    ]
    # 空値フォールバック
    assert nightly_task_worker.normalize_daily_times([]) == ["03:00"]

    # フォーマット異常は ValueError
    with pytest.raises(ValueError):
        nightly_task_worker.normalize_daily_times("25:00")
    with pytest.raises(ValueError):
        nightly_task_worker.normalize_daily_times("12:60")
    with pytest.raises(ValueError):
        nightly_task_worker.normalize_daily_times("invalid")


def test_get_next_target_time_multiple_schedules() -> None:
    """複数断面から直近の目標時刻と待機秒数が正しく算出されることを検証する."""
    base_times = ["03:00", "12:00", "18:00"]

    # 1. 現在時刻が 10:00 の場合 -> 直近断面は 12:00 (差分 2時間 = 7200秒)
    now_10am = datetime.datetime(2026, 9, 30, 10, 0, 0)
    wait_secs, next_time = nightly_task_worker.get_next_target_time(base_times, now=now_10am)
    assert next_time == "12:00"
    assert wait_secs == pytest.approx(7200.0)

    # 2. 現在時刻が 15:30 の場合 -> 直近断面は 18:00 (差分 2.5時間 = 9000秒)
    now_330pm = datetime.datetime(2026, 9, 30, 15, 30, 0)
    wait_secs, next_time = nightly_task_worker.get_next_target_time(base_times, now=now_330pm)
    assert next_time == "18:00"
    assert wait_secs == pytest.approx(9000.0)

    # 3. 現在時刻が 22:00 の場合（本日分終了） -> 直近断面は翌日の 03:00 (差分 5時間 = 18000秒)
    now_10pm = datetime.datetime(2026, 9, 30, 22, 0, 0)
    wait_secs, next_time = nightly_task_worker.get_next_target_time(base_times, now=now_10pm)
    assert next_time == "03:00"
    assert wait_secs == pytest.approx(18000.0)


def test_calculate_sleep_seconds_until_backward_compatible() -> None:
    """単一時刻指定に対する calculate_sleep_seconds_until の後方互換性を検証する."""
    base_time = datetime.datetime(2026, 9, 30, 10, 0, 0)
    secs = nightly_task_worker.calculate_sleep_seconds_until("11:30", now=base_time)
    assert secs == pytest.approx(5400.0)

    secs_next_day = nightly_task_worker.calculate_sleep_seconds_until("03:00", now=base_time)
    assert secs_next_day == pytest.approx(17 * 3600.0)


def test_interruptible_sleep() -> None:
    """interruptible_sleep が指定短時間で安全に終了することを検証する."""
    stop_event = threading.Event()
    result = nightly_task_worker.interruptible_sleep(0.05, stop_event, check_interval=0.01)
    assert result is True


def test_interruptible_sleep_returns_false_when_stop_event_is_set() -> None:
    """停止イベントが設定済みなら待機せず False を返すことを検証する."""
    stop_event = threading.Event()
    stop_event.set()

    result = nightly_task_worker.interruptible_sleep(60.0, stop_event)

    assert result is False


def test_main_disabled_config(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """enabled = false の設定時に即座に 0 終了することを検証する."""
    cfg_file = tmp_path / "disabled_config.toml"
    cfg_file.write_text("enabled = false\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(["--config", str(cfg_file)])

    assert exit_code == 0
    assert "ワンショットモード終了理由 (Exit Reason): disabled" in caplog.text


def test_main_dry_run_with_no_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """対象タスクが存在しない場合の正常終了を検証する."""
    cfg_file = tmp_path / "test_config.toml"
    cfg_file.write_text("enabled = true\nmax_tasks_per_run = 1\n", encoding="utf-8")

    monkeypatch.setattr(nightly_task_worker, "load_project_registry", lambda root: {"projects": {}})

    exit_code = nightly_task_worker.main(["--config", str(cfg_file), "--dry-run"])
    assert exit_code == 0


def test_run_loop_with_max_iterations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """自己ループモードが max_iterations の指定回数で安全終了することを検証する."""
    cfg_file = tmp_path / "loop_config.toml"
    cfg_content = """
    version = "1.0"
    enabled = true
    max_tasks_per_run = 1
    target_projects = ["all"]

    [loop]
    enabled = true
    mode = "interval"
    interval_seconds = 0
    """
    cfg_file.write_text(cfg_content, encoding="utf-8")

    monkeypatch.setattr(nightly_task_worker, "load_project_registry", lambda root: {"projects": {}})

    cycle_count = 0

    def mock_cycle(root: Path, config: dict, opts: object) -> int:
        nonlocal cycle_count
        cycle_count += 1
        return 0

    monkeypatch.setattr(nightly_task_worker, "run_batch_cycle", mock_cycle)

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(
            [
                "--config",
                str(cfg_file),
                "--loop",
                "--loop-mode",
                "interval",
                "--interval",
                "0",
                "--max-iterations",
                "3",
            ]
        )

    assert exit_code == 0
    assert cycle_count == 3
    assert "終了理由 (Exit Reason): max_iterations" in caplog.text


def test_run_loop_logs_daily_boundary_reached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """daily 待機の正常満了時に到達断面と次周回番号をログすることを検証する."""
    cfg_file = tmp_path / "daily_loop_config.toml"
    cfg_file.write_text(
        'enabled = true\n[loop]\nenabled = true\nmode = "daily"\n',
        encoding="utf-8",
    )

    cycle_count = 0

    def mock_cycle(root: Path, config: dict, opts: object) -> int:
        nonlocal cycle_count
        cycle_count += 1
        return 0

    monkeypatch.setattr(nightly_task_worker, "run_batch_cycle", mock_cycle)
    monkeypatch.setattr(
        nightly_task_worker,
        "get_next_target_time",
        lambda target_times: (0.0, "18:00"),
    )

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(
            [
                "--config",
                str(cfg_file),
                "--loop",
                "--loop-mode",
                "daily",
                "--daily-times",
                "18:00",
                "--max-iterations",
                "2",
            ]
        )

    assert exit_code == 0
    assert cycle_count == 2
    assert "指定断面時刻 (18:00) に到達しました。周回 #2 を開始します。" in caplog.text
    assert "終了理由 (Exit Reason): max_iterations" in caplog.text


def test_run_loop_enabled_false_exits_without_batch_or_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ループ中に enabled=false を検知したら処理・待機せず終了することを検証する."""
    cfg_file = tmp_path / "disabled_loop_config.toml"
    cfg_file.write_text(
        'enabled = false\n[loop]\nenabled = true\nmode = "interval"\ninterval_seconds = 3600\n',
        encoding="utf-8",
    )

    def fail_cycle(root: Path, config: dict, opts: object) -> int:
        raise AssertionError("enabled=false の設定でバッチを実行してはいけません")

    def fail_sleep(*args: object, **kwargs: object) -> bool:
        raise AssertionError("enabled=false の設定で待機してはいけません")

    monkeypatch.setattr(nightly_task_worker, "run_batch_cycle", fail_cycle)
    monkeypatch.setattr(nightly_task_worker, "interruptible_sleep", fail_sleep)

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(["--config", str(cfg_file), "--loop"])

    assert exit_code == 0
    assert "終了理由 (Exit Reason): disabled" in caplog.text


def test_run_loop_keyboard_interrupt_logs_exit_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """待機中の KeyboardInterrupt を捕捉して終了理由を記録することを検証する."""
    cfg_file = tmp_path / "interrupt_loop_config.toml"
    cfg_file.write_text(
        'enabled = true\n[loop]\nenabled = true\nmode = "interval"\ninterval_seconds = 1\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(nightly_task_worker, "run_batch_cycle", lambda root, config, opts: 0)

    def raise_keyboard_interrupt(*args: object, **kwargs: object) -> bool:
        raise KeyboardInterrupt

    monkeypatch.setattr(nightly_task_worker, "interruptible_sleep", raise_keyboard_interrupt)

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(["--config", str(cfg_file), "--loop"])

    assert exit_code == 0
    assert "ユーザー割り込み (Ctrl+C) を検知しました。安全に停止します。" in caplog.text
    assert "終了理由 (Exit Reason): keyboard_interrupt" in caplog.text


def test_windows_does_not_register_sigterm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Windows では SIGINT のみを登録し SIGTERM を登録しないことを検証する."""
    cfg_file = tmp_path / "windows_loop_config.toml"
    cfg_file.write_text(
        'enabled = true\n[loop]\nenabled = true\nmode = "interval"\ninterval_seconds = 0\n',
        encoding="utf-8",
    )

    registered_signals: list[int] = []

    def fake_signal(signum: int, handler: object) -> object:
        registered_signals.append(signum)
        return signal.SIG_DFL

    monkeypatch.setattr(nightly_task_worker.sys, "platform", "win32")
    monkeypatch.setattr(nightly_task_worker.signal, "signal", fake_signal)
    monkeypatch.setattr(nightly_task_worker, "run_batch_cycle", lambda root, config, opts: 0)

    with caplog.at_level(logging.INFO, logger="nightly_worker"):
        exit_code = nightly_task_worker.main(
            ["--config", str(cfg_file), "--loop", "--max-iterations", "1"]
        )

    assert exit_code == 0
    assert signal.SIGINT in registered_signals
    assert signal.SIGTERM not in registered_signals
    assert "終了理由 (Exit Reason): max_iterations" in caplog.text

"""L2 process-boundary tests for the agy client using a local fake CLI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tools.agy_client import AgyExitError, AgyTimeoutError, run_agy_in_workdir, run_agy_text

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_agy(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Select the platform-specific fake agy wrapper for the test process."""
    wrapper_name = "fake_agy.cmd" if os.name == "nt" else "fake_agy.sh"
    wrapper = (FIXTURE_DIR / wrapper_name).resolve()
    monkeypatch.setenv("SBOS_AGY_EXECUTABLE", str(wrapper))
    monkeypatch.delenv("FAKE_AGY_MODE", raising=False)
    monkeypatch.delenv("FAKE_AGY_PROMPT_FILE", raising=False)
    monkeypatch.delenv("FAKE_AGY_TIMEOUT_MARKER", raising=False)
    return wrapper


def test_fake_agy_text_response_and_prompt(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real Popen boundary returns text and forwards the prompt unchanged."""
    prompt_file = tmp_path / "prompt.txt"
    prompt = "テストプロンプト: text"
    monkeypatch.setenv("FAKE_AGY_MODE", "text")
    monkeypatch.setenv("FAKE_AGY_PROMPT_FILE", str(prompt_file))

    response = run_agy_text(prompt, timeout=5, cwd=str(tmp_path))

    assert response == "FAKE_AGY_TEXT_OK"
    assert prompt_file.read_text(encoding="utf-8") == prompt


def test_fake_agy_json_response_is_raw_stdout(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client returns JSON stdout as text for the caller to decode."""
    monkeypatch.setenv("FAKE_AGY_MODE", "json")

    response = run_agy_text("テストプロンプト: json", timeout=5, cwd=str(tmp_path))

    assert response == '{"verdict":"LGTM","comments":[]}'
    assert json.loads(response) == {"verdict": "LGTM", "comments": []}


def test_fake_agy_nonzero_exit_includes_stderr(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero fake process becomes an AgyExitError with stderr and status."""
    monkeypatch.setenv("FAKE_AGY_MODE", "exit")

    with pytest.raises(AgyExitError, match="FAKE_AGY_EXIT_ERROR") as exc_info:
        run_agy_text("テストプロンプト: exit", timeout=5, cwd=str(tmp_path))

    assert exc_info.value.returncode == 7


def test_fake_agy_timeout_terminates_process(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeout handling stops the fake process before its delayed marker write."""
    marker = tmp_path / "timeout-completed.txt"
    monkeypatch.setenv("FAKE_AGY_MODE", "timeout")
    monkeypatch.setenv("FAKE_AGY_TIMEOUT_MARKER", str(marker))

    with pytest.raises(AgyTimeoutError, match="timed out"):
        run_agy_text("テストプロンプト: timeout", timeout=1, cwd=str(tmp_path))

    deadline = time.monotonic() + 1.5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not marker.exists()


def test_fake_agy_edit_writes_complete_target_file(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The edit mode writes complete Python code inside the requested cwd."""
    monkeypatch.setenv("FAKE_AGY_MODE", "edit")

    response = run_agy_in_workdir("target.pyを編集", cwd=str(tmp_path), timeout=5)

    target = tmp_path / "target.py"
    assert response == ""
    assert target.is_file()
    source = target.read_text(encoding="utf-8")
    compile(source, str(target), "exec")
    assert "FAKE_AGY_EDIT_OK" in source


def test_fake_agy_unauthorized_mode_writes_both_fixture_files(
    fake_agy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture can model an out-of-scope write at the raw L2 process seam."""
    monkeypatch.setenv("FAKE_AGY_MODE", "unauthorized")

    run_agy_in_workdir("範囲外書き込みを試す", cwd=str(tmp_path), timeout=5)

    assert (tmp_path / "target.py").read_text(encoding="utf-8") == "UNAUTHORIZED_TARGET = True\n"
    assert (tmp_path / "unauthorized.txt").read_text(encoding="utf-8") == (
        "FAKE_AGY_UNAUTHORIZED_WRITE\n"
    )

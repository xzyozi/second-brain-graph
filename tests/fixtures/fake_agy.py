"""Harmless local fake for exercising the agy subprocess boundary."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

TEXT_RESPONSE = "FAKE_AGY_TEXT_OK"
JSON_RESPONSE = '{"verdict":"LGTM","comments":[]}'
INVALID_JSON_RESPONSE = "NOT_VALID_JSON {broken"
EDITED_TARGET = '''"""Target written by the fake agy edit mode."""


def fake_agy_edit() -> str:
    return "FAKE_AGY_EDIT_OK"


if __name__ == "__main__":
    print(fake_agy_edit())
'''
UNAUTHORIZED_TARGET = "UNAUTHORIZED_TARGET = True\n"


def _parse_prompt(argv: list[str]) -> str:
    """Accept exactly the non-interactive arguments used by agy_client."""
    expected_prefix = ["--dangerously-skip-permissions", "-p"]
    if len(argv) != 3 or argv[:2] != expected_prefix:
        sys.stderr.write("FAKE_AGY_INVALID_ARGS")
        raise SystemExit(2)
    return argv[2]


def _save_prompt(prompt: str) -> None:
    prompt_file = os.environ.get("FAKE_AGY_PROMPT_FILE")
    if prompt_file:
        Path(prompt_file).write_text(prompt, encoding="utf-8")


def _run_edit(mode: str, files: dict[str, str] | None = None) -> None:
    cwd = Path.cwd()
    if files:
        for rel_path, content in files.items():
            dest = cwd / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return
    if mode == "edit":
        (cwd / "target.py").write_text(EDITED_TARGET, encoding="utf-8")
    elif mode == "unauthorized":
        (cwd / "target.py").write_text(UNAUTHORIZED_TARGET, encoding="utf-8")
        (cwd / "unauthorized.txt").write_text("FAKE_AGY_UNAUTHORIZED_WRITE\n", encoding="utf-8")


def _run_timeout(sleep_sec: float = 2.0) -> None:
    time.sleep(sleep_sec)
    marker = os.environ.get("FAKE_AGY_TIMEOUT_MARKER")
    if marker:
        Path(marker).write_text("FAKE_AGY_TIMEOUT_COMPLETED\n", encoding="utf-8")


def _next_step() -> dict[str, Any]:
    seq_path_str = os.environ.get("FAKE_AGY_SEQUENCE_FILE", "").strip()
    if not seq_path_str:
        return {"mode": os.environ.get("FAKE_AGY_MODE", "text")}

    seq_path = Path(seq_path_str)
    idx_path = seq_path.with_suffix(seq_path.suffix + ".idx")
    steps = json.loads(seq_path.read_text(encoding="utf-8"))
    if isinstance(steps, dict):
        steps = steps.get("steps", [])
    idx = int(idx_path.read_text(encoding="utf-8").strip()) if idx_path.exists() else 0
    idx_path.write_text(str(idx + 1), encoding="utf-8")
    if idx < len(steps):
        item = steps[idx]
        return item if isinstance(item, dict) else {"mode": str(item)}
    return {"mode": "exit", "stderr": f"FAKE_AGY_SEQUENCE_EXHAUSTED (idx={idx})", "returncode": 2}


def main(argv: list[str]) -> int:
    """Run one deterministic fake agy mode and return its process status."""
    prompt = _parse_prompt(argv)
    _save_prompt(prompt)
    step = _next_step()
    mode = str(step.get("mode", "text"))

    if mode == "text":
        sys.stdout.write(str(step.get("stdout", TEXT_RESPONSE)))
    elif mode == "json":
        sys.stdout.write(str(step.get("stdout", JSON_RESPONSE)))
    elif mode == "invalid_json":
        sys.stdout.write(str(step.get("stdout", INVALID_JSON_RESPONSE)))
    elif mode == "exit":
        sys.stderr.write(str(step.get("stderr", "FAKE_AGY_EXIT_ERROR")))
        return int(step.get("returncode", 7))
    elif mode == "timeout":
        _run_timeout(float(step.get("sleep", 2.0)))
    elif mode in {"edit", "unauthorized"}:
        raw_files = step.get("files")
        files = raw_files if isinstance(raw_files, dict) else None
        _run_edit(mode, files=files)
    else:
        sys.stderr.write("FAKE_AGY_UNKNOWN_MODE")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

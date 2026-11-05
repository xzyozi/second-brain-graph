"""Harmless local fake for exercising the agy subprocess boundary."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

TEXT_RESPONSE = "FAKE_AGY_TEXT_OK"
JSON_RESPONSE = '{"verdict":"LGTM","comments":[]}'
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


def _run_edit(mode: str) -> None:
    cwd = Path.cwd()
    if mode == "edit":
        (cwd / "target.py").write_text(EDITED_TARGET, encoding="utf-8")
    elif mode == "unauthorized":
        (cwd / "target.py").write_text(UNAUTHORIZED_TARGET, encoding="utf-8")
        (cwd / "unauthorized.txt").write_text("FAKE_AGY_UNAUTHORIZED_WRITE\n", encoding="utf-8")


def _run_timeout() -> None:
    time.sleep(2.0)
    marker = os.environ.get("FAKE_AGY_TIMEOUT_MARKER")
    if marker:
        Path(marker).write_text("FAKE_AGY_TIMEOUT_COMPLETED\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    """Run one deterministic fake agy mode and return its process status."""
    prompt = _parse_prompt(argv)
    _save_prompt(prompt)
    mode = os.environ.get("FAKE_AGY_MODE", "text")

    if mode == "text":
        sys.stdout.write(TEXT_RESPONSE)
    elif mode == "json":
        sys.stdout.write(JSON_RESPONSE)
    elif mode == "exit":
        sys.stderr.write("FAKE_AGY_EXIT_ERROR")
        return 7
    elif mode == "timeout":
        _run_timeout()
    elif mode in {"edit", "unauthorized"}:
        _run_edit(mode)
    else:
        sys.stderr.write("FAKE_AGY_UNKNOWN_MODE")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""L4 E2E scenario tests exercising orchestrator_graph across real git, Popen, and JEV boundaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

from tools.backends import backend_coordinator, jev_adapter
from tools.backends.backend_coordinator import BackendExecutionCoordinator
from tools.core.orchestrator_graph import GraphState, execute_issue, review_node
from tools.workspace.config_loader import BackendExecutionConfig, ProfileConfig
from tools.workspace.github_issues import use_issue_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"

VALID_CALC_PY = '''"""Simple calculator module."""


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b
'''

VALID_TEST_CALC_PY = '''"""Unit tests for calc module."""

from src.calc import add


def test_add() -> None:
    assert add(2, 3) == 5
'''


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return res.stdout.strip()


def _install_fake_gh(bin_dir: Path, pr_log: Path) -> None:
    """Create a cross-platform fake gh CLI wrapper that logs PR creation calls."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script_py = bin_dir / "fake_gh.py"
    script_py.write_text(
        (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "log_path = Path(os.environ['FAKE_GH_LOG'])\n"
            "records = json.loads(log_path.read_text(encoding='utf-8')) if log_path.exists() else []\n"
            "records.append(args)\n"
            "log_path.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')\n"
            "if args[:2] == ['pr', 'list']:\n"
            "    print('[]')\n"
            "elif args[:2] == ['pr', 'create']:\n"
            "    print('https://github.com/xzyozi/test_file_grep/pull/999')\n"
            "else:\n"
            "    print('')\n"
        ),
        encoding="utf-8",
    )

    if os.name == "nt":
        wrapper = bin_dir / "gh.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{os.path.abspath(sys.executable)}" "{script_py}" %*\r\n',
            encoding="utf-8",
        )
    else:
        wrapper = bin_dir / "gh"
        wrapper.write_text(
            f'#!/usr/bin/env sh\nexec "{os.path.abspath(sys.executable)}" "{script_py}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)


def _setup_workspace(tmp_path: Path) -> dict[str, Path]:
    """Create an isolated mother repo structure with a real bare origin and working satellite."""
    project_root = tmp_path / "mother"
    metadata_dir = project_root / "metadata"
    meta_tfg = metadata_dir / "projects" / "TFG"
    meta_tfg.mkdir(parents=True, exist_ok=True)
    history_file = project_root / "tools" / ".cache" / "execution_history.json"

    origin_bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin_bare)], check=True)

    sat_dir = project_root / "projects" / "test_file_grep"
    sat_dir.mkdir(parents=True, exist_ok=True)
    _git(sat_dir, "init", "-q", "-b", "develop")
    _git(sat_dir, "config", "user.name", "SBOS Test")
    _git(sat_dir, "config", "user.email", "sbos-test@example.com")

    (sat_dir / "src").mkdir(parents=True, exist_ok=True)
    (sat_dir / "src" / "__init__.py").write_text("", encoding="utf-8")
    (sat_dir / "src" / "calc.py").write_text(
        '"""Placeholder."""\n\n\ndef add(a: int, b: int) -> int:\n    return 0\n',
        encoding="utf-8",
    )
    (sat_dir / "src" / "untouched.py").write_text("KEEP_ME = 'original'\n", encoding="utf-8")
    (sat_dir / "tests").mkdir(parents=True, exist_ok=True)
    (sat_dir / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (sat_dir / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_placeholder() -> None:\n    assert callable(add)\n",
        encoding="utf-8",
    )
    (sat_dir / ".gitignore").write_text(".venv/\n.agy*\n*.pyc\n", encoding="utf-8")

    _git(sat_dir, "add", "-A")
    _git(sat_dir, "commit", "-q", "-m", "chore: initial satellite repo")
    _git(sat_dir, "remote", "add", "origin", str(origin_bare))
    _git(sat_dir, "push", "-q", "-u", "origin", "develop")

    (meta_tfg / "project.json").write_text(
        json.dumps(
            {
                "key": "TFG",
                "name": "test_file_grep",
                "base_branch": "develop",
                "github_repo": "xzyozi/test_file_grep",
            }
        ),
        encoding="utf-8",
    )
    (metadata_dir / ".project-registry.json").write_text(
        json.dumps(
            {
                "projects": {
                    "TFG": {
                        "name": "test_file_grep",
                        "dir": "projects/test_file_grep",
                        "meta": "metadata/projects/TFG",
                        "github_repo": "xzyozi/test_file_grep",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "fake_bin"
    pr_log = tmp_path / "fake_gh_calls.json"
    _install_fake_gh(bin_dir, pr_log)

    return {
        "project_root": project_root,
        "metadata_dir": metadata_dir,
        "history_file": history_file,
        "sat_dir": sat_dir,
        "bin_dir": bin_dir,
        "pr_log": pr_log,
    }


def _issue_fixture_for_tfg99() -> dict[str, list[dict[str, Any]]]:
    body = (
        "## 1. 課題・背景 (Context)\n"
        "- **起票ステータス**: `stage:ready`\n\n"
        "calc.add を実装する。\n\n"
        "## 4. 編集対象ファイル (Target Files)\n"
        "- `src/calc.py`\n"
        "- `tests/test_calc.py`\n"
    )
    return {
        "xzyozi/test_file_grep": [
            {
                "number": 99,
                "title": "[L4] calc.add implementation",
                "body": body,
                "state": "OPEN",
                "labels": [{"name": "stage:ready"}],
                "url": "https://github.com/xzyozi/test_file_grep/issues/99",
            }
        ]
    }


@pytest.fixture
def l4_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Path]]:
    """Configure real fake_agy subprocess boundary, fake gh CLI, and isolated git workspace."""
    ws = _setup_workspace(tmp_path)

    wrapper_name = "fake_agy.cmd" if os.name == "nt" else "fake_agy.sh"
    wrapper_path = (FIXTURES_DIR / wrapper_name).resolve()
    monkeypatch.setenv("SBOS_AGY_EXECUTABLE", str(wrapper_path))
    monkeypatch.setenv("FAKE_GH_LOG", str(ws["pr_log"]))
    monkeypatch.setenv("PATH", f"{ws['bin_dir']}{os.pathsep}{os.environ.get('PATH', '')}")

    # Shorten agy timeout to 1s so fake timeout steps complete quickly in L4 scenarios.
    test_cfg = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        gpu_lease_timeout=10,
        routes={
            "spec_draft": "agy_default",
            "task_decomposition": "agy_default",
            "task_prioritization": "agy_default",
            "code_edit": "agy_default",
            "aider_edit": "agy_default",
            "code_review": "agy_default",
            "failure_analysis": "agy_default",
            "test_feedback": "agy_default",
        },
        profiles={
            "agy_default": ProfileConfig(
                backend="agy",
                model="agy-default",
                timeout=1,
            )
        },
    )
    coordinator = BackendExecutionCoordinator()
    coordinator.config = test_cfg
    monkeypatch.setattr(backend_coordinator, "get_coordinator", lambda: coordinator)
    monkeypatch.setattr("tools.backends.llm_client.get_coordinator", lambda: coordinator)
    monkeypatch.setattr("tools.core.orchestrator_graph.get_coordinator", lambda: coordinator)

    with use_issue_fixture(_issue_fixture_for_tfg99()):
        yield ws


def _set_fake_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, steps: list[dict[str, Any]]
) -> Path:
    seq_file = tmp_path / "fake_agy_sequence.json"
    seq_file.write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FAKE_AGY_SEQUENCE_FILE", str(seq_file))
    return seq_file


def _read_sequence_index(seq_file: Path) -> int:
    idx_file = seq_file.with_suffix(seq_file.suffix + ".idx")
    return int(idx_file.read_text(encoding="utf-8").strip()) if idx_file.exists() else 0


def _read_state(ws: dict[str, Path], issue_id: str = "TFG-0099") -> dict[str, Any]:
    state_file = ws["metadata_dir"] / "projects" / "TFG" / "state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    return data[issue_id]


def test_l4_002_planner_timeout_retries_and_recovers(
    l4_env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4-002 (recovery): spec_draft retries once on timeout and completes the full pipeline."""
    seq_file = _set_fake_sequence(
        tmp_path,
        monkeypatch,
        [
            {"mode": "timeout", "sleep": 2.5},
            {
                "mode": "text",
                "stdout": "Plan: implement add() in src/calc.py and test in tests/test_calc.py.",
            },
            {
                "mode": "edit",
                "files": {"src/calc.py": VALID_CALC_PY, "tests/test_calc.py": VALID_TEST_CALC_PY},
            },
            {"mode": "json", "stdout": '{"verdict":"LGTM","comments":[]}'},
        ],
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_plan_conformance", lambda **_: (True, 1.0, "ok")
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_review_conformance", lambda **_: (True, 1.0, "ok")
    )

    execute_issue(
        "TFG-0099",
        "TFG",
        metadata_dir=l4_env["metadata_dir"],
        history_file=l4_env["history_file"],
        project_root=l4_env["project_root"],
        fresh=True,
    )

    assert _read_sequence_index(seq_file) == 4
    task_state = _read_state(l4_env)
    assert task_state["status"] == "COMPLETED"
    assert l4_env["pr_log"].exists()
    gh_calls = json.loads(l4_env["pr_log"].read_text(encoding="utf-8"))
    assert any(call[:2] == ["pr", "create"] for call in gh_calls)


def test_l4_002_planner_consecutive_timeouts_stop_safely(
    l4_env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4-002 (safe stop): two consecutive spec_draft timeouts escalate to FAILED_SYSTEM / LLM_TIMEOUT."""
    seq_file = _set_fake_sequence(
        tmp_path,
        monkeypatch,
        [
            {"mode": "timeout", "sleep": 2.5},
            {"mode": "timeout", "sleep": 2.5},
        ],
    )

    execute_issue(
        "TFG-0099",
        "TFG",
        metadata_dir=l4_env["metadata_dir"],
        history_file=l4_env["history_file"],
        project_root=l4_env["project_root"],
        fresh=True,
    )

    assert _read_sequence_index(seq_file) == 2
    task_state = _read_state(l4_env)
    assert task_state["status"] == "FAILED_SYSTEM"
    assert task_state["error_category"] == "LLM_TIMEOUT"


def test_l4_003_reviewer_invalid_json_transitions_to_changes_requested(
    l4_env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4-003: malformed reviewer JSON transitions safely to changes_requested (not LGTM) and recovers on next round."""
    # Direct review_node check with real _parse_llm_output via fake_agy invalid_json mode
    with monkeypatch.context() as m:
        m.setenv("FAKE_AGY_MODE", "invalid_json")
        m.delenv("FAKE_AGY_SEQUENCE_FILE", raising=False)
        state: GraphState = {
            "issue_id": "TFG-0099",
            "project_key": "TFG",
            "target_files": ["src/calc.py"],
            "instruction": "Implement add",
            "impl_plan": "Plan",
            "cwd": str(l4_env["sat_dir"]),
            "base_branch": "develop",
            "review_round": 0,
            "max_round": 3,
            "review_rounds": [],
        }
        m.setattr(
            "tools.core.orchestrator_graph.get_git_diff",
            lambda *_, **__: "diff --git a/src/calc.py",
        )
        rev_res = review_node(state)
        assert rev_res["review_verdict"] == "changes_requested"
        assert rev_res["status"] == "retry_code"
        assert rev_res["error_category"] == "REVIEW_REJECTED"

    # Full graph flow: invalid JSON in round 1 causes retry_code, then LGTM in round 2 completes
    seq_file = _set_fake_sequence(
        tmp_path,
        monkeypatch,
        [
            {"mode": "text", "stdout": "Plan: implement add() and test_add()."},
            {
                "mode": "edit",
                "files": {"src/calc.py": VALID_CALC_PY, "tests/test_calc.py": VALID_TEST_CALC_PY},
            },
            {"mode": "invalid_json", "stdout": "Reviewer crashed output {not valid json"},
            {
                "mode": "edit",
                "files": {"src/calc.py": VALID_CALC_PY, "tests/test_calc.py": VALID_TEST_CALC_PY},
            },
            {"mode": "json", "stdout": '{"verdict":"LGTM","comments":[]}'},
        ],
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_plan_conformance", lambda **_: (True, 1.0, "ok")
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_review_conformance", lambda **_: (True, 1.0, "ok")
    )

    execute_issue(
        "TFG-0099",
        "TFG",
        metadata_dir=l4_env["metadata_dir"],
        history_file=l4_env["history_file"],
        project_root=l4_env["project_root"],
        fresh=True,
    )

    assert _read_sequence_index(seq_file) == 5
    assert _read_state(l4_env)["status"] == "COMPLETED"


def test_l4_004_code_out_of_scope_write_handled_by_edit_guard(
    l4_env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4-004: edit_guard restores out-of-scope tracked edits and removes unauthorized untracked files."""
    seq_file = _set_fake_sequence(
        tmp_path,
        monkeypatch,
        [
            {"mode": "text", "stdout": "Plan: update src/calc.py and tests/test_calc.py."},
            {
                "mode": "unauthorized",
                "files": {
                    "src/calc.py": VALID_CALC_PY,
                    "tests/test_calc.py": VALID_TEST_CALC_PY,
                    "src/untouched.py": "KEEP_ME = 'tampered'\n",
                    "unauthorized.txt": "OUT_OF_SCOPE\n",
                },
            },
            {"mode": "json", "stdout": '{"verdict":"LGTM","comments":[]}'},
        ],
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_plan_conformance", lambda **_: (True, 1.0, "ok")
    )
    monkeypatch.setattr(
        "tools.backends.jev_adapter.verify_review_conformance", lambda **_: (True, 1.0, "ok")
    )

    execute_issue(
        "TFG-0099",
        "TFG",
        metadata_dir=l4_env["metadata_dir"],
        history_file=l4_env["history_file"],
        project_root=l4_env["project_root"],
        fresh=True,
    )

    assert _read_sequence_index(seq_file) == 3
    assert _read_state(l4_env)["status"] == "COMPLETED"

    sat_dir = l4_env["sat_dir"]
    assert (sat_dir / "src" / "untouched.py").read_text(
        encoding="utf-8"
    ) == "KEEP_ME = 'original'\n"
    assert not (sat_dir / "unauthorized.txt").exists()

    committed_files = set(
        _git(sat_dir, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    )
    assert committed_files == {"src/calc.py", "tests/test_calc.py"}


def test_l4_006_jev_unavailable_continues_pipeline_fail_open(
    l4_env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4-006: when JEV Ollama endpoint is unreachable, both plan and review gates fail open and complete."""
    seq_file = _set_fake_sequence(
        tmp_path,
        monkeypatch,
        [
            {"mode": "text", "stdout": "Plan: implement add() and tests."},
            {
                "mode": "edit",
                "files": {"src/calc.py": VALID_CALC_PY, "tests/test_calc.py": VALID_TEST_CALC_PY},
            },
            {"mode": "json", "stdout": '{"verdict":"LGTM","comments":[]}'},
        ],
    )
    # Point JEV to an unreachable local port and reset singleton so real JudgePipeline hits connection error.
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:19999")
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    monkeypatch.setattr(jev_adapter, "_PIPELINE_INSTANCE", None)

    execute_issue(
        "TFG-0099",
        "TFG",
        metadata_dir=l4_env["metadata_dir"],
        history_file=l4_env["history_file"],
        project_root=l4_env["project_root"],
        fresh=True,
    )

    assert _read_sequence_index(seq_file) == 3
    assert _read_state(l4_env)["status"] == "COMPLETED"
    # Ensure singleton does not leak unreachable endpoint into later tests
    jev_adapter._PIPELINE_INSTANCE = None

"""Resume モードの Git 安全性 (Issue #92) のテスト。"""

import json
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import MagicMock, patch

import pytest

from tests.test_consecutive_b7_guard import ISSUE_ID, _write_state
from tests.test_orchestrator_hardening import _setup_satellite
from tools.orchestrator_graph import (
    ProjectLockManager,
    build_wip_pathspec,
    commit_wip_changes,
    execute_issue,
    is_generated_artifact_path,
    porcelain_path,
)

OK = MagicMock(returncode=0, stdout="", stderr="")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (" M src/a.py", "src/a.py"),
        ("?? .pytest_cache/", ".pytest_cache/"),
        ("R  old.py -> new.py", "new.py"),
        ('?? "docs/設計.md"', "docs/設計.md"),
    ],
)
def test_porcelain_path(line: str, expected: str) -> None:
    assert porcelain_path(line) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".aider.chat.history.md", True),
        (".aider.tags.cache.v3/x.db", True),
        (".pytest_cache/", True),
        ("src/__pycache__/mod.cpython-312.pyc", True),
        ("src/mod.pyc", True),
        (".venv/Scripts/python.exe", True),
        (".ruff_cache/", True),
        (".mypy_cache/3.12/x.json", True),
        ("src/a.py", False),
        ("docs/readme.md", False),
        # 部分文字列では除外しない (要素単位で照合する)
        ("docs/my.aider_notes.md", False),
        ("src/pycache_utils.py", False),
    ],
)
def test_is_generated_artifact_path(path: str, expected: bool) -> None:
    assert is_generated_artifact_path(path) is expected


def test_build_wip_pathspec_excludes_artifacts() -> None:
    spec = build_wip_pathspec()

    assert spec[:2] == ["--", "."]
    assert ":(exclude,glob)**/.aider*" in spec
    assert ":(exclude,glob)**/__pycache__/**" in spec
    assert ":(exclude,glob)**/*.pyc" in spec


def _fake_run_cmd(responses: dict[str, MagicMock], executed: list[str]) -> Callable[..., MagicMock]:
    """コマンド文字列に含まれるキーで応答を切り替える run_cmd の代替を返す。"""

    def run(cmd: list[str], cwd: Optional[str] = None, timeout: int = 60) -> MagicMock:
        cmd_str = " ".join(cmd)
        executed.append(cmd_str)
        for key, response in responses.items():
            if key in cmd_str:
                return response
        return OK

    return run


def test_commit_wip_changes_commits_when_staged() -> None:
    executed: list[str] = []
    responses = {"diff --cached --quiet": MagicMock(returncode=1, stdout="", stderr="")}
    with patch("tools.orchestrator_graph.run_cmd", _fake_run_cmd(responses, executed)):
        assert commit_wip_changes("/sat", ISSUE_ID) is None

    assert any(c.startswith("git add -A -- . :(exclude,glob)**/.aider*") for c in executed)
    assert any(c.startswith("git commit -m wip: preserve") for c in executed)


def test_commit_wip_changes_skips_commit_when_nothing_staged() -> None:
    executed: list[str] = []
    with patch("tools.orchestrator_graph.run_cmd", _fake_run_cmd({}, executed)):
        assert commit_wip_changes("/sat", ISSUE_ID) is None

    assert not any(c.startswith("git commit") for c in executed)


def test_commit_wip_changes_reports_add_failure() -> None:
    responses = {"git add": MagicMock(returncode=1, stdout="", stderr="index.lock exists")}
    with patch("tools.orchestrator_graph.run_cmd", _fake_run_cmd(responses, [])):
        error = commit_wip_changes("/sat", ISSUE_ID)

    assert error is not None
    assert "git add failed" in error
    assert "index.lock exists" in error


def test_commit_wip_changes_reports_commit_failure() -> None:
    responses = {
        "diff --cached --quiet": MagicMock(returncode=1, stdout="", stderr=""),
        "git commit": MagicMock(returncode=1, stdout="", stderr="hook failed"),
    }
    with patch("tools.orchestrator_graph.run_cmd", _fake_run_cmd(responses, [])):
        error = commit_wip_changes("/sat", ISSUE_ID)

    assert error is not None
    assert "git commit failed" in error
    assert "hook failed" in error


def _run_resume(
    tmp_path: Path, responses: dict[str, MagicMock]
) -> tuple[list[str], MagicMock, Path]:
    """FAILED_B7 状態の Issue を Resume モードで実行し、(コマンド履歴, mock_app, state.json) を返す。"""
    metadata_dir = _setup_satellite(tmp_path)
    state_file = _write_state(metadata_dir, "FAILED_B7", 0)
    executed: list[str] = []

    with (
        patch.object(ProjectLockManager, "_acquire_lock"),
        patch.object(ProjectLockManager, "_release_lock"),
        patch("tools.orchestrator_graph.is_in_git_workspace", return_value=True),
        patch("tools.orchestrator_graph.run_cmd", _fake_run_cmd(responses, executed)),
        patch("tools.orchestrator_graph.StateGraph") as mock_state_graph,
    ):
        mock_app = MagicMock()
        mock_app.invoke.return_value = {"status": "COMPLETED"}
        mock_state_graph.return_value.compile.return_value = mock_app

        execute_issue(
            ISSUE_ID,
            "TFG",
            metadata_dir=metadata_dir,
            history_file=tmp_path / "tools" / ".cache" / "execution_history.json",
            project_root=tmp_path,
        )
    return executed, mock_app, state_file


def _status(stdout: str) -> dict[str, MagicMock]:
    return {"status --porcelain": MagicMock(returncode=0, stdout=stdout, stderr="")}


def test_resume_wip_commits_real_changes(tmp_path: Path) -> None:
    responses = {
        **_status(" M src/a.py\n"),
        "diff --cached --quiet": MagicMock(returncode=1, stdout="", stderr=""),
    }
    executed, mock_app, _ = _run_resume(tmp_path, responses)

    assert any(c.startswith("git commit -m wip:") for c in executed)
    mock_app.invoke.assert_called_once()


def test_resume_ignores_generated_artifacts_only(tmp_path: Path) -> None:
    """生成物だけが dirty の場合は WIP コミットを作らず Resume を続行する。"""
    executed, mock_app, _ = _run_resume(
        tmp_path, _status("?? .pytest_cache/\n?? src/__pycache__/\n?? .aider.chat.history.md\n")
    )

    assert not any(c.startswith("git add -A") for c in executed)
    assert not any(c.startswith("git commit") for c in executed)
    mock_app.invoke.assert_called_once()


def test_resume_aborts_when_wip_add_fails(tmp_path: Path) -> None:
    responses = {
        **_status(" M src/a.py\n"),
        "git add": MagicMock(returncode=1, stdout="", stderr="index.lock exists"),
    }
    executed, mock_app, state_file = _run_resume(tmp_path, responses)

    mock_app.invoke.assert_not_called()
    assert not any("git switch" in c for c in executed)
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["status"] == "FAILED_SYSTEM"


def test_resume_aborts_when_rebase_fails(tmp_path: Path) -> None:
    responses = {
        **_status(""),
        "git rebase develop": MagicMock(returncode=1, stdout="CONFLICT (content)", stderr=""),
    }
    executed, mock_app, state_file = _run_resume(tmp_path, responses)

    assert any(c == "git rebase --abort" for c in executed)
    mock_app.invoke.assert_not_called()
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[ISSUE_ID]["status"] == "FAILED_SYSTEM"
    history = json.loads(
        (tmp_path / "tools" / ".cache" / "execution_history.json").read_text(encoding="utf-8")
    )
    assert "CONFLICT" in history["records"][-1]["error_message"]

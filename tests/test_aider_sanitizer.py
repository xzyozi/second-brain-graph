"""aider_runner のサニタイザ (Issue #101) のテスト。実際の git リポジトリで検証する。"""

import logging
import os
import subprocess
from pathlib import Path

import pytest

from tools.aider_runner import cleanup_unauthorized_aider_artifacts, warn_if_working_tree_dirty

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=GIT_ENV, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """追跡済みファイルを持つ git リポジトリ。"""
    git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.py").write_text("t = 1\n", encoding="utf-8")
    (tmp_path / "settings.json").write_text('{"a": 1}\n', encoding="utf-8")
    (tmp_path / "other.py").write_text("o = 1\n", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("g\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_tracked_file_modified_outside_targets_is_restored_not_deleted(repo: Path) -> None:
    """追跡済みの無関係ファイルは、削除されず内容が HEAD に戻る。"""
    (repo / "settings.json").write_text('{"a": 2}\n', encoding="utf-8")

    handled = cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert handled == ["settings.json"]
    assert (repo / "settings.json").read_text(encoding="utf-8") == '{"a": 1}\n'
    assert git(repo, "status", "--porcelain") == ""


def test_staged_modification_is_restored(repo: Path) -> None:
    (repo / "other.py").write_text("o = 2\n", encoding="utf-8")
    git(repo, "add", "other.py")

    cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert (repo / "other.py").read_text(encoding="utf-8") == "o = 1\n"
    assert git(repo, "status", "--porcelain") == ""


def test_deleted_tracked_file_is_restored(repo: Path) -> None:
    """追跡済みファイルの削除 (ステージ有無を問わず) が取り消される。"""
    (repo / "gone.txt").unlink()
    git(repo, "rm", "-q", "settings.json")

    cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert (repo / "gone.txt").exists()
    assert (repo / "settings.json").read_text(encoding="utf-8") == '{"a": 1}\n'
    assert git(repo, "status", "--porcelain") == ""


def test_untracked_artifact_is_deleted(repo: Path) -> None:
    (repo / "junk_conversation.md").write_text("junk\n", encoding="utf-8")

    handled = cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert handled == ["junk_conversation.md"]
    assert not (repo / "junk_conversation.md").exists()


def test_newly_staged_file_is_removed(repo: Path) -> None:
    (repo / "staged_new.py").write_text("n = 1\n", encoding="utf-8")
    git(repo, "add", "staged_new.py")

    cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert not (repo / "staged_new.py").exists()
    assert git(repo, "status", "--porcelain") == ""


def test_protected_paths_are_left_alone(repo: Path) -> None:
    """target_files と .aider* / .pytest* / .gitignore は触らない。"""
    (repo / "src" / "target.py").write_text("t = 2\n", encoding="utf-8")
    (repo / ".aider.tags").write_text("x\n", encoding="utf-8")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "v").write_text("1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")

    handled = cleanup_unauthorized_aider_artifacts(str(repo), ["src/target.py"])

    assert handled == []
    assert (repo / "src" / "target.py").read_text(encoding="utf-8") == "t = 2\n"
    assert (repo / ".aider.tags").exists()
    assert (repo / ".gitignore").exists()


def test_cleanup_without_cwd_does_nothing() -> None:
    assert cleanup_unauthorized_aider_artifacts(None, ["a.py"]) == []


def test_warns_when_working_tree_is_dirty_before_aider(
    repo: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (repo / "settings.json").write_text('{"a": 2}\n', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="aider_runner"):
        warn_if_working_tree_dirty(str(repo), ["src/target.py"])

    assert "Working tree is not clean" in caplog.text
    assert "settings.json" in caplog.text


def test_no_warning_when_only_targets_or_aider_files_changed(
    repo: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (repo / "src" / "target.py").write_text("t = 2\n", encoding="utf-8")
    (repo / ".aider.tags").write_text("x\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="aider_runner"):
        warn_if_working_tree_dirty(str(repo), ["src/target.py"])

    assert "Working tree is not clean" not in caplog.text

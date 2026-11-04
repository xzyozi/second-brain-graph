"""Unit tests for tools/edit_guard.py (Issue #125).

Aider / agy 共通の書き込み境界ガード、母艦保護、秘密情報検出、
未追跡ファイル/ディレクトリの削除、追跡済み復元、.gitignore 復元を検証する。
"""

import os
import subprocess
from pathlib import Path

import pytest

from tools.edit_guard import (
    EditGuardError,
    MotherRepositoryProtectionError,
    detect_secret_files,
    prepare_guard,
    rollback_unauthorized_changes,
    validate_cwd_is_satellite,
)

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
def mother_and_satellites(tmp_path: Path) -> tuple[Path, Path]:
    """疑似母艦リポジトリと衛星リポジトリのペアを作成する."""
    mother = tmp_path / "mother"
    mother.mkdir()
    git(mother, "init", "-q")
    (mother / "pyproject.toml").write_text("# mother pyproject", encoding="utf-8")
    (mother / "tools").mkdir()
    (mother / "tools" / "dummy.py").write_text("# tool", encoding="utf-8")
    git(mother, "add", "-A")
    git(mother, "commit", "-q", "-m", "init mother")

    sat = mother / "projects" / "test_satellite"
    sat.mkdir(parents=True)
    git(sat, "init", "-q")
    (sat / "src").mkdir()
    (sat / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (sat / "tracked_outside.py").write_text("orig = True\n", encoding="utf-8")
    (sat / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    git(sat, "add", "-A")
    git(sat, "commit", "-q", "-m", "init satellite")

    return mother, sat


def test_validate_cwd_rejects_mother_root(mother_and_satellites: tuple[Path, Path]) -> None:
    """母艦リポジトリ自身を cwd に指定した場合は拒否される."""
    mother, _ = mother_and_satellites
    with pytest.raises(MotherRepositoryProtectionError, match="母艦リポジトリ.*禁止"):
        validate_cwd_is_satellite(mother, mother_root=mother)


def test_validate_cwd_rejects_mother_subdirectories_outside_projects(
    mother_and_satellites: tuple[Path, Path],
) -> None:
    """母艦配下の tools などの管理ディレクトリを cwd に指定した場合は拒否される."""
    mother, _ = mother_and_satellites
    tools_dir = mother / "tools"
    with pytest.raises(MotherRepositoryProtectionError, match="projects/ 配下の衛星を指定"):
        validate_cwd_is_satellite(tools_dir, mother_root=mother)


def test_validate_cwd_allows_valid_satellite(mother_and_satellites: tuple[Path, Path]) -> None:
    """母艦配下の projects/ 衛星ディレクトリは許可される."""
    mother, sat = mother_and_satellites
    res = validate_cwd_is_satellite(sat, mother_root=mother)
    assert res == sat.resolve()


def test_validate_cwd_allows_external_repository(tmp_path: Path) -> None:
    """母艦外部の独立した git ワークスペースは許可される."""
    ext_repo = tmp_path / "external_repo"
    ext_repo.mkdir()
    git(ext_repo, "init", "-q")
    (ext_repo / "a.txt").write_text("hello", encoding="utf-8")
    git(ext_repo, "add", "-A")
    git(ext_repo, "commit", "-q", "-m", "init")

    res = validate_cwd_is_satellite(ext_repo)
    assert res == ext_repo.resolve()


def test_validate_cwd_requires_non_empty() -> None:
    """cwd が未指定または空文字の場合は EditGuardError."""
    with pytest.raises(EditGuardError, match="must be specified"):
        validate_cwd_is_satellite(None)
    with pytest.raises(EditGuardError, match="must be specified"):
        validate_cwd_is_satellite("")


def test_detect_secret_files(tmp_path: Path) -> None:
    """作業ツリー内の .env や *.pem, token.json などの秘密情報ファイルを検出する."""
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "private.key").write_text("KEY", encoding="utf-8")
    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    (tmp_path / "normal.py").write_text("print()", encoding="utf-8")

    secrets = detect_secret_files(tmp_path)
    assert ".env" in secrets
    assert "sub/private.key" in secrets
    assert "token.json" in secrets
    assert "normal.py" not in secrets


def test_rollback_deletes_untracked_directory(mother_and_satellites: tuple[Path, Path]) -> None:
    """target_files 外に作成された未追跡ディレクトリが丸ごと削除される."""
    mother, sat = mother_and_satellites
    snapshot = prepare_guard(sat, ["src/main.py"], mother_root=mother)

    # 未追跡ディレクトリとファイルを作成
    untracked_dir = sat / "unauthorized_dir"
    untracked_dir.mkdir()
    (untracked_dir / "junk.txt").write_text("junk", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/main.py"])

    assert not untracked_dir.exists()
    assert any("unauthorized_dir" in item for item in report.reverted)


def test_rollback_reverts_tracked_outside_file(mother_and_satellites: tuple[Path, Path]) -> None:
    """target_files 外の追跡済みファイルの変更が HEAD の状態に復元される."""
    mother, sat = mother_and_satellites
    snapshot = prepare_guard(sat, ["src/main.py"], mother_root=mother)

    # 追跡済みファイルを改変
    (sat / "tracked_outside.py").write_text("modified = True\n", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/main.py"])

    assert (sat / "tracked_outside.py").read_text(encoding="utf-8") == "orig = True\n"
    assert "tracked_outside.py" in report.reverted
    assert git(sat, "status", "--porcelain") == ""


def test_rollback_reverts_modified_gitignore(mother_and_satellites: tuple[Path, Path]) -> None:
    """実行中に .gitignore が改変された場合、スナップショット時点の内容に復元される."""
    mother, sat = mother_and_satellites
    snapshot = prepare_guard(sat, ["src/main.py"], mother_root=mother)

    # .gitignore を改変
    (sat / ".gitignore").write_text("*.pyc\n*.log\n# modified\n", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/main.py"])

    assert (sat / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n"
    assert ".gitignore" in report.reverted
    assert git(sat, "status", "--porcelain") == ""


def test_rollback_removes_newly_created_gitignore(tmp_path: Path) -> None:
    """実行前には無かった .gitignore が新規作成された場合、削除される."""
    repo = tmp_path / "repo_no_gi"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("app = 1", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    snapshot = prepare_guard(repo, ["src/app.py"])
    assert snapshot.gitignore_existed is False

    # 新規に .gitignore を作成
    (repo / ".gitignore").write_text(".aider*\n", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/app.py"])

    assert not (repo / ".gitignore").exists()
    assert ".gitignore" in report.reverted


def test_glob_to_regex_and_matches_any_glob() -> None:
    """glob パターンマッチングが正しく判定されることを検証する (Issue #102)."""
    from tools.edit_guard import matches_any_glob

    globs = ["tests/**", "src/**/*.rs", "docs/*.md"]

    assert matches_any_glob("tests/test_foo.py", globs) is True
    assert matches_any_glob("tests/nested/test_bar.py", globs) is True
    assert matches_any_glob("src/sub/worker.rs", globs) is True
    assert matches_any_glob("src/main.rs", globs) is True
    assert matches_any_glob("docs/spec.md", globs) is True
    assert matches_any_glob("docs/nested/spec.md", globs) is False
    assert matches_any_glob("other/junk.txt", globs) is False
    assert matches_any_glob("settings.json", globs) is False


def test_rollback_retains_untracked_file_matching_allowed_new_file_globs(
    mother_and_satellites: tuple[Path, Path],
) -> None:
    """allowed_new_file_globs に一致する未追跡ファイルが保持され、それ以外は削除される (Issue #102)."""
    mother, sat = mother_and_satellites
    snapshot = prepare_guard(
        sat,
        ["src/main.py"],
        allowed_new_file_globs=["tests/**", "src/**/*.rs"],
        mother_root=mother,
    )

    # 1. 許可される未追跡ファイル
    (sat / "tests").mkdir(parents=True, exist_ok=True)
    allowed_test = sat / "tests" / "test_feature.py"
    allowed_test.write_text("def test_ok(): pass\n", encoding="utf-8")

    allowed_rs = sat / "src" / "helper.rs"
    allowed_rs.write_text("pub fn helper() {}\n", encoding="utf-8")

    # 2. 許可されない未追跡ファイル
    unauthorized_file = sat / "unauthorized.txt"
    unauthorized_file.write_text("junk", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/main.py"])

    # 許可されたファイルは保持される
    assert allowed_test.exists()
    assert allowed_rs.exists()
    assert "tests/test_feature.py" in report.retained_new_files
    assert "src/helper.rs" in report.retained_new_files

    # 許可されないファイルは削除される
    assert not unauthorized_file.exists()
    assert any("unauthorized.txt" in item for item in report.reverted)


def test_rollback_reverts_tracked_outside_file_even_if_matching_allowed_globs(
    mother_and_satellites: tuple[Path, Path],
) -> None:
    """追跡済みファイルの変更は allowed_new_file_globs に一致していても target_files 外なら元に戻る (Issue #102)."""
    mother, sat = mother_and_satellites

    # src/main.py 以外の追跡済みファイルを src/ 配下に作成・コミットしておく
    tracked_in_src = sat / "src" / "existing.py"
    tracked_in_src.write_text("version = 1\n", encoding="utf-8")
    git(sat, "add", "-A")
    git(sat, "commit", "-q", "-m", "add existing")

    # allowed_new_file_globs=["src/**"] を指定（新規ファイルのみ許可）
    snapshot = prepare_guard(
        sat,
        ["src/main.py"],
        allowed_new_file_globs=["src/**"],
        mother_root=mother,
    )

    # 追跡済みファイルを改変
    tracked_in_src.write_text("version = 2\n", encoding="utf-8")

    report = rollback_unauthorized_changes(snapshot, ["src/main.py"])

    # 追跡済みファイルは元に戻される
    assert tracked_in_src.read_text(encoding="utf-8") == "version = 1\n"
    assert any("src/existing.py" in item for item in report.reverted)
    assert "src/existing.py" not in report.retained_new_files

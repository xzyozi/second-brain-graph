"""Tests for tools/add_project.py."""

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from tools.add_project import (
    commit_and_push_initial_files,
    detect_git_default_branch,
    ensure_base_branch,
    extract_github_repo,
    register_project,
)


def test_register_project_success(tmp_path: pytest.TempPathFactory) -> None:
    root_dir = str(tmp_path)

    entry = register_project(
        key="MOB",
        name="Mobile App",
        directory="projects/mobile-app",
        base_branch="main",
        description="Mobile test app",
        root_dir=root_dir,
    )

    assert entry["name"] == "Mobile App"
    assert entry["dir"] == "projects/mobile-app"
    assert entry["meta"] == "projects/mobile-app/docs"

    sat_dir = os.path.join(root_dir, "projects", "mobile-app")
    docs_dir = os.path.join(sat_dir, "docs")
    proj_json = os.path.join(docs_dir, "project.json")
    tasks_md = os.path.join(docs_dir, "tasks.md")
    template_md = os.path.join(docs_dir, "issues", "_template.md")
    workflow_file = os.path.join(sat_dir, ".github", "workflows", "issue-auto-tag.yml")
    reg_json = os.path.join(root_dir, "metadata", ".project-registry.json")

    # Host metadata/projects/MOB must NOT exist (Host purification)
    host_meta_dir = os.path.join(root_dir, "metadata", "projects", "MOB")
    assert not os.path.exists(host_meta_dir)

    # Satellite docs/ assets MUST exist
    assert os.path.exists(sat_dir)
    assert os.path.exists(docs_dir)
    assert os.path.exists(proj_json)
    assert os.path.exists(tasks_md)
    assert os.path.exists(template_md)
    assert os.path.exists(reg_json)

    # Satellite auto-tag workflow MUST exist
    assert os.path.exists(workflow_file)
    with open(workflow_file, "r", encoding="utf-8") as f:
        wf_content = f.read()
        assert "stage:ideation" in wf_content
        assert "Auto Label Issues" in wf_content

    with open(proj_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["key"] == "MOB"
        assert data["base_branch"] == "main"
        assert data["description"] == "Mobile test app"

    with open(reg_json, "r", encoding="utf-8") as f:
        reg_data = json.load(f)
        assert "MOB" in reg_data["projects"]
        assert reg_data["projects"]["MOB"]["dir"] == "projects/mobile-app"


def test_register_project_with_repo_url_extracts_github_repo(
    tmp_path: pytest.TempPathFactory,
) -> None:
    root_dir = str(tmp_path)
    # Pre-create sat_dir so git clone is not attempted on dummy URL
    os.makedirs(os.path.join(root_dir, "projects", "srv"), exist_ok=True)

    entry = register_project(
        key="SRV",
        name="Backend Service",
        directory="projects/srv",
        base_branch="develop",
        repo_url="https://github.com/myorg/backend-service.git",
        root_dir=root_dir,
    )

    assert entry["github_repo"] == "myorg/backend-service"

    sat_dir = os.path.join(root_dir, "projects", "srv")
    proj_json = os.path.join(sat_dir, "docs", "project.json")
    reg_json = os.path.join(root_dir, "metadata", ".project-registry.json")

    with open(proj_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["github_repo"] == "myorg/backend-service"

    with open(reg_json, "r", encoding="utf-8") as f:
        reg_data = json.load(f)
        assert reg_data["projects"]["SRV"]["github_repo"] == "myorg/backend-service"


def test_extract_github_repo() -> None:
    assert extract_github_repo("https://github.com/owner/repo.git") == "owner/repo"
    assert extract_github_repo("https://github.com/owner/repo") == "owner/repo"
    assert extract_github_repo("git@github.com:owner/repo.git") == "owner/repo"
    assert extract_github_repo("owner/repo") == "owner/repo"
    assert extract_github_repo(None) is None
    assert extract_github_repo("https://gitlab.com/owner/repo.git") is None


def test_register_project_invalid_key_raises() -> None:
    with pytest.raises(ValueError):
        register_project(key="", name="Invalid Project")


def test_register_project_loads_master_issue_template(tmp_path: pytest.TempPathFactory) -> None:
    root_dir = str(tmp_path)
    # 1. Test fallback when master template not in root_dir
    register_project(
        key="FALL",
        name="Fallback App",
        directory="projects/fallback",
        root_dir=root_dir,
    )
    fallback_tpl = os.path.join(root_dir, "projects", "fallback", "docs", "issues", "_template.md")
    assert os.path.exists(fallback_tpl)
    with open(fallback_tpl, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# [FALL-XXXX]" in content
    assert "## 0. メタ情報 (Scope & Impact)" in content
    assert "## 4. 編集対象ファイル (Target Files)" in content
    assert "## 8. 完了定義 (Definition of Done)" in content
    assert "CI・自動検査に関する運用指針" in content

    # 2. Test master template loading when present
    tpl_dir = os.path.join(root_dir, "metadata", "templates")
    os.makedirs(tpl_dir, exist_ok=True)
    master_file = os.path.join(tpl_dir, "issue_template.md")
    with open(master_file, "w", encoding="utf-8") as f:
        f.write("# [{key}-9999] Custom Master Template\n\n## Custom Section\n")

    register_project(
        key="CUST",
        name="Custom App",
        directory="projects/custom",
        root_dir=root_dir,
    )
    custom_tpl = os.path.join(root_dir, "projects", "custom", "docs", "issues", "_template.md")
    with open(custom_tpl, "r", encoding="utf-8") as f:
        content2 = f.read()
    assert "# [CUST-9999] Custom Master Template" in content2
    assert "## Custom Section" in content2


def test_detect_git_default_branch() -> None:
    # 1. Test symbolic-ref
    def mock_run_sym(cmd: list[str], **kwargs: object) -> MagicMock:
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=0, stdout="origin/main\n")
        return MagicMock(returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run_sym):
        assert detect_git_default_branch("/dummy") == "main"

    # 2. Test origin/master candidate
    def mock_run_master(cmd: list[str], **kwargs: object) -> MagicMock:
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "origin/master" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run_master):
        assert detect_git_default_branch("/dummy") == "master"


def test_ensure_base_branch_creates_from_main_when_missing() -> None:
    executed_cmds = []

    def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
        cmd_str = " ".join(cmd)
        executed_cmds.append(cmd_str)
        if (
            "rev-parse --verify develop" in cmd_str
            or "rev-parse --verify origin/develop" in cmd_str
        ):
            return MagicMock(returncode=1)
        if "rev-parse --verify origin/main" in cmd_str:
            return MagicMock(returncode=0)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("os.path.exists", return_value=True), patch("subprocess.run", side_effect=mock_run):
        branch = ensure_base_branch("/dummy", base_branch="develop")

    assert branch == "develop"
    assert any("git -C /dummy checkout -b develop origin/main" in c for c in executed_cmds)


def test_commit_and_push_initial_files_no_push() -> None:
    executed_cmds = []

    def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
        cmd_str = " ".join(cmd)
        executed_cmds.append(cmd_str)
        if "diff --cached" in cmd_str:
            return MagicMock(returncode=1)  # has staged diff
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("os.path.exists", return_value=True), patch("subprocess.run", side_effect=mock_run):
        success = commit_and_push_initial_files("/dummy", base_branch="develop", push=False)

    assert success is True
    assert any("git -C /dummy commit" in c for c in executed_cmds)
    assert not any("git -C /dummy push" in c for c in executed_cmds)


def test_register_project_git_integration(tmp_path: pytest.TempPathFactory) -> None:
    """ローカル git リポジトリに対する register_project のブランチ作成と初期コミットの検証."""
    root_dir = str(tmp_path)
    sat_dir = os.path.join(root_dir, "projects", "repo_app")
    os.makedirs(sat_dir, exist_ok=True)

    # Initialize a real git repo with a main branch and initial commit
    subprocess.run(["git", "-C", sat_dir, "init", "-b", "main"], check=True)
    subprocess.run(["git", "-C", sat_dir, "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", sat_dir, "config", "user.email", "test@example.com"], check=True)
    dummy_file = os.path.join(sat_dir, "README.md")
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("# Repo App\n")
    subprocess.run(["git", "-C", sat_dir, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", sat_dir, "commit", "-m", "Initial commit on main"], check=True)

    # Register project with develop as base_branch and push=False (no remote)
    entry = register_project(
        key="RAPP",
        name="Repo App",
        directory="projects/repo_app",
        base_branch="develop",
        push=False,
        root_dir=root_dir,
    )

    assert entry["name"] == "Repo App"
    # Check current branch in satellite repo: must be develop (created from main)
    res_br = subprocess.run(
        ["git", "-C", sat_dir, "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res_br.stdout.strip() == "develop"

    # Check git log on develop: must have initial config commit
    res_log = subprocess.run(
        ["git", "-C", sat_dir, "log", "-1", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "chore(init): initialize Second Brain satellite project configuration" in res_log.stdout

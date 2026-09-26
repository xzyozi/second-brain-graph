"""Tests for tools/add_project.py."""

import json
import os

import pytest

from tools.add_project import extract_github_repo, register_project


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


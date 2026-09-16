"""Tests for tools/add_project.py."""

import json
import os

import pytest

from tools.add_project import register_project


def test_register_project_success(tmp_path: pytest.TempPathFactory) -> None:
    root_dir = str(tmp_path)

    entry = register_project(
        key="MOB",
        name="Mobile App",
        directory="projects/mobile-app",
        base_branch="main",
        root_dir=root_dir,
    )

    assert entry["name"] == "Mobile App"
    assert entry["dir"] == "projects/mobile-app"
    assert entry["meta"] == "metadata/projects/MOB"

    sat_dir = os.path.join(root_dir, "projects", "mobile-app")
    meta_dir = os.path.join(root_dir, "metadata", "projects", "MOB")
    proj_json = os.path.join(meta_dir, "project.json")
    tasks_md = os.path.join(meta_dir, "tasks.md")
    reg_json = os.path.join(root_dir, "metadata", ".project-registry.json")

    assert os.path.exists(sat_dir)
    assert os.path.exists(meta_dir)
    assert os.path.exists(proj_json)
    assert os.path.exists(tasks_md)
    assert os.path.exists(reg_json)

    with open(proj_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["key"] == "MOB"
        assert data["base_branch"] == "main"

    with open(reg_json, "r", encoding="utf-8") as f:
        reg_data = json.load(f)
        assert "MOB" in reg_data["projects"]


def test_register_project_invalid_key_raises() -> None:
    with pytest.raises(ValueError):
        register_project(key="", name="Invalid Project")

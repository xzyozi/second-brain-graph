"""CLI Tool for adding a new satellite project to Second Brain OS.

SBOS-MULTI-001 Rev.3.0 compliant (Host Purification & Satellite Docs Ownership).
Initializes metadata files (project.json, tasks.md, issues/) directly inside the satellite's
docs/ directory (projects/<name>/docs/) and registers the project into metadata/.project-registry.json.
The host repository's metadata/ directory remains pure and unpolluted.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ISSUE_TEMPLATE_CONTENT = """# [{key}-XXXX] Issueタイトル

## 概要・目的

## 要求仕様

## 受入条件 (Acceptance Criteria)
- [ ]

## 変更対象想定ファイル
-
"""


def register_project(
    key: str,
    name: str,
    directory: str = "",
    base_branch: str = "develop",
    description: str = "",
    repo_url: Optional[str] = None,
    root_dir: str = ".",
) -> Dict[str, Any]:
    """Register a new satellite project into Second Brain OS."""
    key = key.strip().upper()
    name = name.strip()
    if not key or not name:
        raise ValueError("Project key and name must not be empty.")

    if not directory:
        directory = f"projects/{key.lower()}"

    sat_path = os.path.join(root_dir, directory)

    # 1. Clone repository if repo_url provided and directory does not exist
    if repo_url and not os.path.exists(sat_path):
        logger.info(f"Cloning repository {repo_url} into {sat_path}...")
        try:
            subprocess.run(["git", "clone", repo_url, sat_path], check=True)
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            raise

    # 2. Ensure satellite root and docs directory exist
    docs_path = os.path.join(sat_path, "docs")
    os.makedirs(docs_path, exist_ok=True)
    logger.info(f"Ensured satellite docs directory: {docs_path}")

    # 3. Create satellite docs/project.json (SSOT)
    proj_json_path = os.path.join(docs_path, "project.json")
    if not os.path.exists(proj_json_path):
        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        proj_data = {
            "key": key,
            "name": name,
            "base_branch": base_branch,
            "created_at": now_date,
            "description": description or f"{name} satellite project",
        }
        with open(proj_json_path, "w", encoding="utf-8") as f:
            json.dump(proj_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Initialized satellite project config at {proj_json_path}")
    else:
        logger.info(f"Satellite project config already exists at {proj_json_path}")

    # 4. Create satellite docs/tasks.md if not present
    tasks_md_path = os.path.join(docs_path, "tasks.md")
    if not os.path.exists(tasks_md_path):
        with open(tasks_md_path, "w", encoding="utf-8") as f:
            f.write("# Tasks\n\n")
        logger.info(f"Initialized tasks.md at {tasks_md_path}")
    else:
        logger.info(f"Satellite tasks.md already exists at {tasks_md_path}")

    # 5. Create satellite docs/issues/ and _template.md
    issues_dir = os.path.join(docs_path, "issues")
    os.makedirs(issues_dir, exist_ok=True)
    template_path = os.path.join(issues_dir, "_template.md")
    if not os.path.exists(template_path):
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(ISSUE_TEMPLATE_CONTENT.format(key=key))
        logger.info(f"Initialized issue template at {template_path}")

    # 6. Update host metadata/.project-registry.json
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    registry: Dict[str, Any] = {"version": "1.0", "projects": {}}
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception as e:
            logger.warning(f"Could not parse existing registry, starting fresh: {e}")

    registry.setdefault("projects", {})
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Save relative posix-style paths for directory
    rel_dir = os.path.normpath(directory).replace("\\", "/")
    meta_rel = f"{rel_dir}/docs"

    registry["projects"][key] = {
        "name": name,
        "dir": rel_dir,
        "meta": meta_rel,
        "registered_at": now_iso,
    }

    tmp_reg = reg_path + ".tmp"
    with open(tmp_reg, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    os.replace(tmp_reg, reg_path)
    logger.info(f"Successfully registered '{key}' into {reg_path}")

    return registry["projects"][key]


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Add a new satellite project to Second Brain OS (Satellite Docs Ownership)."
    )
    parser.add_argument(
        "--key", "-k", required=True, help="Project ID key prefix (e.g. EC, MOB, NEW)"
    )
    parser.add_argument("--name", "-n", required=True, help="Human-readable project name")
    parser.add_argument(
        "--dir", "-d", default="", help="Satellite directory path (e.g. projects/new-service)"
    )
    parser.add_argument(
        "--base-branch", "-b", default="develop", help="Base branch name (default: develop)"
    )
    parser.add_argument("--desc", default="", help="Project description")
    parser.add_argument("--repo", default=None, help="Git repository URL to clone if not present")

    args = parser.parse_args()

    try:
        entry = register_project(
            key=args.key,
            name=args.name,
            directory=args.dir,
            base_branch=args.base_branch,
            description=args.desc,
            repo_url=args.repo,
            root_dir=".",
        )
        print(
            f"Project '{args.key}' successfully registered: {json.dumps(entry, ensure_ascii=False)}"
        )
    except Exception as e:
        logger.error(f"Failed to register project: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

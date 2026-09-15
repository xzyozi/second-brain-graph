"""CLI Tool for adding a new satellite project to Second Brain OS.

SBOS-MULTI-001 §5 & PM-004 compliant.
Creates satellite directories, initializes metadata files (project.json, tasks.md),
and registers the project into metadata/.project-registry.json.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def register_project(
    key: str,
    name: str,
    directory: str = "",
    base_branch: str = "develop",
    root_dir: str = ".",
) -> Dict[str, Any]:
    """Register a new satellite project."""
    key = key.strip().upper()
    name = name.strip()
    if not key or not name:
        raise ValueError("Project key and name must not be empty.")

    if not directory:
        directory = f"projects/{key.lower()}"

    # 1. Create satellite directory
    sat_path = os.path.join(root_dir, directory)
    os.makedirs(sat_path, exist_ok=True)
    logger.info(f"Ensured satellite directory: {sat_path}")

    # 2. Create metadata directory
    meta_rel = os.path.join("metadata", "projects", key)
    meta_path = os.path.join(root_dir, meta_rel)
    os.makedirs(meta_path, exist_ok=True)
    logger.info(f"Ensured metadata directory: {meta_path}")

    # 3. Create project.json
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proj_json_path = os.path.join(meta_path, "project.json")
    proj_data = {
        "name": name,
        "key": key,
        "base_branch": base_branch,
        "created_at": now_date,
    }
    with open(proj_json_path, "w", encoding="utf-8") as f:
        json.dump(proj_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved project metadata to {proj_json_path}")

    # 4. Create tasks.md if not present
    tasks_md_path = os.path.join(meta_path, "tasks.md")
    if not os.path.exists(tasks_md_path):
        with open(tasks_md_path, "w", encoding="utf-8") as f:
            f.write("# タスク一覧\n\n")
        logger.info(f"Initialized tasks.md at {tasks_md_path}")

    # 5. Update metadata/.project-registry.json
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
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

    registry["projects"][key] = {
        "name": name,
        "dir": rel_dir,
        "meta": meta_rel.replace("\\", "/"),
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
        description="Add a new satellite project to Second Brain OS."
    )
    parser.add_argument(
        "--key", "-k", required=True, help="Project ID key prefix (e.g. EC, MOB, NEW)"
    )
    parser.add_argument(
        "--name", "-n", required=True, help="Human-readable project name"
    )
    parser.add_argument(
        "--dir", "-d", default="", help="Satellite directory path (e.g. projects/new-service)"
    )
    parser.add_argument(
        "--base-branch", "-b", default="develop", help="Base branch name (default: develop)"
    )

    args = parser.parse_args()

    try:
        entry = register_project(
            key=args.key,
            name=args.name,
            directory=args.dir,
            base_branch=args.base_branch,
            root_dir=".",
        )
        print(f"Project '{args.key}' successfully registered: {json.dumps(entry, ensure_ascii=False)}")
    except Exception as e:
        logger.error(f"Failed to register project: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

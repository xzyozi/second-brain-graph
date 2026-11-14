"""CLI Tool for adding a new satellite project to Second Brain OS.

SBOS-MULTI-001 Rev.3.0 compliant (Host Purification & GitHub Issues SSOT).
Initializes metadata file (project.json) directly inside the satellite's
docs/ directory (projects/<name>/docs/) and registers the project into metadata/.project-registry.json.
The host repository's metadata/ directory remains pure and unpolluted.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools.workspace.metadata_store import SUPPORTED_LANGUAGES

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


ISSUE_AUTO_TAG_WORKFLOW = """name: Auto Label Issues

on:
  issues:
    types: [opened]

permissions:
  issues: write

jobs:
  auto-label:
    runs-on: ubuntu-latest
    steps:
      - name: Add stage:ideation label
        uses: actions/github-script@v7
        with:
          script: |
            const issue = context.payload.issue;
            const title = (issue.title || '').toLowerCase();
            const labelsToAdd = ['stage:ideation'];

            if (title.includes('[feat]') || title.includes('feat:')) {
              labelsToAdd.push('enhancement');
            } else if (title.includes('[fix]') || title.includes('fix:')) {
              labelsToAdd.push('bug');
            } else if (title.includes('[docs]') || title.includes('docs:')) {
              labelsToAdd.push('documentation');
            }

            await github.rest.issues.addLabels({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: issue.number,
              labels: labelsToAdd
            });
"""

STANDARD_STAGE_LABELS = [
    ("stage:ideation", "cfd3d7", "構想・壁打ち中（実装対象外）"),
    ("stage:ready", "0e8a16", "仕様確定・着手可能（自律開発対象）"),
    ("stage:in-progress", "fbca04", "エージェント実装・作業中"),
    ("stage:done", "1d76db", "完了・マージ済み"),
    ("theme:security", "d93f0b", "セキュリティ脆弱性・安全対策"),
    ("theme:edge_cases", "e99695", "エッジケース・異常系堅牢化"),
    ("theme:architecture", "bfd4f2", "関心事の分離・構造改善"),
]


def extract_github_repo(url: Optional[str]) -> Optional[str]:
    """Extract owner/repo from GitHub URL or git remote string."""
    if not url:
        return None
    url = url.strip()
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", url):
        return url
    return None


def extract_repo_name(url_or_repo: Optional[str]) -> Optional[str]:
    """Extract repository name (basename) from git URL or owner/repo shorthand."""
    if not url_or_repo:
        return None
    cleaned = url_or_repo.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if "/" in cleaned:
        return cleaned.split("/")[-1]
    if ":" in cleaned:
        return cleaned.split(":")[-1]
    return cleaned


def normalize_git_url(url_or_repo: Optional[str]) -> Optional[str]:
    """Normalize owner/repo shorthand to full GitHub HTTPS URL."""
    if not url_or_repo:
        return None
    cleaned = url_or_repo.strip()
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", cleaned):
        return f"https://github.com/{cleaned}"
    return cleaned


def get_git_remote_url(repo_dir: str) -> Optional[str]:
    """Get remote origin URL of a git directory if present."""
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        return None
    try:
        res = subprocess.run(
            ["git", "-C", repo_dir, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return None


def detect_git_default_branch(repo_dir: str) -> str:
    """Detect default branch of the git repository (e.g. main, master)."""
    # 1. Try remote symbolic-ref
    try:
        res = subprocess.run(
            ["git", "-C", repo_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            ref = str(res.stdout).strip()
            if "/" in ref:
                return ref.split("/", 1)[1]
            if ref:
                return ref
    except Exception:
        pass

    # 2. Check if origin/main or origin/master exists
    for candidate in ["origin/main", "origin/master"]:
        res = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--verify", candidate],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return candidate.replace("origin/", "")

    # 3. Check local main or master
    for candidate in ["main", "master"]:
        res = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--verify", candidate],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return candidate

    # 4. Fallback to current branch or "main"
    try:
        res = subprocess.run(
            ["git", "-C", repo_dir, "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            cur = str(res.stdout).strip()
            if cur:
                return cur
    except Exception:
        pass

    return "main"


def ensure_base_branch(repo_dir: str, base_branch: str = "develop") -> str:
    """Ensure base branch exists in the satellite repo.
    If base_branch (e.g. develop) does not exist, create it from default branch (e.g. main).
    """
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        logger.debug(f"{repo_dir} is not a git repository. Skipping branch setup.")
        return base_branch

    # Try fetching origin to have latest remote refs
    subprocess.run(
        ["git", "-C", repo_dir, "fetch", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Check if local base_branch exists
    res_local = subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "--verify", base_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_local.returncode == 0:
        subprocess.run(
            ["git", "-C", repo_dir, "checkout", base_branch],
            capture_output=True,
            text=True,
            check=False,
        )
        logger.info(f"Checked out existing local branch '{base_branch}' in {repo_dir}")
        return base_branch

    # Check if remote base_branch exists
    res_remote = subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "--verify", f"origin/{base_branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_remote.returncode == 0:
        res_chk = subprocess.run(
            ["git", "-C", repo_dir, "checkout", "-b", base_branch, f"origin/{base_branch}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res_chk.returncode == 0:
            logger.info(
                f"Created and checked out '{base_branch}' tracking 'origin/{base_branch}' in {repo_dir}"
            )
            return base_branch

    # Neither local nor remote base_branch exists: create from default branch (e.g. main)
    default_branch = detect_git_default_branch(repo_dir)
    start_point = f"origin/{default_branch}"
    res_sp = subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "--verify", start_point],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_sp.returncode != 0:
        start_point = default_branch

    res_create = subprocess.run(
        ["git", "-C", repo_dir, "checkout", "-b", base_branch, start_point],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_create.returncode == 0:
        logger.info(f"Created base_branch '{base_branch}' from '{start_point}' in {repo_dir}")
    else:
        logger.warning(
            f"Failed to create '{base_branch}' from '{start_point}': {res_create.stderr.strip()}"
        )

    return base_branch


def commit_and_push_initial_files(
    repo_dir: str,
    base_branch: str = "develop",
    push: bool = True,
) -> bool:
    """Stage generated metadata/workflows, commit them to base_branch, and optionally push to origin."""
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        return False

    stage_paths = []
    if os.path.exists(os.path.join(repo_dir, "docs")):
        stage_paths.append("docs")
    if os.path.exists(os.path.join(repo_dir, ".github")):
        stage_paths.append(".github")

    if not stage_paths:
        return False

    subprocess.run(
        ["git", "-C", repo_dir, "add"] + stage_paths,
        capture_output=True,
        text=True,
        check=False,
    )

    # Check if there are staged changes
    res_diff = subprocess.run(
        ["git", "-C", repo_dir, "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_diff.returncode != 0:
        commit_msg = "chore(init): initialize Second Brain satellite project configuration"
        res_commit = subprocess.run(
            ["git", "-C", repo_dir, "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
            check=False,
        )
        if res_commit.returncode == 0:
            logger.info(f"Committed initial configuration files in {repo_dir}")
        else:
            logger.warning(f"Could not commit initial configuration: {res_commit.stderr.strip()}")
            return False
    else:
        logger.info(f"No new changes to commit in {repo_dir}")

    if not push:
        logger.info(f"Push skipped (--no-push specified) for {repo_dir}")
        return True

    res_push = subprocess.run(
        ["git", "-C", repo_dir, "push", "-u", "origin", base_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if res_push.returncode == 0:
        logger.info(
            f"Successfully pushed initial configuration to origin/{base_branch} in {repo_dir}"
        )
        return True
    else:
        logger.warning(
            f"Could not push to origin/{base_branch} in {repo_dir}: {res_push.stderr.strip()}\n"
            f"Please manually push using: git -C {repo_dir} push -u origin {base_branch}"
        )
        return False


def setup_satellite_workflow(sat_path: str) -> str:
    """Ensure .github/workflows/issue-auto-tag.yml exists in the satellite repository."""
    wf_dir = os.path.join(sat_path, ".github", "workflows")
    os.makedirs(wf_dir, exist_ok=True)
    wf_file = os.path.join(wf_dir, "issue-auto-tag.yml")
    if not os.path.exists(wf_file):
        with open(wf_file, "w", encoding="utf-8") as f:
            f.write(ISSUE_AUTO_TAG_WORKFLOW)
        logger.info(f"Initialized satellite auto-tag workflow at {wf_file}")
    else:
        logger.info(f"Satellite auto-tag workflow already exists at {wf_file}")
    return wf_file


def setup_github_labels(github_repo: str) -> None:
    """Create standard stage labels on the satellite GitHub repository if gh CLI is available."""
    for name, color, desc in STANDARD_STAGE_LABELS:
        try:
            subprocess.run(
                [
                    "gh",
                    "label",
                    "create",
                    name,
                    "--color",
                    color,
                    "--description",
                    desc,
                    "--repo",
                    github_repo,
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Ensured label '{name}' in {github_repo}")
        except Exception as e:
            logger.debug(f"Could not setup label '{name}' in {github_repo}: {e}")


def register_project(
    key: str,
    name: Optional[str] = None,
    directory: str = "",
    base_branch: str = "develop",
    description: str = "",
    repo_url: Optional[str] = None,
    github_repo: Optional[str] = None,
    setup_labels: bool = True,
    push: bool = True,
    language: str = "python",
    test_command: str = "",
    root_dir: str = ".",
) -> Dict[str, Any]:
    """Register a new satellite project into Second Brain OS."""
    if not key or not key.strip():
        raise ValueError("Project key must not be empty.")
    key = key.strip().upper()
    norm_lang = (language or "python").strip().lower()
    if norm_lang not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{language}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )

    # Normalize Git URL and extract repo name
    normalized_url = normalize_git_url(repo_url)
    repo_name = extract_repo_name(normalized_url) or extract_repo_name(github_repo)

    # Auto-derive project name if omitted
    if not name or not name.strip():
        name = repo_name or key.lower()
    else:
        name = name.strip()

    # Auto-derive directory path if omitted
    if not directory:
        if repo_name:
            directory = f"projects/{repo_name}"
        else:
            directory = f"projects/{key.lower()}"

    sat_path = os.path.join(root_dir, directory)

    # 1. Clone repository if repo_url provided and directory does not exist
    if normalized_url and not os.path.exists(sat_path):
        logger.info(f"Cloning repository {normalized_url} into {sat_path}...")
        try:
            subprocess.run(["git", "clone", normalized_url, sat_path], check=True)
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            raise

    # Determine github_repo from parameter, repo_url, or satellite git remote
    resolved_github_repo = github_repo or extract_github_repo(normalized_url)
    if not resolved_github_repo and os.path.exists(sat_path):
        remote_url = get_git_remote_url(sat_path)
        resolved_github_repo = extract_github_repo(remote_url)

    # 2. Ensure satellite is on base_branch (create from default branch if not exists)
    if os.path.exists(os.path.join(sat_path, ".git")):
        ensure_base_branch(sat_path, base_branch=base_branch)

    # 3. Ensure satellite root and docs directory exist
    docs_path = os.path.join(sat_path, "docs")
    os.makedirs(docs_path, exist_ok=True)
    logger.info(f"Ensured satellite docs directory: {docs_path}")

    # 4. Create satellite docs/project.json (SSOT)
    proj_json_path = os.path.join(docs_path, "project.json")
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proj_data: Dict[str, Any] = {}
    if os.path.exists(proj_json_path):
        try:
            with open(proj_json_path, "r", encoding="utf-8") as f:
                proj_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load existing project.json: {e}")

    proj_data["key"] = key
    proj_data["name"] = name
    proj_data["base_branch"] = proj_data.get("base_branch", base_branch)
    proj_data["created_at"] = proj_data.get("created_at", now_date)
    proj_data["description"] = description or proj_data.get(
        "description", f"{name} satellite project"
    )
    proj_data["language"] = norm_lang
    if test_command:
        proj_data["test_command"] = test_command.strip()
    if resolved_github_repo:
        proj_data["github_repo"] = resolved_github_repo

    with open(proj_json_path, "w", encoding="utf-8") as f:
        json.dump(proj_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Updated satellite project config at {proj_json_path}")

    # 5. Ensure satellite has issue auto-tagging workflow (.github/workflows/issue-auto-tag.yml)
    setup_satellite_workflow(sat_path)

    # 6. Ensure satellite .gitignore has language-specific generated entries
    if os.path.exists(sat_path):
        try:
            gi_path = os.path.join(sat_path, ".gitignore")
            if os.path.exists(gi_path):
                with open(gi_path, "r", encoding="utf-8") as f:
                    gi_content = f.read()
                from tools.doctor import _missing_gitignore_for_lang

                needed = _missing_gitignore_for_lang(gi_content, language=norm_lang)
                if needed:
                    with open(gi_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"\n# Autonomous worker ignores ({norm_lang})\n"
                            + "\n".join(needed)
                            + "\n"
                        )
                    logger.info(f"Updated satellite .gitignore with {needed}")
        except Exception as e:
            logger.debug(f"Could not update satellite .gitignore: {e}")

    # 9. Commit and push initial files to base_branch in satellite repo
    if os.path.exists(os.path.join(sat_path, ".git")):
        commit_and_push_initial_files(sat_path, base_branch=base_branch, push=push)

    # 10. Optionally setup standard GitHub labels on satellite repository
    if setup_labels and resolved_github_repo:
        setup_github_labels(resolved_github_repo)

    # 11. Update host metadata/.project-registry.json
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

    entry: Dict[str, Any] = {
        "name": name,
        "dir": rel_dir,
        "meta": meta_rel,
        "registered_at": now_iso,
    }
    if resolved_github_repo:
        entry["github_repo"] = resolved_github_repo

    registry["projects"][key] = entry

    tmp_reg = reg_path + ".tmp"
    with open(tmp_reg, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    os.replace(tmp_reg, reg_path)
    logger.info(f"Successfully registered '{key}' into {reg_path}")

    return registry["projects"][key]


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Add a new satellite project to Second Brain OS (Git URL Driven)."
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Git repository URL (e.g. https://github.com/owner/repo) or owner/repo shorthand (Positional argument)",
    )
    parser.add_argument(
        "--key", "-k", required=True, help="Project ID key prefix (e.g. EC, MOB, NEW)"
    )
    parser.add_argument(
        "--name",
        "-n",
        default=None,
        help="Human-readable project name (auto-inferred from repo name if omitted)",
    )
    parser.add_argument(
        "--dir",
        "-d",
        default="",
        help="Satellite directory path (e.g. projects/new-service, auto-inferred to projects/<repo> if omitted)",
    )
    parser.add_argument(
        "--base-branch", "-b", default="develop", help="Base branch name (default: develop)"
    )
    parser.add_argument("--desc", default="", help="Project description")
    parser.add_argument(
        "--repo",
        default=None,
        help="Git repository URL to clone if not present (alternative to positional target)",
    )
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository name in 'owner/repo' format (auto-inferred from Git URL if omitted)",
    )
    parser.add_argument(
        "--setup-labels",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Setup standard stage and theme labels on the satellite GitHub repository via gh CLI (default: True)",
    )
    parser.add_argument(
        "--language",
        "-l",
        default="python",
        choices=list(SUPPORTED_LANGUAGES),
        help=f"Satellite programming language (default: python, choices: {', '.join(SUPPORTED_LANGUAGES)})",
    )
    parser.add_argument(
        "--test-cmd",
        default="",
        help="Custom test command (e.g. 'npm test', 'cargo test')",
    )
    parser.add_argument(
        "--push",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Commit and push initial satellite files to origin base_branch (default: True)",
    )

    args = parser.parse_args()

    repo_input = normalize_git_url(args.target or args.repo)

    try:
        entry = register_project(
            key=args.key,
            name=args.name,
            directory=args.dir,
            base_branch=args.base_branch,
            description=args.desc,
            repo_url=repo_input,
            github_repo=args.github_repo,
            setup_labels=args.setup_labels,
            push=args.push,
            language=args.language,
            test_command=args.test_cmd,
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

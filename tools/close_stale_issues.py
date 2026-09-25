"""Close stale ideation issues batch script.

Finds issues with 'stage:ideation' label that have not been updated for N days (default: 30),
and closes them immediately without warning.
Can be run locally or via GitHub Actions (with GITHUB_TOKEN).
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def is_stale_issue(
    updated_at_str: str, days_threshold: int = 30, now_dt: Optional[datetime] = None
) -> Tuple[bool, int]:
    """Check if an issue is stale based on its updatedAt timestamp.

    Returns (is_stale, elapsed_days).
    """
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    # GitHub ISO 8601 format: 2026-09-24T08:42:31Z
    try:
        # Handle trailing Z
        clean_str = updated_at_str.replace("Z", "+00:00")
        updated_dt = datetime.fromisoformat(clean_str)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning(f"Failed to parse timestamp '{updated_at_str}': {e}")
        return False, 0

    elapsed_seconds = (now_dt - updated_dt).total_seconds()
    elapsed_days = int(elapsed_seconds // 86400)
    is_stale = elapsed_days >= days_threshold
    return is_stale, elapsed_days


def fetch_ideation_issues(repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch open issues with 'stage:ideation' label using gh CLI."""
    cmd = [
        "gh",
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        "stage:ideation",
        "--json",
        "number,title,updatedAt,createdAt,labels",
        "--limit",
        "200",
    ]
    if repo:
        cmd.extend(["--repo", repo])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issues = json.loads(res.stdout)
        return issues
    except subprocess.CalledProcessError as e:
        logger.error(f"gh command failed: {e.stderr}")
        return []
    except Exception as e:
        logger.error(f"Error fetching issues: {e}")
        return []


def close_issue(
    issue_number: int,
    elapsed_days: int,
    dry_run: bool = False,
    repo: Optional[str] = None,
) -> bool:
    """Close a stale issue with an explanatory comment."""
    comment = f"【自動クローズ】`stage:ideation`（構想・壁打ち）のまま {elapsed_days} 日間更新がなかったため、自動クローズしました。"

    if dry_run:
        logger.info(
            f"[DRY-RUN] Would close Issue #{issue_number} (elapsed {elapsed_days} days): {comment}"
        )
        return True

    cmd = [
        "gh",
        "issue",
        "close",
        str(issue_number),
        "--comment",
        comment,
    ]
    if repo:
        cmd.extend(["--repo", repo])

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Closed Issue #{issue_number} successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to close Issue #{issue_number}: {e.stderr}")
        return False


def process_stale_issues(
    days_threshold: int = 30,
    dry_run: bool = False,
    repo: Optional[str] = None,
    now_dt: Optional[datetime] = None,
) -> List[int]:
    """Find and close all stale ideation issues. Returns list of closed issue numbers."""
    issues = fetch_ideation_issues(repo=repo)
    logger.info(f"Fetched {len(issues)} open 'stage:ideation' issues.")

    closed_numbers: List[int] = []
    for iss in issues:
        num = iss.get("number")
        updated_at = iss.get("updatedAt")
        title = iss.get("title", "")

        if not num or not updated_at:
            continue

        is_stale, elapsed = is_stale_issue(updated_at, days_threshold=days_threshold, now_dt=now_dt)
        if is_stale:
            logger.info(
                f"Stale Issue #{num} '{title}' detected (inactive for {elapsed} days >= {days_threshold} days)."
            )
            success = close_issue(num, elapsed, dry_run=dry_run, repo=repo)
            if success:
                closed_numbers.append(num)

    return closed_numbers


def main() -> None:
    parser = argparse.ArgumentParser(description="Close stale ideation issues without warning.")
    parser.add_argument(
        "--days", type=int, default=30, help="Days threshold for inactivity (default: 30)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate without closing issues")
    parser.add_argument("--repo", type=str, default=None, help="GitHub repository (owner/repo)")
    args = parser.parse_args()

    closed = process_stale_issues(days_threshold=args.days, dry_run=args.dry_run, repo=args.repo)
    logger.info(f"Process completed. Total closed issues: {len(closed)}")


if __name__ == "__main__":
    main()

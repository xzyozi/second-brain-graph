"""Issue Screening Tool with JEV integration.

Scans all GitHub Issues (open and closed), detects potential duplicates/similar issues,
and categorizes them into appropriate area/type labels using JEV / heuristic scoring.
Can post findings as issue comments and apply recommended labels when --apply is specified.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# JEV adapter import
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.jev_adapter import (  # noqa: E402
    JudgeRequestDTO,
    JudgeResponseDTO,
    get_jev_pipeline,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Category definitions and associated keywords
CATEGORY_MAP: Dict[str, List[str]] = {
    "area:orch": [
        "orchestrator",
        "graph",
        "langgraph",
        "node",
        "review_node",
        "planner",
        "run_task",
    ],
    "area:jev": [
        "jev",
        "noul",
        "zero-decode",
        "logit",
        "confidence",
        "検問",
        "gate",
        "conformance",
    ],
    "area:ci": [
        "ci",
        "github actions",
        "actions",
        "workflow",
        "ci/ops",
        "automation",
        "regression",
    ],
    "area:safety": ["safety", "回帰テスト", "regression test", "defense", "yagni", "dod", "保証"],
    "area:docs": ["doc", "docs", "設計書", "仕様書", "markdown", "ドキュメント", "readme"],
}

DUPLICATE_CHECK_POLICY = (
    "2つのタスク・Issue（Issue A と Issue B）の内容を比較し、これらが実質的に同一の目的・要求、"
    "または高度に重複する課題を扱っているか（重複起票・車輪の再発明であるか）を判定せよ。\n"
    "単に関連する同じ領域であるというだけでは不適合（No）とし、"
    "解決しようとしている本質的な課題や実装仕様が実質的に重複している場合のみ適合（Yes）と判定せよ。"
)


def tokenize(text: str) -> Set[str]:
    """Simple alphanumeric and Japanese word tokenization for similarity comparison."""
    # Split by whitespace, punctuation, brackets
    tokens = re.findall(
        r"[A-Za-z0-9_-]+|[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]{2,}", text.lower()
    )
    # Exclude common stopwords
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "in",
        "to",
        "for",
        "of",
        "and",
        "or",
        "feat",
        "fix",
        "add",
        "issue",
        "こと",
        "ため",
        "追加",
        "実装",
    }
    return {t for t in tokens if t not in stopwords and len(t) >= 2}


def calculate_jaccard_similarity(text_a: str, text_b: str) -> float:
    """Calculate Jaccard similarity between two texts."""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    return len(intersection) / len(union)


def verify_duplicate_with_jev(
    issue_a_title: str,
    issue_a_body: str,
    issue_b_title: str,
    issue_b_body: str,
    pipeline: Optional[Any] = None,
) -> Tuple[bool, float]:
    """Verify if two issues are duplicates using JEV Zero-Decode NoulTask.

    Returns (is_duplicate, confidence).
    """
    pipe = pipeline or get_jev_pipeline()
    if pipe is None:
        # Fallback to lexical Jaccard
        lex_sim = calculate_jaccard_similarity(
            f"{issue_a_title} {issue_a_body}",
            f"{issue_b_title} {issue_b_body}",
        )
        return (lex_sim >= 0.5), lex_sim

    context_text = (
        f"【Issue A】\nタイトル: {issue_a_title}\n本文: {issue_a_body[:1000]}\n\n"
        f"【Issue B】\nタイトル: {issue_b_title}\n本文: {issue_b_body[:1000]}"
    )

    request = JudgeRequestDTO(
        task_type="noul",
        context_text=context_text,
        rule_definition=DUPLICATE_CHECK_POLICY,
    )

    try:
        response: JudgeResponseDTO = pipe.judge(request)
        if response.status == "SUCCESS":
            is_dup = response.verdict == "Yes"
            conf = response.confidence if response.confidence is not None else 1.0
            return is_dup, conf
    except Exception as e:
        logger.warning(f"JEV duplicate check failed: {e}")

    # Fallback
    lex_sim = calculate_jaccard_similarity(
        f"{issue_a_title} {issue_a_body}",
        f"{issue_b_title} {issue_b_body}",
    )
    return (lex_sim >= 0.5), lex_sim


def infer_categories(title: str, body: str) -> List[str]:
    """Infer recommended category labels based on title and body keywords."""
    full_text = f"{title} {body}".lower()
    scores: Dict[str, int] = {}

    for cat, keywords in CATEGORY_MAP.items():
        score = sum(1 for kw in keywords if kw in full_text)
        if score > 0:
            scores[cat] = score

    if not scores:
        return []

    # Sort categories by score descending
    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [cat for cat, _ in sorted_cats]


def fetch_all_issues(repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all issues (open and closed) via gh CLI."""
    cmd = [
        "gh",
        "issue",
        "list",
        "--state",
        "all",
        "--json",
        "number,title,labels,body,state,updatedAt,createdAt",
        "--limit",
        "200",
    ]
    if repo:
        cmd.extend(["--repo", repo])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to fetch issues: {e.stderr}")
        return []
    except Exception as e:
        logger.error(f"Error fetching issues: {e}")
        return []


def screen_single_issue(
    target_issue: Dict[str, Any],
    all_issues: List[Dict[str, Any]],
    pipeline: Optional[Any] = None,
) -> Dict[str, Any]:
    """Screen an issue against all other issues for duplicates and categorize."""
    t_num = target_issue.get("number", 0)
    t_title = target_issue.get("title", "")
    t_body = target_issue.get("body", "") or ""

    # 1. Infer Categories
    recommended_categories = infer_categories(t_title, t_body)

    # 2. Check Duplicates / Similarities
    potential_duplicates: List[Dict[str, Any]] = []

    for other in all_issues:
        o_num = other.get("number", 0)
        if o_num == t_num:
            continue

        o_title = other.get("title", "")
        o_body = other.get("body", "") or ""

        # Quick lexical filter
        jaccard = calculate_jaccard_similarity(f"{t_title} {t_body}", f"{o_title} {o_body}")
        if jaccard >= 0.25:  # Pre-filter candidate threshold
            is_dup, conf = verify_duplicate_with_jev(
                t_title, t_body, o_title, o_body, pipeline=pipeline
            )
            if is_dup or jaccard >= 0.45:
                potential_duplicates.append(
                    {
                        "number": o_num,
                        "title": o_title,
                        "state": other.get("state"),
                        "lexical_similarity": round(jaccard, 3),
                        "is_jev_duplicate": is_dup,
                        "confidence": round(conf, 3),
                    }
                )

    potential_duplicates.sort(key=lambda x: x["lexical_similarity"], reverse=True)

    return {
        "number": t_num,
        "title": t_title,
        "recommended_categories": recommended_categories,
        "potential_duplicates": potential_duplicates,
    }


def post_screening_results_to_issue(
    issue_number: int,
    screening_result: Dict[str, Any],
    repo: Optional[str] = None,
) -> bool:
    """Post screening findings as an issue comment and apply category labels."""
    categories = screening_result.get("recommended_categories", [])
    duplicates = screening_result.get("potential_duplicates", [])

    body_lines = ["### 🤖 JEV Issue スクリーニング結果\n"]

    if categories:
        cats_str = ", ".join([f"`{c}`" for c in categories])
        body_lines.append(f"- **推奨カテゴリ**: {cats_str}")
    else:
        body_lines.append("- **推奨カテゴリ**: (該当なし)")

    if duplicates:
        body_lines.append("\n- **類似・重複の可能性がある過去の Issue**:")
        for d in duplicates[:5]:
            state_emoji = "🟢" if d["state"] == "OPEN" else "🟣"
            dup_tag = "【JEV 重複判定】" if d["is_jev_duplicate"] else ""
            body_lines.append(
                f"  - {state_emoji} #{d['number']} `{d['title']}` "
                f"(類似度: {int(d['lexical_similarity'] * 100)}%) {dup_tag}"
            )
    else:
        body_lines.append("- **重複確認**: 類似・重複する過去の Issue は見つかりませんでした。")

    comment_text = "\n".join(body_lines)

    # 1. Post Comment
    cmd_comment = ["gh", "issue", "comment", str(issue_number), "--body", comment_text]
    if repo:
        cmd_comment.extend(["--repo", repo])

    try:
        subprocess.run(cmd_comment, capture_output=True, text=True, check=True)
        logger.info(f"Comment posted to Issue #{issue_number}.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to post comment to Issue #{issue_number}: {e.stderr}")
        return False

    # 2. Apply Recommended Category Label (if not already present)
    if categories:
        best_cat = categories[0]
        cmd_label = ["gh", "issue", "edit", str(issue_number), "--add-label", best_cat]
        if repo:
            cmd_label.extend(["--repo", repo])
        try:
            subprocess.run(cmd_label, capture_output=True, text=True, check=True)
            logger.info(f"Applied label '{best_cat}' to Issue #{issue_number}.")
        except Exception as e:
            logger.warning(f"Could not apply label '{best_cat}': {e}")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen GitHub issues for duplicates and categories."
    )
    parser.add_argument(
        "--issue", type=int, default=None, help="Target specific issue number to screen"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Post results as comment and apply labels"
    )
    parser.add_argument("--repo", type=str, default=None, help="GitHub repository (owner/repo)")
    args = parser.parse_args()

    all_issues = fetch_all_issues(repo=args.repo)
    if not all_issues:
        logger.warning("No issues found or failed to fetch.")
        return

    logger.info(f"Fetched {len(all_issues)} total issues.")

    target_issues = []
    if args.issue:
        target_issues = [iss for iss in all_issues if iss.get("number") == args.issue]
        if not target_issues:
            logger.error(f"Issue #{args.issue} not found in repository.")
            return
    else:
        # Default: screen open stage:ideation issues
        for iss in all_issues:
            labels = [
                lbl.get("name", "") if isinstance(lbl, dict) else str(lbl)
                for lbl in iss.get("labels", [])
            ]
            if "stage:ideation" in labels and iss.get("state") == "OPEN":
                target_issues.append(iss)

    logger.info(f"Screening {len(target_issues)} issue(s)...")

    for target in target_issues:
        num = target.get("number")
        result = screen_single_issue(target, all_issues)
        logger.info(f"Screening result for Issue #{num}:")
        logger.info(f"  Categories: {result['recommended_categories']}")
        logger.info(f"  Potential duplicates: {len(result['potential_duplicates'])}")

        if args.apply and num:
            post_screening_results_to_issue(num, result, repo=args.repo)


if __name__ == "__main__":
    main()

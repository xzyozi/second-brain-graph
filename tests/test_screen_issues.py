"""Unit tests for tools/screen_issues.py."""

from unittest.mock import MagicMock

from tools.screen_issues import (
    calculate_jaccard_similarity,
    infer_categories,
    screen_single_issue,
    tokenize,
)


def test_tokenize():
    """Test tokenization of English and Japanese text."""
    tokens = tokenize("[feat] レビュー合否ゲートをJEV(noul)で決定化する")
    assert "レビュー合否ゲートをjev" in tokens or any("jev" in t or "レビュー" in t for t in tokens)


def test_calculate_jaccard_similarity():
    """Test Jaccard similarity between identical, similar, and distinct texts."""
    text1 = "review conformance gate with jev noul validation"
    text2 = "review conformance gate with jev noul verification"
    text3 = "completely different database migration script"

    sim_high = calculate_jaccard_similarity(text1, text2)
    sim_low = calculate_jaccard_similarity(text1, text3)

    assert sim_high > 0.5
    assert sim_low == 0.0


def test_infer_categories():
    """Test category inference from keywords."""
    cats = infer_categories(
        title="[feat] レビュー合否ゲートをJEV(noul)で決定化する二次ゲートを追加",
        body="review_node にて orchestrator の合否を検証し、safety と回帰テストを保証する",
    )
    assert "area:jev" in cats
    assert "area:orch" in cats
    assert "area:safety" in cats


def test_screen_single_issue_with_duplicate():
    """Test duplicate detection in screening."""
    target = {
        "number": 201,
        "title": "レビュー合否ゲートのJEV検証",
        "body": "review_node で JEV noul を呼び出して検証する",
    }
    all_issues = [
        target,
        {
            "number": 150,
            "title": "レビュー合否ゲートのJEV検証と二次ゲート",
            "body": "review_node で JEV noul を呼び出して二次検証を行う",
            "state": "OPEN",
        },
        {
            "number": 151,
            "title": "全く関係のないUI改善タスク",
            "body": "フロントエンドのデザインを改修する",
            "state": "CLOSED",
        },
    ]

    # Mock JEV pipeline to simulate duplicate detection
    mock_pipeline = MagicMock()
    mock_response = MagicMock()
    mock_response.status = "SUCCESS"
    mock_response.verdict = "Yes"
    mock_response.confidence = 0.95
    mock_pipeline.judge.return_value = mock_response

    result = screen_single_issue(target, all_issues, pipeline=mock_pipeline)

    assert result["number"] == 201
    assert "area:jev" in result["recommended_categories"]
    assert len(result["potential_duplicates"]) >= 1
    dup_numbers = [d["number"] for d in result["potential_duplicates"]]
    assert 150 in dup_numbers
    assert 151 not in dup_numbers

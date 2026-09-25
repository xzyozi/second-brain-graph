"""Unit tests for tools/close_stale_issues.py."""

from datetime import datetime, timezone
from unittest.mock import patch

from tools.close_stale_issues import (
    is_stale_issue,
    process_stale_issues,
)


def test_is_stale_issue_not_stale():
    """Test that issue updated 10 days ago is not stale with 30 days threshold."""
    now_dt = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    updated_str = "2026-09-15T12:00:00Z"  # 10 days ago

    is_stale, elapsed = is_stale_issue(updated_str, days_threshold=30, now_dt=now_dt)
    assert not is_stale
    assert elapsed == 10


def test_is_stale_issue_stale():
    """Test that issue updated 35 days ago is stale."""
    now_dt = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    updated_str = "2026-08-20T12:00:00Z"  # 36 days ago

    is_stale, elapsed = is_stale_issue(updated_str, days_threshold=30, now_dt=now_dt)
    assert is_stale
    assert elapsed >= 35


def test_is_stale_issue_invalid_date():
    """Test handling of invalid timestamp string."""
    is_stale, elapsed = is_stale_issue("invalid-date")
    assert not is_stale
    assert elapsed == 0


def test_process_stale_issues_dry_run():
    """Test process_stale_issues with mock issues and dry_run=True."""
    mock_issues = [
        {
            "number": 101,
            "title": "Old ideation task",
            "updatedAt": "2026-08-01T00:00:00Z",
            "labels": [{"name": "stage:ideation"}],
        },
        {
            "number": 102,
            "title": "Fresh ideation task",
            "updatedAt": "2026-09-24T00:00:00Z",
            "labels": [{"name": "stage:ideation"}],
        },
    ]

    now_dt = datetime(2026, 9, 25, 0, 0, 0, tzinfo=timezone.utc)

    with patch("tools.close_stale_issues.fetch_ideation_issues", return_value=mock_issues):
        with patch("tools.close_stale_issues.close_issue", return_value=True) as mock_close:
            closed = process_stale_issues(days_threshold=30, dry_run=True, now_dt=now_dt)
            assert closed == [101]
            mock_close.assert_called_once_with(101, 55, dry_run=True, repo=None)

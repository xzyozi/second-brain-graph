import importlib.util
import sys
from pathlib import Path

import pytest

# run_review.py の動的インポート
script_path = (
    Path(__file__).resolve().parents[1]
    / ".gemini"
    / "skills"
    / "satellite-ideation-reviewer"
    / "scripts"
    / "run_review.py"
)
spec = importlib.util.spec_from_file_location("run_review", script_path)
assert spec is not None and spec.loader is not None
run_review = importlib.util.module_from_spec(spec)
sys.modules["run_review"] = run_review
spec.loader.exec_module(run_review)

ReviewItem = run_review.ReviewItem
ExistingIssue = run_review.ExistingIssue


def test_validate_target_repo_mother_protection(tmp_path: Path) -> None:
    """母艦リポジトリ自身がターゲットに指定された場合は例外を送出する."""
    with pytest.raises(ValueError, match="母艦リポジトリ.*はレビュー対象外です"):
        run_review.validate_target_repo(tmp_path, "second-brain-graph")

    with pytest.raises(ValueError, match="母艦リポジトリ.*はレビュー対象外です"):
        run_review.validate_target_repo(tmp_path, "")


def test_validate_target_repo_not_found(tmp_path: Path) -> None:
    """存在しないサテライトが指定された場合は FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="指定されたサテライトディレクトリが存在しません"):
        run_review.validate_target_repo(tmp_path, "non_existent_satellite")


def test_validate_target_repo_success(tmp_path: Path) -> None:
    """存在するサテライトの場合はパスを正常に返す."""
    target_dir = tmp_path / "projects" / "test_satellite"
    target_dir.mkdir(parents=True)
    res = run_review.validate_target_repo(tmp_path, "test_satellite")
    assert res == target_dir


def test_parse_agys_response_json_block() -> None:
    """コードブロックで囲まれた JSON を正しくパースできる."""
    raw = """レビュー結果は以下の通りです。
```json
{
  "reviews": [
    {
      "title": "[security] パストラバーサルの潜在的リスク",
      "target_file": "src/utils/file_utils.py#L30-L45",
      "severity": "High",
      "summary": "パスのバリデーション不備",
      "problem_detail": "os.path.join が未検証で呼ばれています",
      "suggested_solution": "os.path.abspath と startswith で検証する",
      "keywords": ["path_traversal", "security", "file_utils"]
    }
  ]
}
```
確認をお願いします。
"""
    items = run_review.parse_agys_response(raw)
    assert len(items) == 1
    assert items[0].title == "[security] パストラバーサルの潜在的リスク"
    assert items[0].severity == "High"
    assert "path_traversal" in items[0].keywords


def test_check_duplicates_with_open_and_closed_issues() -> None:
    """重複チェック: Open はスキップ、Closed は注記付きで例外起票."""
    existing = [
        ExistingIssue(
            number=1,
            title="[security] パストラバーサル防止の不備",
            state="OPEN",
            body="src/utils/file_utils.py における検証不備",
        ),
        ExistingIssue(
            number=2,
            title="[edge_cases] None ハンドリングのエラー",
            state="CLOSED",
            body="src/api.py での None エラー",
        ),
    ]

    items = [
        # Open Issue #1 と重複（スキップされるべき）
        ReviewItem(
            title="[security] パストラバーサル防止の不備",
            target_file="src/utils/file_utils.py#L10",
            severity="High",
            summary="要約",
            problem_detail="詳細",
            suggested_solution="解決案",
        ),
        # Closed Issue #2 と重複（例外的に注記付きで起票されるべき）
        ReviewItem(
            title="[edge_cases] None ハンドリングのエラー再発",
            target_file="src/api.py#L20",
            severity="Medium",
            summary="要約2",
            problem_detail="詳細2",
            suggested_solution="解決案2",
        ),
        # 重複なし（通常通り起票されるべき）
        ReviewItem(
            title="[architecture] 単一責任の原則違反",
            target_file="src/service.py#L50",
            severity="Low",
            summary="要約3",
            problem_detail="詳細3",
            suggested_solution="解決案3",
        ),
    ]

    filtered = run_review.check_duplicates(items, existing)
    assert len(filtered) == 2

    # Closed Issue と重複したものは注記がある
    closed_item = [i for i in filtered if "None" in i.title][0]
    assert "Issue #2: Closed" in closed_item.related_issue_note

    # 重複なしのものは注記が空
    arch_item = [i for i in filtered if "単一責任" in i.title][0]
    assert arch_item.related_issue_note == ""


def test_filter_and_cap_issues() -> None:
    """重要度順ソートと上限件数（Cap）の切り詰め."""
    items = [
        ReviewItem("Low Issue", "f1", "Low", "s", "p", "sol"),
        ReviewItem("High Issue", "f2", "High", "s", "p", "sol"),
        ReviewItem("Medium Issue", "f3", "Medium", "s", "p", "sol"),
        ReviewItem("High Issue 2", "f4", "High", "s", "p", "sol"),
    ]

    capped = run_review.filter_and_cap_issues(items, max_issues=2)
    assert len(capped) == 2
    assert capped[0].severity == "High"
    assert capped[1].severity == "High"


def test_format_issue_body() -> None:
    """起票用 Issue 本文の Markdown 構造を検証する."""
    item = ReviewItem(
        title="[security] 検証不備",
        target_file="src/main.py#L10",
        severity="High",
        summary="入力検証がありません",
        problem_detail="外部からの文字列をそのまま使用しています",
        suggested_solution="正規表現でバリデーションを行ってください",
        related_issue_note="過去の Issue #5 (Closed) の再発確認",
    )

    body = run_review.format_issue_body(item, theme_key="security")
    assert "## 検出テーマ: セキュリティ" in body
    assert "`src/main.py#L10`" in body
    assert "**重要度**: High" in body
    assert "過去の Issue #5 (Closed) の再発確認" in body
    assert "stage:ideation" in body


def test_main_dry_run_with_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main の結合テスト（dry-run + mock-response）."""
    # サテライト環境を疑似作成
    sat_dir = tmp_path / "projects" / "mock_satellite"
    sat_dir.mkdir(parents=True)
    src_file = sat_dir / "app.py"
    src_file.write_text("def test(): pass\n", encoding="utf-8")

    mock_json = """
    {
      "reviews": [
        {
          "title": "[security] mock vulnerability",
          "target_file": "app.py#L1",
          "severity": "High",
          "summary": "mock summary",
          "problem_detail": "mock detail",
          "suggested_solution": "mock solution",
          "keywords": ["mock"]
        }
      ]
    }
    """

    # validate_target_repo の探索元 repo_root を tmp_path に向ける
    monkeypatch.setattr(
        run_review, "validate_target_repo", lambda root, target: sat_dir
    )
    monkeypatch.setattr(
        run_review, "fetch_existing_issues", lambda target: []
    )

    exit_code = run_review.main([
        "--target", "mock_satellite",
        "--theme", "security",
        "--dry-run",
        "--mock-response", mock_json,
    ])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "[DRY-RUN] 起票対象: [security] mock vulnerability" in captured.out
    assert "[Labels]: stage:ideation" in captured.out

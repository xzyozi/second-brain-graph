"""tests/test_issue_spec_manager.py - issue_spec_manager の単体テスト."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.issue_spec_manager import (
    format_issue_spec_content,
    get_task_id_from_tasks_md,
    self_heal_missing_specs,
    write_issue_spec,
)


def test_format_issue_spec_content_without_header() -> None:
    content = format_issue_spec_content("CW-0038", "タイトル", "## 1. 概要\n本文です")
    assert content.startswith("# [CW-0038] タイトル\n\n## 1. 概要")


def test_format_issue_spec_content_with_existing_header() -> None:
    content = format_issue_spec_content("CW-0038", "タイトル", "# 既存タイトル\n\n## 1. 概要\n本文")
    assert content.startswith("# [CW-0038] 既存タイトル\n\n## 1. 概要")


def test_format_issue_spec_content_with_already_tagged_header() -> None:
    content = format_issue_spec_content(
        "CW-0038", "タイトル", "# [CW-0038] 既存タイトル\n\n## 1. 概要\n本文"
    )
    assert content.startswith("# [CW-0038] 既存タイトル\n\n## 1. 概要")


def test_write_issue_spec(tmp_path: Path) -> None:
    project_dir = tmp_path / "clip_watcher"
    spec_path = write_issue_spec(
        project_dir=project_dir,
        task_id="CW-0038",
        title="クリップボード重複検知",
        body="## 1. 概要\n詳細本文",
    )
    assert spec_path.exists()
    assert spec_path.name == "CW-0038.md"
    content = spec_path.read_text(encoding="utf-8")
    assert "# [CW-0038] クリップボード重複検知" in content
    assert "## 1. 概要" in content


def test_get_task_id_from_tasks_md(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text(
        "# Tasks\n\n- [ ] [CW-0038] タイトル <!-- priority:high issue:#109 -->\n",
        encoding="utf-8",
    )
    task_id = get_task_id_from_tasks_md(tasks_path, 109)
    assert task_id == "CW-0038"
    assert get_task_id_from_tasks_md(tasks_path, 999) is None


def test_self_heal_missing_specs_with_provided_issues(tmp_path: Path) -> None:
    project_dir = tmp_path / "clip_watcher"
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True)
    tasks_path = docs_dir / "tasks.md"
    tasks_path.write_text(
        "- [ ] [CW-0038] タイトル1 <!-- priority:high issue:#109 -->\n"
        "- [x] [CW-0037] 完了タスク <!-- priority:low issue:#108 -->\n",
        encoding="utf-8",
    )

    issues = [
        {"number": 109, "title": "タイトル1", "body": "## 1. 概要\n詳細1"},
        {"number": 108, "title": "完了タスク", "body": "## 1. 概要\n詳細2"},
    ]

    healed = self_heal_missing_specs(
        project_dir=project_dir,
        repo="xzyozi/clip_watcher",
        issues=issues,
    )
    assert "CW-0038" in healed
    assert "CW-0037" in healed

    spec_38 = project_dir / "docs" / "issues" / "CW-0038.md"
    spec_37 = project_dir / "docs" / "issues" / "CW-0037.md"
    assert spec_38.exists()
    assert spec_37.exists()

    # 再度実行した場合は既に存在するため空リスト
    healed_again = self_heal_missing_specs(
        project_dir=project_dir,
        repo="xzyozi/clip_watcher",
        issues=issues,
    )
    assert healed_again == []


@patch("tools.issue_spec_manager.fetch_remote_issue_body")
def test_self_heal_missing_specs_with_remote_fetch(mock_fetch: MagicMock, tmp_path: Path) -> None:
    mock_fetch.return_value = {
        "number": 109,
        "title": "リモートタイトル",
        "body": "## 1. リモート概要",
    }
    project_dir = tmp_path / "clip_watcher"
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True)
    tasks_path = docs_dir / "tasks.md"
    tasks_path.write_text(
        "- [ ] [CW-0038] タイトル <!-- priority:high issue:#109 -->\n",
        encoding="utf-8",
    )

    healed = self_heal_missing_specs(
        project_dir=project_dir,
        repo="xzyozi/clip_watcher",
        issues=None,
    )
    assert healed == ["CW-0038"]
    spec_38 = project_dir / "docs" / "issues" / "CW-0038.md"
    assert spec_38.exists()
    assert "リモートタイトル" in spec_38.read_text(encoding="utf-8")


def test_parse_task_line_metadata() -> None:
    from tools.issue_spec_manager import parse_task_line_metadata

    # 正常行
    line = "- [ ] [CW-0038] クリップボード監視 <!-- priority:high issue:#109 theme:security -->"
    task_id, issue_num = parse_task_line_metadata(line)
    assert task_id == "CW-0038"
    assert issue_num == 109

    # チェック済み行
    line_checked = "- [x] [TP-0001] 完了タスク <!-- issue:#42 -->"
    task_id2, issue_num2 = parse_task_line_metadata(line_checked)
    assert task_id2 == "TP-0001"
    assert issue_num2 == 42

    # 不正行
    assert parse_task_line_metadata("ただのテキスト") == (None, None)
    assert parse_task_line_metadata("- [ ] タスクのみ（IDなし）") == (None, None)


def test_write_issue_spec_with_dataclass(tmp_path: Path) -> None:
    from tools.issue_spec_manager import IssueSpecData

    project_dir = tmp_path / "proj"
    spec_data = IssueSpecData(task_id="TEST-001", title="テストDTO", body="## 1. 概要")
    spec_path = write_issue_spec(project_dir=project_dir, spec=spec_data)
    assert spec_path.exists()
    content = spec_path.read_text(encoding="utf-8")
    assert "# [TEST-001] テストDTO" in content


def test_sync_spec_for_task(tmp_path: Path) -> None:
    from tools.issue_spec_manager import sync_spec_for_task

    project_dir = tmp_path / "proj"
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True)
    tasks_file = docs_dir / "tasks.md"
    tasks_file.write_text(
        "- [ ] [TEST-0005] 自動同期タスク <!-- issue:#500 -->\n",
        encoding="utf-8",
    )

    # tasks.md から task_id を自動逆引きして生成
    spec_path = sync_spec_for_task(
        project_dir=project_dir,
        issue_num=500,
        title="自動同期タスク",
        body="## 1. 詳細",
    )
    assert spec_path is not None
    assert spec_path.name == "TEST-0005.md"
    assert "# [TEST-0005] 自動同期タスク" in spec_path.read_text(encoding="utf-8")

    # 未登録の Issue 番号の場合は None
    res = sync_spec_for_task(
        project_dir=project_dir,
        issue_num=999,
        title="存在しないIssue",
        body="",
    )
    assert res is None

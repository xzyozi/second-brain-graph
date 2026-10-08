from pathlib import Path

import pytest

from tools import promote_issue


def test_parse_approaches() -> None:
    sample_body = """## 2. 仕様および要求事項

### 検討中の修正方針 (Proposed Approaches):
<!-- ※運用方針: 基本は「案 1 (推奨)」を採用して確定タスクへ展開します -->
- [ ] **案 1 (推奨): shlex.quote による引数エスケープの適用**
  - 方針概要: コマンド文字列組み立て箇所でエスケープする
  - メリット: 最小変更
- [x] **案 2: 入力引数の事前バリデーションの追加**
  - 方針概要: パス引数を検証する
  - メリット: 多層防御

### 確定実装タスク (Task Checklist):
- [ ] （方針決定後に確定タスクが展開されます）
"""
    apps = promote_issue.parse_approaches(sample_body)
    assert 1 in apps
    assert 2 in apps
    assert apps[1]["checked"] is False
    assert "shlex.quote" in apps[1]["title"]
    assert apps[2]["checked"] is True
    assert "事前バリデーション" in apps[2]["title"]


def test_update_target_files_section() -> None:
    sample_body = """## 3. 段階的実装手順 (Step-by-step Execution)
- Phase 1

## 4. 編集対象ファイル (Target Files)
- `old/path.py`

## 5. 影響範囲
- 影響小
"""
    updated = promote_issue.update_target_files_section(
        sample_body, ["src/new_path.py", "`src/another.py`"]
    )
    assert "- `src/new_path.py`" in updated
    assert "- `src/another.py`" in updated
    assert "old/path.py" not in updated
    assert "## 5. 影響範囲" in updated


def test_update_execution_steps_section() -> None:
    sample_body = """## 2. 仕様
詳細

## 3. 段階的実装手順 (Step-by-step Execution)
- Phase 1

## 4. 編集対象ファイル
- `file.py`
"""
    updated = promote_issue.update_execution_steps_section(
        sample_body, ["- [ ] タスクA", "タスクB", "- タスクC"]
    )
    assert "- [ ] タスクA" in updated
    assert "- [ ] タスクB" in updated
    assert "- [ ] タスクC" in updated
    assert "Phase 1" not in updated

    # 空リストの場合は変更されない
    unchanged = promote_issue.update_execution_steps_section(sample_body, [])
    assert unchanged == sample_body


def test_generate_promoted_body() -> None:
    sample_body = """## 0. メタ情報 (Scope & Impact)
- **検出テーマ**: セキュリティ
- **重要度**: High
- **起票ステータス**: `stage:ideation` (agys 自律レビュー起票)

## 1. 概要・背景
テスト概要

## 2. 仕様および要求事項

### 検討中の修正方針 (Proposed Approaches):
- [ ] **案 1 (推奨): アプローチ1のタイトル**
  - 詳細1
- [ ] **案 2: アプローチ2のタイトル**
  - 詳細2

### 確定実装タスク (Task Checklist):
- [ ] （方針決定後に確定タスクが展開されます）

## 3. 段階的実装手順 (Step-by-step Execution)
- Phase 1

## 4. 編集対象ファイル (Target Files)
- `dummy/file.py`

## 7. 対象外 (Non-Goals)
- 本課題と無関係な修正
- （※壁打ちで採用されなかった代替アプローチはここに記録してスコープ外を明確化）

## 8. 完了定義 (Definition of Done)
- [ ] 完了

---
*※ 本 Issue は agys 自律レビューにより自動起票されました（stage:ideation）。壁打ち・検討後に stage:ready へ昇格してください。*
"""
    apps = promote_issue.parse_approaches(sample_body)
    promoted = promote_issue.generate_promoted_body(
        body=sample_body,
        selected_approach=1,
        approaches=apps,
        concrete_tasks=["タスク1を実行する", "テストコードを作成する"],
        target_files=["src/core/runner.py", "tests/test_runner.py"],
    )

    assert "`stage:ready` (方針確定・tasks.md 登録完了)" in promoted
    assert "- [x] **案 1 (推奨): アプローチ1のタイトル**" in promoted
    assert "- [ ] **案 2: アプローチ2のタイトル**" in promoted
    assert "### 確定実装タスク" not in promoted
    assert "- [ ] タスク1を実行する" in promoted
    assert "- [ ] テストコードを作成する" in promoted
    assert "- `src/core/runner.py`" in promoted
    assert "- `tests/test_runner.py`" in promoted
    assert "dummy/file.py" not in promoted
    assert "## 7. 対象外 (Non-Goals)" in promoted
    assert "**案 2 (アプローチ2のタイトル)**: 案1を採用したため今回はスコープ外" in promoted
    assert "tasks.md に登録されて stage:ready に昇格しました" in promoted


def test_sync_to_tasks_md(tmp_path: Path) -> None:
    tasks_file = tmp_path / "docs" / "tasks.md"
    success = promote_issue.sync_to_tasks_md(
        tasks_path=tasks_file,
        project_key="TEST",
        issue_num=10,
        title="テストIssue",
        priority="high",
    )
    assert success is True
    content = tasks_file.read_text(encoding="utf-8")
    assert "- [ ] [TEST-0001] テストIssue <!-- priority:high issue:#10 stage:ready -->" in content

    # 既に stage:ready の重複登録はスキップされる (False)
    success_duplicate = promote_issue.sync_to_tasks_md(
        tasks_path=tasks_file,
        project_key="TEST",
        issue_num=10,
        title="テストIssue",
        priority="high",
    )
    assert success_duplicate is False

    # 既存行が stage:ideation の場合は stage:ready へ昇格される (True)
    ideation_file = tmp_path / "docs" / "tasks_ideation.md"
    ideation_file.write_text(
        "- [ ] [TEST-0003] アイデアタスク <!-- priority:low issue:#20 stage:ideation -->\n",
        encoding="utf-8",
    )
    success_promote = promote_issue.sync_to_tasks_md(
        tasks_path=ideation_file,
        project_key="TEST",
        issue_num=20,
        title="アイデアタスク",
        priority="low",
    )
    assert success_promote is True
    assert "stage:ready" in ideation_file.read_text(encoding="utf-8")
    assert "stage:ideation" not in ideation_file.read_text(encoding="utf-8")

    # 2件目のタスク番号が正しくインクリメントされる
    success_2 = promote_issue.sync_to_tasks_md(
        tasks_path=tasks_file,
        project_key="TEST",
        issue_num=11,
        title="テストIssue2",
        priority="medium",
    )
    assert success_2 is True
    content2 = tasks_file.read_text(encoding="utf-8")
    assert (
        "- [ ] [TEST-0002] テストIssue2 <!-- priority:medium issue:#11 stage:ready -->" in content2
    )


def test_promote_issue_creates_spec_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 擬似リポジトリとサテライトディレクトリ作成
    root_dir = tmp_path / "root"
    sat_dir = root_dir / "projects" / "test_proj"
    sat_dir.mkdir(parents=True)
    (sat_dir / "docs").mkdir()

    # モックの設定
    mock_issue = {
        "number": 42,
        "title": "機能改善",
        "body": """## 0. メタ情報
- **重要度**: High

## 2. 仕様および要求事項
- [ ] **案 1 (推奨): 推奨方針**
  - 詳細1
- [ ] **案 2: 代替方針**
  - 詳細2

## 7. 対象外 (Non-Goals)
- 本課題と無関係な修正
- （※壁打ちで採用されなかった代替アプローチはここに記録してスコープ外を明確化）

## 8. 完了定義 (Definition of Done)
- [ ] 完了
""",
        "labels": [{"name": "stage:ideation"}, {"name": "theme:architecture"}],
    }

    monkeypatch.setattr(
        promote_issue,
        "resolve_project_info",
        lambda _root, _p: ("TP", sat_dir, "xzyozi/test_proj"),
    )
    monkeypatch.setattr(promote_issue, "fetch_issue", lambda _repo, _num: mock_issue)
    monkeypatch.setattr(promote_issue.subprocess, "run", lambda *a, **kw: None)

    success = promote_issue.promote_issue(
        root_dir=root_dir,
        target_project="test_proj",
        issue_num=42,
        approach=1,
        concrete_tasks=["実装タスク1", "実装タスク2"],
        target_files=["src/main.py"],
    )
    assert success is True

    # tasks.md の確認
    tasks_file = sat_dir / "docs" / "tasks.md"
    assert tasks_file.exists()
    assert "- [ ] [TP-0001] 機能改善" in tasks_file.read_text(encoding="utf-8")

    # docs/issues/TP-0001.md の確認
    spec_file = sat_dir / "docs" / "issues" / "TP-0001.md"
    assert spec_file.exists()
    spec_content = spec_file.read_text(encoding="utf-8")
    assert "# [TP-0001] 機能改善" in spec_content
    assert "stage:ready" in spec_content
    assert "- [x] **案 1 (推奨): 推奨方針**" in spec_content
    assert "**案 2 (代替方針)**: 案1を採用したため今回はスコープ外" in spec_content
    assert "- [ ] 実装タスク1" in spec_content
    assert "- [ ] 実装タスク2" in spec_content
    assert "- `src/main.py`" in spec_content


def test_promote_issue_main_url_driven(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() が GitHub Issue URL を位置引数に受け取って正常に実行されることを検証する。"""
    import json
    from unittest.mock import patch

    root_dir = tmp_path
    sat_dir = root_dir / "projects" / "test_proj"
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)

    meta_dir = root_dir / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_file.write_text(
        json.dumps(
            {
                "projects": {
                    "TP": {
                        "name": "test_proj",
                        "github_repo": "xzyozi/test_proj",
                        "dir": "projects/test_proj",
                        "meta": "metadata/projects/TP",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    mock_issue = {
        "number": 42,
        "title": "URLからの機能改善",
        "body": "## 2. 仕様\n- [ ] **案 1 (推奨): 方針1**\n",
        "labels": [{"name": "stage:ideation"}],
    }
    monkeypatch.setattr(promote_issue, "fetch_issue", lambda _repo, _num: mock_issue)
    monkeypatch.setattr(promote_issue.subprocess, "run", lambda *a, **kw: None)

    with (
        patch(
            "sys.argv",
            ["promote_issue.py", "https://github.com/xzyozi/test_proj/issues/42", "--dry-run"],
        ),
        patch("pathlib.Path.cwd", return_value=root_dir),
        patch("tools.promote_issue.Path", return_value=root_dir),
    ):
        # promote_issue(root_dir=...) を patch して呼び出し確認
        with patch("tools.promote_issue.promote_issue", return_value=True) as mock_promote:
            promote_issue.main()
            assert mock_promote.called
            call_kwargs = mock_promote.call_args.kwargs
            assert call_kwargs["target_project"] == "xzyozi/test_proj"
            assert call_kwargs["issue_num"] == 42

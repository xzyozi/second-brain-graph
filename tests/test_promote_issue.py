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
    )

    assert "`stage:ready` (方針確定・tasks.md 登録完了)" in promoted
    assert "- [x] **案 1 (推奨): アプローチ1のタイトル**" in promoted
    assert "- [ ] **案 2: アプローチ2のタイトル**" in promoted
    assert "### 確定実装タスク" not in promoted
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
    assert "- [ ] [TEST-0001] テストIssue <!-- priority:high issue:#10 -->" in content

    # 重複登録はスキップされる
    success_duplicate = promote_issue.sync_to_tasks_md(
        tasks_path=tasks_file,
        project_key="TEST",
        issue_num=10,
        title="テストIssue",
        priority="high",
    )
    assert success_duplicate is False

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
    assert "- [ ] [TEST-0002] テストIssue2 <!-- priority:medium issue:#11 -->" in content2


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

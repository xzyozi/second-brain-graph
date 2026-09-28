from pathlib import Path

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

    assert "`stage:ready` (方針確定・実装準備完了)" in promoted
    assert "### 採用された修正方針:" in promoted
    assert "アプローチ1のタイトル" in promoted
    assert "- [ ] タスク1を実行する" in promoted
    assert "- [ ] テストコードを作成する" in promoted
    assert "アプローチ2のタイトル" in promoted
    assert "## 7. 対象外 (Non-Goals)" in promoted
    assert (
        "案2を採用したため今回はスコープ外" in promoted
        or "案1を採用したため今回はスコープ外" in promoted
    )
    assert "壁打ちにより案1が採用され、stage:ready（実装可能）に昇格しました" in promoted


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

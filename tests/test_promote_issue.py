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

    assert "`stage:ready` (方針確定済み)" in promoted
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
    assert "stage:ready に昇格しました" in promoted


def test_promote_issue_updates_github_without_local_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """promote_issue() が GitHub Issue を更新し、tasks.md / docs/issues を作成しないことを検証する."""
    import subprocess

    # 擬似リポジトリとサテライトディレクトリ作成
    root_dir = tmp_path / "root"
    sat_dir = root_dir / "projects" / "test_proj"
    sat_dir.mkdir(parents=True)

    # モックの設定
    mock_issue = {
        "number": 42,
        "title": "機能改善",
        "body": """## 0. メタ情報
- **重要度**: High

## 1. 概要・背景
機能改善の概要。

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

    recorded_cmds: list[list[str]] = []

    def mock_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        promote_issue,
        "resolve_project_info",
        lambda _root, _p: ("TP", sat_dir, "xzyozi/test_proj"),
    )
    monkeypatch.setattr(promote_issue, "fetch_issue", lambda _repo, _num: mock_issue)
    monkeypatch.setattr(
        promote_issue,
        "verify_plan_conformance",
        lambda **_kwargs: (True, 0.95, "JEV Plan Conformance: PASSED"),
    )
    monkeypatch.setattr(promote_issue.subprocess, "run", mock_run)

    success = promote_issue.promote_issue(
        root_dir=root_dir,
        target_project="test_proj",
        issue_num=42,
        approach=1,
        concrete_tasks=["実装タスク1", "実装タスク2"],
        target_files=["src/main.py"],
    )
    assert success is True

    # GitHub Issue 更新コマンドの検証
    assert len(recorded_cmds) == 1
    cmd = recorded_cmds[0]
    assert cmd[:4] == ["gh", "issue", "edit", "42"]
    assert "--add-label" in cmd
    assert "stage:ready" in cmd
    assert "--remove-label" in cmd
    assert "stage:ideation" in cmd

    # ローカルファイル同期が行われないことの検証
    assert not (sat_dir / "docs" / "tasks.md").exists()
    assert not (sat_dir / "docs" / "issues").exists()


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


def test_resolve_project_info_mother_aliases_and_cwd_guard(tmp_path: Path) -> None:
    """母艦エイリアス解決が promote_issue 内で完結し、projects/ 配下は母艦扱いされないこと."""
    for alias in ("second-brain-graph", "xzyozi/second-brain-graph", "SBOS", "mother"):
        key, pdir, repo = promote_issue.resolve_project_info(tmp_path, alias)
        assert key == promote_issue.MOTHER_PROJECT_KEY
        assert pdir == tmp_path
        assert repo == promote_issue.MOTHER_GITHUB_REPO

    sat_dir = tmp_path / "projects" / "some_sat"
    sat_dir.mkdir(parents=True)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    assert promote_issue._is_mother_cwd(tmp_path, tmp_path) is True
    assert promote_issue._is_mother_cwd(tools_dir, tmp_path) is True
    assert promote_issue._is_mother_cwd(sat_dir, tmp_path) is False


def test_promote_issue_main_mother_cwd_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """母艦配下 CWD で番号のみ指定された場合、母艦リポジトリへフォールバックすること."""
    from unittest.mock import patch

    actual_root = Path(promote_issue.__file__).resolve().parent.parent
    sat_dir = actual_root / "projects" / "unregistered_sat"

    monkeypatch.setattr(
        promote_issue,
        "resolve_target_spec",
        lambda *_a, **_kw: {
            "type": "issue_number",
            "project_key": None,
            "task_id": None,
            "issue_number": 203,
            "github_repo": None,
            "target": "203",
        },
    )

    with (
        patch("sys.argv", ["promote_issue.py", "203", "--dry-run", "--skip-jev"]),
        patch("tools.promote_issue.Path.cwd", return_value=actual_root),
        patch("tools.promote_issue.promote_issue", return_value=True) as mock_promote,
    ):
        promote_issue.main()
        assert mock_promote.called
        assert mock_promote.call_args.kwargs["target_project"] == promote_issue.MOTHER_GITHUB_REPO
        assert mock_promote.call_args.kwargs["issue_num"] == 203
        assert mock_promote.call_args.kwargs["skip_jev"] is True

    # projects/ 配下では母艦フォールバックしない
    with (
        patch("sys.argv", ["promote_issue.py", "203"]),
        patch("tools.promote_issue.Path.cwd", return_value=sat_dir),
        pytest.raises(SystemExit) as exc_info,
    ):
        promote_issue.main()
    assert exc_info.value.code == 1


def test_validate_promoted_structure() -> None:
    """構造チェックが必須セクション・Target Files・未置換初期値を検証すること."""
    valid_body = """## 1. 概要・背景
背景説明

## 2. 仕様および要求事項
- [x] **案 1 (推奨)**: 方針A

## 3. 段階的実装手順
- [ ] タスクA

## 4. 編集対象ファイル (Target Files)
- `tools/promote_issue.py`（既存編集）

## 8. 完了定義
- [ ] pytest 通過
"""
    assert promote_issue.validate_promoted_structure(valid_body) == []
    assert promote_issue._extract_target_files_from_body(valid_body) == ["tools/promote_issue.py"]

    broken_body = """## 1. 概要・背景
〇〇 を実装する
## 2. 仕様および要求事項
- [x] **案 1 (推奨)**: 方針
## 4. 編集対象ファイル (Target Files)
- `path/to/file.py`
"""
    errors = promote_issue.validate_promoted_structure(broken_body)
    assert any("## 3." in e for e in errors)
    assert any("## 8." in e for e in errors)
    assert any("path/to/file.py" in e for e in errors)
    assert any("〇〇" in e for e in errors)


def test_promote_issue_jev_exit_gate_reject_skip_and_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """JEV 出口検問の REJECTED 中断・--skip-jev 上書き・--dry-run 検問・抽出内容を検証する."""
    import subprocess

    mock_issue = {
        "number": 203,
        "title": "壁打ちスキル",
        "body": """## 1. 概要・背景
対話壁打ちスキルを導入する。

## 2. 仕様および要求事項
- [ ] **案 1 (推奨): 設計書改訂とスキル新設**
  - 詳細1
- [ ] **案 2: 別アプローチ**
  - 非採用詳細

## 3. 段階的実装手順
- [ ] 設計書を改訂する

## 4. 編集対象ファイル (Target Files)
- `tools/promote_issue.py`

## 7. 対象外 (Non-Goals)
- （※壁打ちで採用されなかった代替アプローチはここに記録してスコープ外を明確化）

## 8. 完了定義 (Definition of Done)
- [ ] pytest 通過
""",
        "labels": [{"name": "stage:ideation"}],
    }

    captured_calls: list[dict[str, object]] = []
    recorded_cmds: list[list[str]] = []

    def fake_verify(**kwargs: object) -> tuple[bool, float, str]:
        captured_calls.append(dict(kwargs))
        return False, 0.15, "JEV Plan Conformance: REJECTED (verdict=No, conf=0.150, latency=12ms)"

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(promote_issue, "fetch_issue", lambda _repo, _num: mock_issue)
    monkeypatch.setattr(promote_issue, "verify_plan_conformance", fake_verify)
    monkeypatch.setattr(promote_issue.subprocess, "run", fake_run)

    # 1. 通常時: REJECTED で中断し gh issue edit は呼ばれない
    with caplog.at_level("ERROR"):
        ok = promote_issue.promote_issue(
            root_dir=tmp_path,
            target_project="second-brain-graph",
            issue_num=203,
            approach=1,
        )
    assert ok is False
    assert recorded_cmds == []
    assert len(captured_calls) == 1
    assert captured_calls[0]["issue_id"] == "second-brain-graph#203"
    assert "案 1" in str(captured_calls[0]["instruction"])
    assert "別アプローチ" not in str(captured_calls[0]["instruction"])
    assert "設計書を改訂する" in str(captured_calls[0]["impl_plan"])
    assert captured_calls[0]["target_files"] == ["tools/promote_issue.py"]
    assert "--skip-jev" in caplog.text
    assert "tools/promote_issue.py" in caplog.text

    # 2. --dry-run 時も JEV 検問が実行され REJECTED なら False になる
    ok_dry_reject = promote_issue.promote_issue(
        root_dir=tmp_path,
        target_project="second-brain-graph",
        issue_num=203,
        approach=1,
        dry_run=True,
    )
    assert ok_dry_reject is False
    assert len(captured_calls) == 2

    # 3. --skip-jev 指定時は REJECTED でも昇格を実行する
    ok_skip = promote_issue.promote_issue(
        root_dir=tmp_path,
        target_project="second-brain-graph",
        issue_num=203,
        approach=1,
        skip_jev=True,
    )
    assert ok_skip is True
    assert len(captured_calls) == 2
    assert len(recorded_cmds) == 1
    assert recorded_cmds[0][:5] == ["gh", "issue", "edit", "203", "--repo"]
    assert "xzyozi/second-brain-graph" in recorded_cmds[0]

    # 4. PASSED + --dry-run なら検問実行後に True（gh issue edit なし）
    def fake_pass_verify(**kwargs: object) -> tuple[bool, float, str]:
        captured_calls.append(dict(kwargs))
        return True, 0.99, "JEV Plan Conformance: PASSED"

    monkeypatch.setattr(promote_issue, "verify_plan_conformance", fake_pass_verify)
    ok_dry_pass = promote_issue.promote_issue(
        root_dir=tmp_path,
        target_project="second-brain-graph",
        issue_num=203,
        approach=1,
        dry_run=True,
    )
    assert ok_dry_pass is True
    assert len(captured_calls) == 3
    assert len(recorded_cmds) == 1

# L5 運用・復旧試験証跡レポート (Issue #163 P1/P2)

- **実施日時**: 2026-11-06 17:27:40 JST (UTC: 2026-11-06T08:27:40Z)
- **対象**: `tools/nightly_task_worker.py`、`tools/orchestrator_graph.py`、`tools/agy_client.py`
- **スコープ**: Issue #163 に基づく現行基盤の段階的進行（P1: L5 worker試験 / P2: 排他・監査確認）
- **総合判定**: **合格 (L5-001〜L5-006 全項目契約確認完了、欠落 0 件)**

---

## 1. 試験項目と検証結果サマリー

| ID | 試験名 | 合格条件 | 検証方法 / テスト | 結果 |
| :--- | :--- | :--- | :--- | :---: |
| L5-001 | auth連続失敗 | 2回連続でworker停止 | `test_run_batch_cycle_aborts_on_consecutive_auth_quota_failures` | 合格 |
| L5-002 | quota連続失敗 | 2回連続でworker停止 | `test_run_batch_cycle_aborts_on_consecutive_auth_quota_failures` | 合格 |
| L5-003 | timeout上限停止 | 指数バックオフ後上限停止 | `test_code_node_handles_agy_timeout_retry_and_escalation` | 合格 |
| L5-004 | 子孫プロセスkill | timeout後子孫残存ゼロ | `test_run_with_tree_kill_terminates_grandchild` | 合格 |
| L5-005 | 旧資産復旧 | archive tagから復元可能 | タグ `archive/local-llm-20261104` 実在確認 | 合格 |
| L5-006 | routes復旧 | 切り戻し手順の実行可能性 | `legacy/local_llm/MANIFEST.md` §6 手順確認 | 合格 |

---

## 2. 実機環境での worker 起動確認 (dry-run)

実機 agy 環境におけるワンショット worker 実行結果:

```powershell
uv run python tools/nightly_task_worker.py --config config/nightly_worker.toml --dry-run
```

- **バッチサイクル開始**: 最大実行タスク数 = 1 件
- **候補タスク検出**: `stage:ready` 5 件検出
- **自律タスク選定**: `[TFG-0005]` (スコア: 85.0, 優先度: high)
- **終了理由 (Exit Reason)**: `batch_cycle_completed` (exit code: 0)

---

## 3. 実機未実施理由と再開条件 (Issue #163 遵守)

- **L5-001 / L5-002 (実機 auth / quota 障害)**:
  - **未確認理由**: 実アカウントの認証破壊や意図的なクォータ枯渇は運用環境を破壊するため、実機での意図的誘発は非推奨。
  - **再開・検証条件**: モック境界試験（PR #139 で実装された契約テスト）を正本として判定。将来本番運用中に実際の認証切れやクォータ超過が発生した際、本ガードが機能することをログ監視にて追跡確認する。

---

## 4. P2 複数衛星排他および実行履歴・監査の確認結果

- **複数プロジェクト排他**:
  - `ProjectLockManager` の `.lock` 排他機構により、同一プロジェクトの並列実行競合が確実に遮断されることを確認（`test_project_lock_manager_acquire_and_release`, `test_project_lock_manager_timeout` 3 passed）。
- **実行履歴・監査**:
  - 現行の `state.json` および `execution_history.json` にて、最終状態（`final_status`）、エラー分類（`error_category`）、主要品質ゲート（`lint_passed`, `test_passed`, `review_verdict`, `jev_review_conformance`）が正確に記録されることを確認（L4完走実績と完全一致）。

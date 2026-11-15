# L4 サンドボックスE2E・SSOT移行後試験 証跡レポート (TFG-0009 / L4-002〜006)

- **実施日時**: 2026-11-15 09:58 JST 〜 10:06 JST
- **対象システム**: Second Brain OS（GitHub Issues SSOT 移行後・`tools/core/orchestrator_graph.py` / `tools/run_task.py`）
- **使用モデル・バックエンド**: `agy` CLI v1.5.9（実機テスト）、Ollama `qwen2.5:0.5b`（JEV 検問）、Fake `agy` CLI（異常系 E2E）

---

## 1. 実機 SSOT フルライフサイクル試験 (`TFG-0009` / `L4-001` 再確認)

`xzyozi/test_file_grep#9`（`sandbox` ラベル付き小規模 Issue）を対象に、`tasks.md` / `docs/issues/` 非依存の GitHub Issues SSOT 導線を一気通貫で検証しました。

| 工程 | 実行コマンド / 処理 | 結果 |
| :--- | :--- | :--- |
| Ideation スキップ | `uv run python tools/score_issues.py` | `[SKIPPED] Issue TFG-0009 is skipped because it is in 'stage:ideation' stage.` |
| `stage:ready` 昇格 | `uv run python tools/promote_issue.py TFG-0009 --approach 1` | GitHub Issue `#9` 本文更新および `stage:ready` ラベル付与成功 |
| スコアリング・選定 | `uv run python tools/score_issues.py` → `orchestrator_graph.py orchestrate --project-key TFG` | Score `78.8` で第 1 位選定、`Suggested Command: python tools/core/orchestrator_graph.py execute --issue-id TFG-0009` |
| 自律実装・完走 | `uv run python tools/run_task.py TFG-0009 --fresh` | **COMPLETED**（所要時間 約 3 分 20 秒、09:58:49〜10:02:09 JST） |
| 生成成果物・テスト | `git -C projects/test_file_grep show --stat HEAD` / `uv run pytest projects/test_file_grep/tests/test_error_handler.py` | コミット `8142797`（`src/utils/error_handler.py`, `tests/test_error_handler.py`）、`11 passed` |
| 境界ガード動作 | `code_node` 中の `settings.json` 変更検知 | `[Edit Guard] Restored tracked file modified outside target_files: settings.json` |
| 定周期状態評価 | `uv run python tools/lifecycle/periodic_review_runner.py --target test_file_grep --status-only --dry-run` | `total=5, open=3, closed=2, ready=1` を正常評価 |

---

## 2. L4 異常系・fail-open シナリオ自動 E2E 試験 (`L4-002`, `L4-003`, `L4-004`, `L4-006`)

実 `git init` リポジトリ + bare `origin` リモート、`use_issue_fixture`（GitHub Issues SSOT フィクスチャ）、`SBOS_AGY_EXECUTABLE`（`tests/fixtures/fake_agy.py` の `FAKE_AGY_SEQUENCE_FILE` / `invalid_json` 拡張）を用い、`execute_issue()` フルグラフを `tests/test_orchestrator_l4_scenarios.py` で検証しました。

| 試験 ID | テスト関数 | 検証内容 | 結果 |
| :--- | :--- | :--- | :--- |
| **L4-002** | `test_l4_002_planner_timeout_retries_and_recovers` | `spec_draft` 1回目 timeout → リトライ → 2回目成功で `COMPLETED` まで完走 | 合格 |
| **L4-002** | `test_l4_002_planner_consecutive_timeouts_stop_safely` | `spec_draft` 2回連続 timeout → `FAILED_SYSTEM` (`LLM_TIMEOUT`) へ安全停止 | 合格 |
| **L4-003** | `test_l4_003_reviewer_invalid_json_transitions_to_changes_requested` | reviewer 非JSON出力時に `LGTM` 誤補正されず `changes_requested` (`retry_code`) へ遷移後、次ラウンドで回復完走（※本調査で判明した `llm_client.py` / `review_node` の `"comment"` vs `"comments"` 不整合バグを修正済み） | 合格 |
| **L4-004** | `test_l4_004_code_out_of_scope_write_handled_by_edit_guard` | 追跡外ファイル改変と未追跡ファイル作成を `edit_guard` が復元・削除し、`HEAD` コミットが `target_files` のみとなることを確認 | 合格 |
| **L4-006** | `test_l4_006_jev_unavailable_continues_pipeline_fail_open` | `OLLAMA_HOST=http://127.0.0.1:19999` により実 `JudgePipeline` を到達不能状態とし、Plan/Review 両 JEV ゲートが fail-open 継続して `COMPLETED` 到達（※`jev_adapter.py` の `effective_url` 接続反映も修正済み） | 合格 |

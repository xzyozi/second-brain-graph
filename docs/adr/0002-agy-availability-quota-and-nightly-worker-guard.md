# ADR 0002: agy 障害分類・指数バックオフと夜間ワーカー安全中断方針

- **日付**: 2026-11-04
- **ステータス**: Accepted
- **関連Issue**: Epic #116, #126

## コンテキスト (Context)
外部 CLI である `agy` を自律夜間バッチ（`nightly_task_worker.py`）で運用する際、認証失効（APIキー切れ、未ログイン）やクォータ枯渇（レートリミット、リソース枯渇）が発生する可能性がある。
これらを単なる一般的な `SYSTEM_ERROR` として処理すると、無意味なリトライを繰り返し、不要なリソース消費、ログの汚染、および夜間バッチの長期ハングアップを引き起こす。

## 決定事項 (Decision)
1. **エラーの詳細分類**:
   - `tools/backends/agy_client.py` において、終了コード非0時の標準出力・標準エラーメッセージを正規表現解析し、`AgyAuthError`（認証失効）および `AgyQuotaError`（クォータ枯渇・レート制限）を自動判別して送出する。
   - `tools/workspace/metadata_store.py` の `ErrorCategory` に `AGY_AUTH`, `AGY_QUOTA` を新設し、オーケストレーターの状態に明示記録する。

2. **タイムアウト時の指数バックオフ**:
   - `tools/core/orchestrator_graph.py` の `spec_draft_node`, `code_node` 等において、`LLM_TIMEOUT` 発生時のリトライ前に指数バックオフ待機（`time.sleep`）を挟むことで、一時的な過負荷による連続失敗を回避する。

3. **夜間バッチの連続失敗安全中断ガード**:
   - `config/nightly_worker.toml` に `max_consecutive_auth_quota_failures = 2` を設定。
   - バッチサイクル内で `AGY_AUTH`、`AGY_QUOTA` または `AGY_POLICY_DENIED` が 2回連続で発生した場合、即座に以降の全タスク実行を安全に中断し、プロセスを早期終了する。`AGY_POLICY_DENIED` は外部送信ポリシーによる拒否であり、自動リトライやフォールバックを行わない。

## 結果・影響 (Consequences)
- 外部サービス障害時に不要なタスク投入が即座に抑止され、翌朝の運用者が障害原因を `state.json` やログから迅速に特定可能となる。

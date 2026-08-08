# 詳細設計書（品質ゲート・レビュー仕様）

| 項目 | 内容 |
| --- | --- |
| 文書名 | Second Brain OS - 品質ゲートおよびレビュー制御仕様 |
| 版数 | Rev.1.0 |
| 改訂日 | 2026年8月8日 |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（オーケストレーター統合設計） |
| 対象コンポーネント | `lint_node`、`run_pytest_node`、`test_feedback_node`、`review_node`、`reviewdog` |
| 役割 | コード生成後の静的解析、自動テスト、LLMによるコードレビュー、およびRDJSONフォーマットへの変換とエスカレーション処理 |

---

## 1. 概要と基本方針

本仕様は、Aider等によるコード生成の直後に実行される「品質検証ループ」を定義する。
品質検証ループは、Ruffによるフォーマットと構文チェック、pytestによる自動テスト、そしてLLM（Reviewer）による静的コードレビューの3段階で構成される。

## 2. 品質 Adapter (`lint_node` / `run_pytest_node`)

### 2.1 Ruff 実行仕様
* **実行内容**: 
  1. `ruff format` 
  2. `ruff check --fix --unsafe-fixes --ignore E501` 
  3. 最終チェックとして `ruff check --ignore E501` を実行する。
* **副作用・失敗契約**: 
  * lintは単なる検査専用ではなく、対象ファイルを直接自動修正する（`--unsafe-fixes`）。
  * 最終チェックが非ゼロ終了となった場合、`LINT_ERROR` として扱い、`lint_round` を加算する。最大回数（3回）を超えると `FAILED_B7` にエスカレーションされる。

### 2.2 pytest 実行仕様
* **実行内容**: 
  * 関連テスト、または `tests/test_*.py` を `python -m pytest --json-report` で実行する。
  * `ui` や `gui` を含む名前のフォールバックテストは実行対象から除外する。
* **副作用・失敗契約**: 
  * JSONレポートは `.report.json` に一時保存され、処理終了時に `finally` ブロックで確実に削除される。
  * テストが失敗した場合、`TEST_ERROR` として `test_round` を加算し、最大回数（3回）を超えると `FAILED_B7` にエスカレーションされる。

### 2.3 テスト助言 (`test_feedback_node`)
* **実行内容**: テストが失敗した場合、`test_feedback` intentを用いてPlanner LLMに失敗ログを渡し、修正のための助言を生成させる。
* **副作用・失敗契約**: 助言生成自体がLLMエラー等で失敗した場合でも、テスト失敗の事実（rawテスト出力）は維持し、そのまま修正ループ（`retry_code`）へ継続させる。

## 3. Review Adapter (`review_node` / Reviewdog)

### 3.1 LLM レビュー仕様
* **実行内容**: `review_node` は `implementation_plan` と現在の Git diff を Reviewer LLM に渡し、判定（`LGTM` または `changes_requested`）およびコメント配列を要求する。
* **コメントの構造化**: 
  * LLMからのコメントは `file`、`line`、`message`、`severity` を補完して構造化される。
  * `changes_requested` と判定されたにもかかわらずコメントが空の場合は、フェイルセーフとして `LGTM` に自動補正される。
* **フィードバックの反映**:
  * severityが `structural`、`major`、`error` 等の重大な指摘、または対象外ファイルへの指摘がある場合は、その内容を Aider への次回のフィードバック指示（`aider_message`）に優先的に追加する。
  * 修正要求（`changes_requested`）は最大3回まで `retry_code` で Aider に差し戻される。

### 3.2 Reviewdog によるアノテーション
* **実行内容**: 構造化されたLLMレビューコメントを RDJSON 形式に変換し、それを標準入力で渡して `reviewdog -f=rdjson -diff="git diff HEAD"` を実行する。
* **副作用・失敗契約**: Reviewdogは補助的な表示機能（CLIやPR上のコメント用）であり、Reviewdog自体の非ゼロ終了や実行例外はログに記録するが、LLMレビュー結果（`review_verdict`）を無効化・中断させることはない。

## 4. エスカレーション (`escalate_node`)

lint または test が上限回数に到達し修正不可能な場合、`escalate_node` が呼び出される。
* **敗因レポートの生成**: 失敗原因とログを含む敗因レポート（`FAILURE_REPORT_<ISSUE_ID>.md`）の生成を試みる。
* **状態の確定**: レポート作成に成功した場合は最終状態を `ESCALATED_NEEDS_REVISION` とし、失敗時は防御的に `FAILED_B7` または `FAILED_SYSTEM` にフォールバックする。

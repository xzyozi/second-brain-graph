# 詳細設計書（品質ゲート・レビュー仕様）

| 項目 | 内容 |
| --- | --- |
| 文書名 | Second Brain OS - 品質ゲートおよびレビュー制御仕様 |
| 版数 | Rev.1.1（Defense 0: JEV 計画適合性検問ゲートの追記） |
| 改訂日 | 2026年9月21日 |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（オーケストレーター統合設計）、PM-053 |
| 対象コンポーネント | `spec_draft_node (JEV 計画適合性ゲート)`、`lint_node`、`run_pytest_node`、`test_feedback_node`、`review_node`、`reviewdog` |
| 役割 | 計画段階のYAGNI検問、コード生成後の静的解析、自動テスト、LLMによるコードレビュー、およびRDJSONフォーマットへの変換とエスカレーション処理 |

---

## 1. 概要と基本方針

本仕様は、エージェントの自律実行ループにおける「多層防衛品質ゲート」を定義する。
品質ゲートは、コード生成前の「計画適合性検問（Defense 0: JEV Plan Conformance）」、生成直後の「Ruff 静的解析（Defense 1）」、「pytest 自動テスト（Defense 2）」、および「LLM 静的コードレビュー（Defense 3）」の4段階で構成される。

### 1.1 計画適合性検問ゲート (`spec_draft_node` / Defense 0: JEV Plan Conformance)

* **目的**: Aider による本格的なコード生成に入る前に、Planner LLM が策定した `impl_plan`（Definition of Done / 実装方針計画）が Issue の要求仕様を逸脱・肥大化（YAGNI 違反・勝手な機能追加）させていないかを水際で検証し、GPU リソースの無駄な浪費と後段爆死を未然に防止する。
* **判定方式**: Zero-Decode 高速判定基盤 JEV (`submodules/jev-localsystem`) の `NoulTask`（規程適合判定）による 39ms 1トークン推論。
* **入力パラメータ**:
  1. `instruction`: Issue 本文および要求仕様
  2. `target_files`: 対象ファイル一覧
  3. `impl_plan`: Planner LLM が策定した実装計画
* **判定規程 (Policy)**:
  「この実装計画は、Issue要件の範囲内に厳密に限定されており、要求されていない新機能追加、過剰な共通化、または無関係な設定ファイルの変更（YAGNI違反・Scope Creep）を含んでいないか？」
* **状態遷移契約**:
  * **適合 (`is_valid == True`)**: `plan_conformance_status = "passed"` を設定し、`code_node` へ進行。
  * **不適合 (`is_valid == False`)**: `plan_conformance_status = "rejected"` を設定し、`plan_conformance_round` を加算。Planner への入力プロンプトに `【YAGNI VIOLATION FEEDBACK】前回の計画は要件逸脱（YAGNI違反）と判定されました。不要な改修を削ぎ落とし、Issue要件を満たす最小限の実装計画を再策定してください。` を注入し、`retry_spec_draft` で再ドラフトを要求する。
  * **エスカレーション**: 再ドラフトが上限（2回）に達した場合は `FAILED_B7` として安全停止し、人間へのエスカレーションを行う。

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

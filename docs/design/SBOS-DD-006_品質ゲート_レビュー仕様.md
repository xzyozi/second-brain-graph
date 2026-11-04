# 詳細設計書（品質ゲート・レビュー仕様）

| 項目               | 内容                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書名             | Second Brain OS - 品質ゲートおよびレビュー制御仕様                                                                                                            |
| 版数               | Rev.1.3（Epic #116: planner / reviewer LLM の agy 移行に伴う記述の一般化と、JEV 据え置きの明記）                                                              |
| 改訂日             | 2026年11月4日                                                                                                                                                 |
| 関連文書           | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、SBOS-DD-005（Backend 仕様）、PM-053、PM-054、Epic #116                                                  |
| 対象コンポーネント | `spec_draft_node (JEV 計画適合性ゲート)`、`lint_node`、`run_pytest_node`、`test_feedback_node`、`review_node (JEV レビュー合否二次ゲート)`、`reviewdog`       |
| 役割               | 計画段階のYAGNI検問、コード生成後の静的解析、自動テスト、LLMによるコードレビューとJEV決定論的二次検問、およびRDJSONフォーマットへの変換とエスカレーション処理 |

---

## 1. 概要と基本方針

本仕様は、エージェントの自律実行ループにおける「多層防衛品質ゲート」を定義する。
品質ゲートは、コード生成前の「計画適合性検問（Defense 0: JEV Plan Conformance）」、生成直後の「Ruff 静的解析（Defense 1）」、「pytest 自動テスト（Defense 2）」、および「LLM 静的コードレビュー ＋ JEV 決定論的二次検問（Defense 3: JEV Review Conformance）」の多層防衛で構成される。

### 1.0 Epic #116（agy 移行）との関係

* **LLM による判定（計画策定 `spec_draft`、テスト助言 `test_feedback`、レビュー `code_review`、敗因分析 `failure_analysis`）**: 実行基盤が Ollama から agy へ移行完了（PR #135・#137）。呼び出し側のシグネチャ・返り値・状態遷移は不変。詳細は SBOS-DD-005 §4.1。
* **JEV（Defense 0 と Defense 3.1）は据え置き**: JEV は本書の Backend 設定を経由せず、Ollama（既定 `qwen2.5:0.5b`）へ直接接続する（SBOS-DD-005 §1.1）。agy への移行後も JEV を使う限り、**Ollama の実行環境が必要**である。JEV が利用できない場合は、従来どおり判定をバイパスする（フェイルオープン）。
* **品質ゲートの順序・上限（`max_round` など）は変えない。** Ruff と pytest は LLM に依存しない。
* **用語**: 本書中の「Aider」は、コード編集エンジン全般（現行は Aider、移行後は agy）を指す箇所がある。状態フィールド名 `aider_message` は、グラフ契約の維持のため名称を変更しない（SBOS-DD-004 §5.1）。

### 1.1 計画適合性検問ゲート (`spec_draft_node` / Defense 0: JEV Plan Conformance)

* **目的**: コード編集エンジン（現行 Aider、移行後 agy）による本格的なコード生成に入る前に、Planner LLM が策定した `impl_plan`（Definition of Done / 実装方針計画）が Issue の要求仕様を逸脱・肥大化（YAGNI 違反・勝手な機能追加）させていないかを水際で検証し、計算資源（現行はローカル GPU、移行後は agy の利用枠）の無駄な浪費と後段の失敗を未然に防止する。
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
  * 最終チェックが非ゼロ終了となった場合、`LINT_ERROR` として扱い、`lint_round` を加算する。累積失敗が `max_round`（3回）に達した時点（3回目の失敗）で `FAILED_B7` にエスカレーションされる。

### 2.2 pytest 実行仕様
* **実行内容**: 
  * 関連テスト、または `tests/test_*.py` を `python -m pytest --json-report` で実行する。
  * `ui` や `gui` を含む名前のフォールバックテストは実行対象から除外する。
* **副作用・失敗契約**: 
  * JSONレポートは `.report.json` に一時保存され、処理終了時に `finally` ブロックで確実に削除される。
  * テストが失敗した場合、`TEST_ERROR` として `test_round` を加算し、累積失敗が `max_round`（3回）に達した時点（3回目の失敗）で `FAILED_B7` にエスカレーションされる。

### 2.3 テスト助言 (`test_feedback_node`)
* **実行内容**: テストが失敗した場合、`test_feedback` intent を用いて Planner LLM に失敗ログを渡し、修正のための助言を生成させる（`call_llm` 経由。実行基盤は移行後 agy、SBOS-DD-005 §4.1）。
* **副作用・失敗契約**: 助言生成自体がLLMエラー等で失敗した場合でも、テスト失敗の事実（rawテスト出力）は維持し、そのまま修正ループ（`retry_code`）へ継続させる。

## 3. Review Adapter (`review_node` / Reviewdog)

### 3.1 LLM レビュー仕様
* **実行内容**: `review_node` は `implementation_plan` と現在の Git diff を Reviewer LLM に渡し、判定（`LGTM` または `changes_requested`）およびコメント配列を要求する。
* **コメントの構造化**: 
  * LLMからのコメントは `file`、`line`、`message`、`severity` を補完して構造化される。
  * `changes_requested` と判定されたにもかかわらずコメントが空の場合は、フェイルセーフとして `LGTM` に自動補正される。
* **フィードバックの反映**:
  * severityが `structural`、`major`、`error` 等の重大な指摘、または対象外ファイルへの指摘がある場合は、その内容をコード編集エンジンへの次回のフィードバック指示（`aider_message`）に優先的に追加する。
  * 修正要求（`changes_requested`）は最大3回まで `retry_code` でコード編集エンジンに差し戻される。
* **応答の契約**: `review_node` は `expect_json=True` で呼び出し、応答の `verdict` が `LGTM` または `changes_requested` でない場合は `FAILED_SYSTEM`（`SYSTEM_ERROR`）として停止する。
* **agy 経路の留意点【移行設計】**: 移行後は agy がレビューを行う。agy が JSON の指示を守らない場合、JSON 抽出のフォールバックは `changes_requested` を返すため、**差し戻しが繰り返されうる**。agy の JSON 遵守率は Issue #127 で確認し、合格基準（100%）を満たすまで、実サテライトでの運用を始めない。JSON のみを出力させる指示は `call_llm` が末尾に追加する（SBOS-DD-005 §4.1）。

### 3.1.1 JEV レビュー合否二次検問ゲート (`review_node` / Defense 3.1: JEV Review Conformance)

* **目的**: Reviewer LLM による JSON 出力の揺らぎや誤認識、パース不備による甘い合否判定を排除し、Reviewer LLM が `LGTM` と判定したコード差分に対して、JEV (Zero-Decode) による決定論的な裏取り検証（二次検問）を行う。未実装の要件や要求外の実装、テスト不整合を水際で遮断する。
* **判定方式**: Zero-Decode 高速判定基盤 JEV (`submodules/jev-localsystem`) の `NoulTask`（規程適合判定）による 39ms 1トークン推論。
* **入力パラメータ**:
  1. `instruction`: Issue 本文および要求仕様
  2. `impl_plan`: Planner LLM が策定した実装計画 (DoD)
  3. `diff_text`: 対象ファイルの Git diff 全文
  4. `pytest_returncode`: 直前の pytest 終了コード
* **判定規程 (Policy)**:
  「この Git 差分（diff）は、Issue の要求仕様（Requirements）および実装計画（DoD）を過不足なく満たしているかを判定せよ。未実装の要件、要求外の実装（YAGNI違反・過剰設計）、不整合、またはテスト失敗がある場合は不適合（No）とする。要求を過不足なく満たしている場合のみ適合（Yes）とする。」
* **状態遷移契約**:
  * **実行契機**: Reviewer LLM が `verdict == "LGTM"` を返した場合のみ実行（LLM が既に `changes_requested` とした場合は JEV をスキップしてそのまま差し戻す）。
  * **適合 (`is_valid == True`)**: `state["review_lgtm"] = True` を確定し、`done_node` へ進行。
  * **不適合 (`is_valid == False`)**: `verdict` を `"changes_requested"` に強制上書き。Aider への次回復帰メッセージ（`aider_message`）に `【JEV REVIEW REJECTED】JEV二次検問により不適合と判定されました: <理由>` を注入し、`retry_code` で差し戻す。
  * **フェイルオープン契約**: JEV 未展開、初期化例外、モデル通信エラー等の異常時は安全にバイパス（`True`）し、Reviewer LLM の判定をそのまま採用してシステム停止を防ぐ。
  * **Ollama 停止時の注意【Epic #116 後】**: JEV は Ollama に依存するため、Ollama を停止すると二次検問は無言でバイパスされ、Reviewer LLM（移行後は agy）の判定のみが採用される。agy 移行後の E2E 検証（Issue #123）は、Ollama を起動したまま行い、JEV を含めた動作を確認する。
  * **監査ログ**: JEV の判定確信度（`confidence`）、レイテンシ、判定ステータスを `review_rounds` 履歴オブジェクトに記録する。

### 3.2 Reviewdog によるアノテーション
* **実行内容**: 構造化されたLLMレビューコメントを RDJSON 形式に変換し、それを標準入力で渡して `reviewdog -f=rdjson -diff="git diff HEAD"` を実行する。
* **副作用・失敗契約**: Reviewdogは補助的な表示機能（CLIやPR上のコメント用）であり、Reviewdog自体の非ゼロ終了や実行例外はログに記録するが、LLMレビュー結果（`review_verdict`）を無効化・中断させることはない。
* **未導入時の扱い（Issue #106）**: 実行前に `shutil.which("reviewdog")` で存在を確認し、PATH に無い場合は実行せずスキップする（INFO ログ1行）。`reviewdog_result` には `{"returncode": null, "skipped": "not_installed"}` を記録し、導入済みで失敗した場合（`returncode` が数値）と区別できるようにする。`tools/doctor.py` の `check_reviewdog` が未導入を `WARN`（任意の依存）として報告する。

## 4. エスカレーション (`escalate_node`)

lint または test が上限回数に到達し修正不可能な場合、`escalate_node` が呼び出される。
* **敗因レポートの生成**: 失敗原因とログを含む敗因レポート（`FAILURE_REPORT_<ISSUE_ID>.md`）の生成を試みる。
* **状態の確定**: レポート作成に成功した場合は最終状態を `ESCALATED_NEEDS_REVISION` とし、失敗時は防御的に `FAILED_B7` または `FAILED_SYSTEM` にフォールバックする。
* **敗因分析の LLM 呼び出し**: `failure_analysis` intent の `call_llm` 呼び出しが例外となった場合は、警告ログのみを残して終了し、`status` は変更しない。レポートは母艦の `metadata/projects/<PROJECT_KEY>/` へ出力し、出力時に `sanitize_text` で機密情報をマスクする（Issue #20・#26）。

# 基本設計書（基本仕様・システム全体アーキテクチャ定義）
**実在 OSS スタック統合による Second Brain OS 再設計（LangGraph / OpenAI 互換 API・agy / Aider・agy / Ruff / Reviewdog）**

| 項目     | 内容                                                                                                                                                                                                                                                          |
| :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 文書番号 | SBOS-BD-002                                                                                                                                                                                                                                                   |
| 版数     | Rev.5.3（Epic #116: LLM 実行基盤の方針を「ローカル完結」から「agy 移行（JEV 据え置き）」へ改訂）                                                                                                                                                              |
| 改訂日   | 2026年11月4日                                                                                                                                                                                                                                                 |
| 作成日   | 2026年7月28日                                                                                                                                                                                                                                                 |
| 関連文書 | SBOS-DD-003（詳細設計書）、SBOS-DD-004（Aider統合仕様）、SBOS-DD-005（Backend仕様）、SBOS-DD-006（品質仕様）、SBOS-DD-007（永続化仕様）、SBOS-MULTI-001（差分設計書）、SBOS-OP-001（運用詳細設計書）、SBOS-ENV-001（環境構築仕様書）、SBOS-PM-005（課題一覧） |
| 対象読者 | システムアーキテクト／リード開発エンジニア／ナレッジマネジメント運用者／DevOps エンジニア                                                                                                                                                                     |

---

## 1. 概要と基本方針

### 1.1 文書の目的と対象範囲
本書は、実績ある OSS を統合して動作する「第二の脳（Second Brain OS）」の自律開発・ナレッジ管理スタックの基本設計を定義する。

> **方針の改訂（Rev.5.3、Epic #116）**: Rev.5.2 までは「クラウド LLM API に依存せず、ローカル環境の Ollama、llama-server を使う」ことを基本前提としていた。この前提を次のとおり改める。
> - **【現行】**: JEV を除く planner / coder / reviewer / failure analyst の LLM 処理は、`config/models.yaml` の routes により **agy（Antigravity CLI）**へルーティングする。agy はクラウド側のモデルを使うため、ソースコード・diff・Issue 本文・ログが外部に送信されうる。外部送信は `backend_execution.agy_external_send` で認可する。
> - **【現行】**: JEV（Zero-Decode 判定）は logprobs を使うため agy へ置き換えず、引き続きローカルの Ollama で動作する。したがって、Ollama は JEV 用の実行基盤として残る。
> - Aider はruntimeから退役済みで、旧実装・設計資産は `legacy/local_llm/` と archive tag に保存する。現行runtimeでAiderへ自動fallbackまたはagyとの同時併用は行わない。
> - agyの認証・外部送信許可・実モデル品質・実サテライトE2Eは、実機環境で別途確認する。置き換え後の設計は SBOS-DD-003 §2.2、SBOS-DD-004、SBOS-DD-005 を正本とする。

本書は採用理由、コンポーネントの責務境界、全体アーキテクチャ、母艦・衛星の隔離方針、運用上の基本前提を扱う。関数の Interface、状態遷移、詳細な外部コマンド仕様、永続化形式、失敗時の振る舞いは [SBOS-DD-003](SBOS-DD-003_%E8%A9%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8.md) および各詳細設計書（[DD-004](SBOS-DD-004_Aider%E7%B5%B1%E5%90%88%E4%BB%95%E6%A7%98.md), [DD-005](SBOS-DD-005_Backend_GPU%E3%83%AA%E3%83%BC%E3%82%B9%E4%BB%95%E6%A7%98.md), [DD-006](SBOS-DD-006_%E5%93%81%E8%B3%AA%E3%82%B2%E3%83%BC%E3%83%88_%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC%E4%BB%95%E6%A7%98.md), [DD-007](SBOS-DD-007_%E6%B0%B8%E7%B6%9A%E5%8C%96_%E6%8E%92%E4%BB%96%E5%88%B6%E5%BE%A1%E4%BB%95%E6%A7%98.md)）を正本とする。

従来の自前ループや自作編集ロジックを、**LangGraph（状態管理・条件分岐グラフ）、agy（テキスト応答・コード編集）、Ruff（一次静的解析）、Reviewdog（差分行アノテーション表示）**を中心とする構成へ置き換えた。JEVはOllamaを直接利用する据え置きモジュールである。Aiderは旧資産としてのみ保持する。

### 1.2 構造的課題と OSS 統合による解決

| 従来自前実装の課題                                    | OSS 統合での解決策                                            | 担当コンポーネント                                |
| :---------------------------------------------------- | :------------------------------------------------------------ | :------------------------------------------------ |
| 手書き `while` ループと状態管理の不透明性             | 宣言的な StateGraph による状態遷移と観測可能な実行履歴        | **LangGraph** (`StateGraph`)                      |
| CLI subprocess 起動による引数長制限・接続管理の複雑さ | OpenAI 互換 HTTP API の直接呼出と intent ごとの endpoint 解決 | **OpenAI SDK** ＋ **BackendExecutionCoordinator** |
| 自作 AST マージの破綻・コード一部消失                 | Git ワーキングツリーへの差分編集と自動コミット抑止            | **Aider** (`aider-chat`)                          |
| 構文エラー等での無駄な LLM トークン消費               | 高速な一次機械チェックと修正ループ                            | **Ruff** ／ **pytest**                            |
| レビュー結果の視覚的アノテーション欠落                | RDJSON を用いた差分行単位の表示                               | **Reviewdog**                                     |
| コンテキスト・状態の分散                              | GraphState と母艦メタデータへの責務分離                       | **LangGraph** ／ `metadata/`                      |

---

## 2. コンポーネント置き換えマッピング

| #    | 旧自前実装                           | 置き換え先                                        | 役割と統合方針                                                                                                                                                                  |
| :--- | :----------------------------------- | :------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | `orchestrator.py` の手書き状態ループ | **LangGraph**                                     | `GraphState` と条件エッジで実行・再試行・終了を制御する。                                                                                                                       |
| 2    | `agent_client.py` の CLI 呼出        | **BackendExecutionCoordinator** ＋ **agy client** | intent に応じて profile を解決し、agyのテキスト応答またはコード編集を実行する。JEVのみOllamaへ直接接続する。                                                                    |
| 3    | Coder Agent と `_merge_python_code`  | **agy**                                           | agyが衛星ワーキングツリーを直接編集する。`edit_guard` が母艦・target_files外・秘密ファイルを保護し、stage、commit、push、PR作成は `done_node` が担当する。Aiderは旧資産である。 |
| 4    | LLM 任せの品質確認                   | **Ruff** ／ **pytest**                            | 自動修正を含む静的解析とテストを品質ゲートとして実行する。                                                                                                                      |
| 5    | 自作レビュープロンプト               | **OpenAI SDK** ＋ **Reviewdog**                   | LLM レビューを構造化し、Reviewdog は補助的に表示する。                                                                                                                          |
| 6    | 未使用の `context_manager.py`        | `GraphState` とメタデータ                         | Graph 内の実行状態と、継続実行に必要な永続状態を分離する。                                                                                                                      |

---

## 3. システム全体アーキテクチャと安全回路

```text
[ tools/orchestrator_graph.py ]  ← LangGraph StateGraph（母艦）

  メタデータ検証・文脈解決・プロジェクトロック取得
         │
         ▼
  spec_draft_node（Planner による実装計画生成）
         │
         ▼
  code_node（agyによる衛星コード編集）
         │
         ▼
  lint_node（Ruff 高速静的解析・自動修正） ── 失敗時は code_node へ
         │
         ▼
  run_pytest_node（pytest 単体テスト） ── 失敗時は test_feedback_node を経て code_node へ
         │
         ▼
  review_node（Reviewer LLM ＋ Reviewdog 出力）
         ├─ LGTM ─► done_node（Git 操作・PR 作成）
         └─ changes_requested ─► code_node または上限到達時に escalate_node
```

> **リトライ安全回路:** lint、test、review の各修正ループは上限試行回数（`max_round`）を持つ。LLM / コード編集エンジンのタイムアウトは全体で共有カウントし、超過時は `FAILED_SYSTEM` として安全停止する。状態遷移や例外分類の厳密な定義は DD-003 を正本とする。

### 3.1 LLM バックエンドの責務分離

`tools/llm_client.py` は role・intent を解決し、agyのテキスト応答を既存の返却形式へ変換する。`BackendExecutionCoordinator` は `config/models.yaml` の intent route に従い、agy backendをGPUリースなしで実行する。JEVはこの経路を通らずOllamaへ直接接続する。具象的なルーティング状態やバックエンド制限事項は DD-003 §2.2 と DD-005 を正本として一元管理する。（loader が読むのは `models.yaml` のみ）

---

## 4. 母艦×衛星 Git 隔離モデルとの整合

1. **`.gitignore` による完全遮断:** 母艦の `.gitignore` により、衛星内の差分および Git 履歴は母艦 Git から完全に隔離する。中央台帳は `metadata/.project-registry.json` に配置する。
2. **メタデータの母艦管理:** `project.json`、`tasks.md`、Issue、`state.json`、ロックは `metadata/projects/<PROJECT_KEY>/` に置き、衛星ソースツリーを汚染しない。
3. **コード編集エンジンのコミット制御:** agyにはcommit / pushをさせず、コード編集だけを許可する。stage、commit、push、PR作成は `done_node` が担当する。
4. **人間承認を残す PR 運用:** 成功時に作業ブランチから PR を作成する。運用者は成果物を確認し、マージ可否を判断する。PR 失敗時には差分・ブランチを保持し停止する。

---

## 5. 動作前提およびシステム境界

- **基本動作環境:** Linux、macOS、Windows Native。依存パッケージは `pyproject.toml` にて管理する。
- **文字コード・改行方針:** 差分の意図しない増大や表示文字化けを防ぐため、リポジトリ単位の改行コード方針および標準 UTF-8 入出力を適用する。
- **品質・監査ツール:** Ruff、pytest、Reviewdog を品質ゲートおよび視覚的フィードバックとして利用する。

### 5.1 運用インターフェースと将来構想

- **標準エントリポイント:** `uv run python tools/orchestrator_graph.py orchestrate` で実行計画を表示し、`uv run python tools/orchestrator_graph.py execute --issue-id <ISSUE_ID> --project-key <PROJECT_KEY> --fresh` でLangGraphを起動する。
- **補助ラッパー:** `uv run python tools/run_task.py <ISSUE_ID> --fresh` は衛星リポジトリのクリーンアップ後にexecuteを起動する。夜間運用は `uv run python tools/nightly_task_worker.py --config config/nightly_worker.toml` を使う。
- **agy起動:** `tools/agy_client.py` が `agy --dangerously-skip-permissions -p <prompt>` を非対話subprocessとして起動する。実行ファイル解決、timeout、終了コード分類はagy clientが担当する。
- **将来構想:** 自動優先度計算バッチ、定期スクラミング、外部通知連携等は現行自律実行基盤の枠外とし、将来拡張機能として位置づける。

---

## 6. 基本設計における変更管理

- 新たな LLM 用途は role・intent・route・profile を明示し、暗黙のモデル選択を導入しない。
- 新しい状態、外部ツール、Git 操作を追加する場合は、DD-003 の状態遷移・副作用・永続化・テスト対応を同時に更新する。
- 本書はコード全文や詳細なコマンド引数を重複掲載しない。ただし採用理由、コンポーネントの責務、システム境界、運用上の前提方針は継続して本書で管理する。
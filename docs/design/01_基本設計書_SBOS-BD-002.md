# 基本設計書（基本仕様・システム全体アーキテクチャ定義）
**実在 OSS スタック統合による Second Brain OS 再設計（LangGraph / OpenAI 互換 API / Aider / Ruff / Reviewdog）**

| 項目     | 内容                                                                                                                                            |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-BD-002                                                                                                                                     |
| 版数     | Rev.5.1（スリム化・レイヤー分離最適化版）                                                                                                       |
| 改訂日   | 2026年8月8日                                                                                                                                    |
| 作成日   | 2026年7月28日                                                                                                                                   |
| 関連文書 | SBOS-DD-003（詳細設計書）、SBOS-MULTI-001（差分設計書）、SBOS-OP-001（運用詳細設計書）、SBOS-ENV-001（環境構築仕様書）、SBOS-PM-005（課題一覧） |
| 対象読者 | システムアーキテクト／リード開発エンジニア／ナレッジマネジメント運用者／DevOps エンジニア                                                       |

---

## 1. 概要と基本方針

### 1.1 文書の目的と対象範囲
本書は、クラウド LLM API に依存せず、ローカル環境の Ollama、llama-server、および実績ある OSS を統合して動作する「第二の脳（Second Brain OS）」の自律開発・ナレッジ管理スタックの基本設計を定義する。

本書は採用理由、コンポーネントの責務境界、全体アーキテクチャ、母艦・衛星の隔離方針、運用上の基本前提を扱う。関数の Interface、状態遷移、詳細な外部コマンド仕様、永続化形式、失敗時の振る舞いは SBOS-DD-003 を正本とする。

従来の自前ループや自作編集ロジックを、**LangGraph（状態管理・条件分岐グラフ）、OpenAI SDK を利用する OpenAI 互換 API 呼出、Aider（コード編集）、Ruff（一次静的解析）、Reviewdog（差分行アノテーション表示）**を中心とする構成へ置き換える。

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

| #    | 旧自前実装                           | 置き換え先                                        | 役割と統合方針                                                                                |
| :--- | :----------------------------------- | :------------------------------------------------ | :-------------------------------------------------------------------------------------------- |
| 1    | `orchestrator.py` の手書き状態ループ | **LangGraph**                                     | `GraphState` と条件エッジで実行・再試行・終了を制御する。                                     |
| 2    | `agent_client.py` の CLI 呼出        | **OpenAI SDK** ＋ **BackendExecutionCoordinator** | intent に応じて profile を解決し、Ollama または llama-server の OpenAI 互換 endpoint を使う。 |
| 3    | Coder Agent と `_merge_python_code`  | **Aider**                                         | `--no-auto-commits` を常に付与し、衛星ワーキングツリーだけを編集する。                        |
| 4    | LLM 任せの品質確認                   | **Ruff** ／ **pytest**                            | 自動修正を含む静的解析とテストを品質ゲートとして実行する。                                    |
| 5    | 自作レビュープロンプト               | **OpenAI SDK** ＋ **Reviewdog**                   | LLM レビューを構造化し、Reviewdog は補助的に表示する。                                        |
| 6    | 未使用の `context_manager.py`        | `GraphState` とメタデータ                         | Graph 内の実行状態と、継続実行に必要な永続状態を分離する。                                    |

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
  code_node（Aider による衛星コード編集）
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

> **リトライ安全回路:** lint、test、review の各修正ループは上限試行回数（`max_round`）を持つ。LLM / Aider のタイムアウトは全体で共有カウントし、超過時は `FAILED_SYSTEM` として安全停止する。状態遷移や例外分類の厳密な定義は DD-003 を正本とする。

### 3.1 LLM バックエンドの責務分離

`tools/llm_client.py` は OpenAI 互換 API 経由で LLM を呼び出す。`BackendExecutionCoordinator` は `config/models.json` で定義された intent ルートに従い、プロファイル解決と GPU リース管理を行う。具象的なルーティング状態やバックエンド制限事項は DD-003 を正本として一元管理する。

---

## 4. 母艦×衛星 Git 隔離モデルとの整合

1. **`.gitignore` による完全遮断:** 母艦の `.gitignore` により、衛星内の差分および Git 履歴は母艦 Git から完全に隔離する。中央台帳は `metadata/.project-registry.json` に配置する。
2. **メタデータの母艦管理:** `project.json`、`tasks.md`、Issue、`state.json`、ロックは `metadata/projects/<PROJECT_KEY>/` に置き、衛星ソースツリーを汚染しない。
3. **Aider のコミット制御:** Aider にはコミット自動化を抑止するフラグ（`--no-auto-commits`）を指定し、コード編集のみを許可する。stage、commit、push、PR 作成は `done_node` が担当する。
4. **人間承認を残す PR 運用:** 成功時に作業ブランチから PR を作成する。運用者は成果物を確認し、マージ可否を判断する。PR 失敗時には差分・ブランチを保持し停止する。

---

## 5. 動作前提およびシステム境界

- **基本動作環境:** Linux、macOS、Windows Native。依存パッケージは `pyproject.toml` にて管理する。
- **文字コード・改行方針:** 差分の意図しない増大や表示文字化けを防ぐため、リポジトリ単位の改行コード方針および標準 UTF-8 入出力を適用する。
- **品質・監査ツール:** Ruff、pytest、Reviewdog を品質ゲートおよび視覚的フィードバックとして利用する。

### 5.1 運用インターフェースと将来構想

- **標準エントリポイント:** CLI（`orchestrator_graph.py`）が自律グラフ実行および優先度表示の役割を担う。
- **補助ラッパー:** `run_task.py` は衛星リポジトリの事前クリーンアップを伴う実行ラッパーとして機能する。
- **将来構想:** 自動優先度計算バッチ、定期スクラミング、外部通知連携等は現行自律実行基盤の枠外とし、将来拡張機能として位置づける。

---

## 6. 基本設計における変更管理

- 新たな LLM 用途は role・intent・route・profile を明示し、暗黙のモデル選択を導入しない。
- 新しい状態、外部ツール、Git 操作を追加する場合は、DD-003 の状態遷移・副作用・永続化・テスト対応を同時に更新する。
- 本書はコード全文や詳細なコマンド引数を重複掲載しない。ただし採用理由、コンポーネントの責務、システム境界、運用上の前提方針は継続して本書で管理する。
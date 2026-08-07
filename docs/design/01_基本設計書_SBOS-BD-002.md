# 基本設計書（基本仕様・システム全体アーキテクチャ定義）
**実在 OSS スタック統合による Second Brain OS 再設計（LangGraph / OpenAI 互換 API / Aider / Ruff / Reviewdog）**

| 項目     | 内容                                                                                                                                            |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-BD-002                                                                                                                                     |
| 版数     | Rev.5.0（現行実装整合・既存構成維持版）                                                                                                         |
| 改訂日   | 2026年8月7日                                                                                                                                    |
| 作成日   | 2026年7月28日                                                                                                                                   |
| 関連文書 | SBOS-DD-003（詳細設計書）、SBOS-MULTI-001（差分設計書）、SBOS-OP-001（運用詳細設計書）、SBOS-ENV-001（環境構築仕様書）、SBOS-PM-005（課題一覧） |
| 対象読者 | システムアーキテクト／リード開発エンジニア／ナレッジマネジメント運用者／DevOps エンジニア                                                       |

---

## 1. 概要と基本方針

### 1.1 文書の目的と対象範囲
本書は、クラウド LLM API に依存せず、ローカル環境の Ollama、llama-server、および実績ある OSS を統合して動作する「第二の脳（Second Brain OS）」の自律開発・ナレッジ管理スタックの基本設計を定義する。

本書は採用理由、コンポーネントの責務境界、全体アーキテクチャ、母艦・衛星の隔離方針、環境上の前提を扱う。関数の Interface、状態遷移、外部コマンド、永続化形式、失敗時の詳細な振る舞いは SBOS-DD-003 Rev.5.0 を正本とする。

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

## 2. コンポーネント置き換えマッピング

| #    | 旧自前実装                           | 置き換え先                                        | 役割と統合方針                                                                                |
| :--- | :----------------------------------- | :------------------------------------------------ | :-------------------------------------------------------------------------------------------- |
| 1    | `orchestrator.py` の手書き状態ループ | **LangGraph**                                     | `GraphState` と条件エッジで実行・再試行・終了を制御する。                                     |
| 2    | `agent_client.py` の CLI 呼出        | **OpenAI SDK** ＋ **BackendExecutionCoordinator** | intent に応じて profile を解決し、Ollama または llama-server の OpenAI 互換 endpoint を使う。 |
| 3    | Coder Agent と `_merge_python_code`  | **Aider**                                         | `--no-auto-commits` を常に付与し、衛星ワーキングツリーだけを編集する。                        |
| 4    | LLM 任せの品質確認                   | **Ruff** ／ **pytest**                            | 自動修正を含む静的解析とテストを品質ゲートとして実行する。                                    |
| 5    | 自作レビュープロンプト               | **OpenAI SDK** ＋ **Reviewdog**                   | LLM レビューを構造化し、Reviewdog は補助的に表示する。                                        |
| 6    | 未使用の `context_manager.py`        | `GraphState` とメタデータ                         | Graph 内の実行状態と、継続実行に必要な永続状態を分離する。                                    |

## 3. システム全体アーキテクチャと安全回路

```text
[ tools/orchestrator_graph.py ]  ← LangGraph StateGraph（母艦）

  メタデータ検証・文脈解決・プロジェクトロック取得
         │
         ▼
  spec_draft_node（Planner による実装計画生成）
         │
         ▼
  code_node（Aider による衛星コード編集: --no-auto-commits）
         │
         ▼
  lint_node（Ruff format / fix / check） ── 失敗時は code_node へ
         │
         ▼
  run_pytest_node（pytest + JSON report） ── 失敗時は test_feedback_node を経て code_node へ
         │
         ▼
  review_node（Reviewer LLM ＋ Reviewdog）
         ├─ LGTM ─► done_node（Git 操作・PR 作成）
         └─ changes_requested ─► code_node または上限到達時に escalate_node
```

> **リトライ安全回路:** lint、test、review の各修正ループは `max_round`（現行既定値 3）で上限を持つ。LLM または Aider の timeout は実行全体で共有して数え、初回のみ再試行、2回目は `FAILED_SYSTEM` として停止する。状態名、条件、例外分類は DD-003 §5 を正本とする。

### 3.1 LLM バックエンドの責務分離

`tools/llm_client.py` は LiteLLM の `completion()` ではなく、`OpenAI(base_url=..., api_key="local")` により OpenAI 互換 API を呼び出す。`BackendExecutionCoordinator` は `config/models.json` の intent route から profile を解決し、GPU リースを取得した上で backend Adapter を実行する。

現行設定ではすべての route が Ollama profile を選択する。llama-server profile は設定に定義されるが route から選択されず、`fallback` による別 profile への自動再試行も実装されていない。この制約を前提にモデル配置・障害対応を設計する。

---

## 4. 母艦×衛星 Git 隔離モデルとの整合

1. **`.gitignore` による完全遮断:** 母艦の `.gitignore` にある `/projects/*`、`/projects/.*` により、衛星内の差分および Git 履歴は母艦 Git から隔離する。中央台帳は `metadata/.project-registry.json` に配置する。
2. **メタデータの母艦管理:** `project.json`、`tasks.md`、Issue、`state.json`、ロックは `metadata/projects/<PROJECT_KEY>/` に置き、衛星ソースツリーを汚染しない。
3. **Aider のコミット制御:** Aider には `--no-auto-commits` を指定し、編集だけを許可する。stage、commit、push、PR 作成は `done_node` が担当する。
4. **人間承認を残す PR 運用:** 成功時に作業ブランチから PR を作成する。運用者は成果物を確認し、マージ可否を判断する。PR 失敗時には差分・ブランチを保持し、`PR_FAILED` として記録する。

---

## 5. 動作前提および Windows Native 環境特有の制約

- **対応 OS:** Windows Native、Linux、macOS。
- **依存管理:** `pyproject.toml` を正本とし、開発環境は `uv sync --extra dev` で構築する。
- **LLM サーバー:** `BackendExecutionCoordinator` の制御下で Ollama と llama-server を排他的に利用できる。GPU リース待機時間は `config/models.json` の `gpu_lease_timeout` で設定する。
- **品質ツール:** Ruff は `--unsafe-fixes` を含む自動修正を行う。pytest 実行には `pytest-json-report` が必要である。Reviewdog は補助的な出力であり、失敗しても LLM レビューの判定を無効化しない。
- **改行コード:** Aider による差分の不要な拡大を避けるため、リポジトリ単位の改行コード方針を統一する。Windows で `core.autocrlf` を変更する場合は、既存リポジトリへの影響を確認してから実施する。
- **PowerShell 文字コード:** 日本語パス・プロンプトを扱うセッションでは UTF-8 出力設定を使用する。`scripts/windows/setup_reviewdog.ps1` は `$PROFILE` を変更せず、必要な設定を案内する。

### 5.1 運用入口と未実装の構想

現行の CLI は次の二つである。

```text
uv run python tools/orchestrator_graph.py orchestrate [--project-key <PROJECT_KEY>]
uv run python tools/orchestrator_graph.py execute --issue-id <ISSUE_ID> [--project-key <PROJECT_KEY>] [--resume] [--fresh]
```

`orchestrate` は既存の priority cache を表示するだけで、優先度計算や Issue 実行はしない。日次バッチ、`score-issues.py`、`check-blockers.py`、`notify.py`、`verify_environment.py`、Task Scheduler／cron への登録は現行実装には含まれない。これらを導入する場合は、キャッシュ生成の責務、失敗時の扱い、通知先、認可を別途設計・実装する。

### 5.2 破壊的な補助ラッパー

`tools/run_task.py` は既定で `git checkout -f`、`git reset --hard`、`git clean -fd` を実行し、未コミット変更と未追跡ファイルを破棄する。通常の実行入口は `orchestrator_graph.py execute` とし、`run_task.py` を使用する場合は `--dry-run` で予定操作を確認し、必要に応じて `--no-clean` または `--resume` を指定する。

---

## 6. 基本設計における変更管理

- 新たな LLM 用途は role・intent・route・profile を明示し、暗黙のモデル選択を導入しない。
- 新しい状態、外部ツール、Git 操作を追加する場合は、DD-003 の状態遷移・副作用・永続化・テスト対応を同時に更新する。
- `target_files` は初期の編集ガイドラインであり、実装は Aider 成功後に変更済み Python ファイルを追加し得る。この制約を変更する場合は、stage・PR の対象制限を含めた設計判断が必要である。
- 本書はコード全文や詳細な疑似コードを重複掲載しない。ただし採用理由、コンポーネントの責務、システム境界、運用上の前提は継続して本書で管理する。
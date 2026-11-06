# 詳細設計書（コンポーネント詳細・データフロー・実装仕様）
**LangGraph / agy Backend / agy コード編集 / JEV（Ollama据え置き）/ Ruff / Reviewdog 統合実装仕様**

| 項目     | 内容                                                                                                  |
| :------- | :---------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-DD-003                                                                                           |
| 版数     | Rev.6.5（agy移行完了後の現行経路・Aider退役・起動方法を反映）                                         |
| 改訂日   | 2026年11月4日                                                                                         |
| 作成日   | 2026年7月28日                                                                                         |
| 実装正本 | `tools/`、`config/models.yaml`、`metadata/.project-registry.json`、`metadata/projects/<PROJECT_KEY>/` |
| 対象読者 | 実装担当エンジニア、運用担当者、テスト担当者                                                          |

> **記載区分（Rev.6.5 以降）**: 本書は現行実装を正本として記述する。agyへの移行が完了したため、移行済みのagy経路には「移行設計・未実装」を付けない。未導入のagy CLI・認証・実機品質試験は、設計上の未確認事項として試験書に記載する。
>
> Aiderはruntimeから退役済みで、旧実装は `legacy/local_llm/` と archive tag に保存する。`aider_edit` や `aider_message` は互換性のための識別子として残るが、現行routeはagyのみであり、自動fallbackは行わない。

---

## 1. 目的・適用範囲

本書は、衛星リポジトリの Issue を対象に、計画生成、コード編集、静的解析、テスト、LLM レビュー、PR 作成までを実行するオーケストレーターの詳細設計を定義する。実装の正本は本書ではなく `tools/` 配下のコードである。本書は、呼び出し側が知るべき Interface、状態遷移、不変条件、外部ツールとの seam、永続化・監査・運用上の制約を定義する。

対象は `orchestrator_graph.py` を中心とした実行基盤であり、衛星プロダクトの業務ロジック、優先度キャッシュの生成、モデル評価ツール `tools/model_test/eval_simpleqa.py` は対象外とする。

### 1.1 設計原則

- **実装正本**: Module の振る舞い・引数・例外は実装コードを正とし、本書では実装を複製しない。
- **隔離**: 母艦のメタデータ（Metadata Store）と衛星リポジトリを分離し、衛星内の Git 操作は解決済み `cwd` でのみ行う。
- **明示的な route**: LLM の intent は `config/models.yaml` の route でプロファイルへ明示的に対応付ける。（Rev.6.4 で `models.json` から訂正。loader が読むのは `models.yaml` のみ。SBOS-DD-005 §2）
- **fail-safe**: プロジェクト文脈、Git、LLM、品質ゲートの例外は状態・履歴へ記録し、安全に停止する。
- **最小権限**: agyの編集対象とGitのstage対象は `target_files` と `allowed_new_file_globs` を基準に制限する。`edit_guard` が母艦誤編集、秘密ファイル、対象外変更を拒否または復元する。

## 2. 全体アーキテクチャ

```mermaid
flowchart LR
    CLI[CLI / run_task] --> ORCH[Orchestrator Module]
    ORCH --> META[Metadata Store / Access]
    ORCH --> GRAPH[LangGraph Workflow]
    GRAPH --> LLM[LLM Module]
    LLM --> COORD[Backend Coordinator]
    COORD --> OLLAMA[Ollama Adapter]
    COORD --> LLAMA[llama-server Adapter]
    COORD --> AGYB[agy Backend Adapter]
    GRAPH --> EDIT[agy Runner]
    EDIT --> GUARD[edit_guard]
    AGYB --> AGYC[agy Client]
    EDIT --> AGYC[agy Client]
    GRAPH --> JEV[JEV Adapter / 据え置き]
    JEV --> OLLAMAJ[Ollama 直接接続]
    GRAPH --> QUALITY[Ruff / pytest / Reviewdog]
    GRAPH --> GIT[Git / GitHub CLI]
    META --> STATE[state.json / execution history]
```

### 2.1 Module と Interface

| Module                   | Interface                                                                                  | 責務                                                                                                        |
| :----------------------- | :----------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------- |
| `orchestrator_graph.py`  | `execute_issue()`、`cmd_orchestrate()`、`main()`                                           | 実行前検証、Git ブランチ準備、LangGraph 実行。                                                              |
| `metadata_store.py`      | `update_task_state()`, `record_execution_history()`, `write_event()`, `ProjectLockManager` | プロジェクト台帳・タスク状態・実行履歴・排他ロック管理。                                                    |
| `sanitizer.py`           | `sanitize_text()`, `sanitize_data()`                                                       | 機密情報（キー、トークン、秘密鍵、パスワード、メール等）のマスキング。                                      |
| `config_loader.py`       | `load_model_config()`、各 `get_*_config()`                                                 | Pydantic による設定検証と設定値の提供。                                                                     |
| `llm_client.py`          | `call_llm()`                                                                               | role・intent・設定からサニタイズ済みpromptを構成し、agyのテキスト応答を既存の返却形式へ変換する。           |
| `backend_coordinator.py` | `BackendExecutionCoordinator.execute()`                                                    | intentのprofile解決とBackend Adapter選択。agyはGPUリースなしで実行する。                                    |
| `agy_client.py`          | `run_agy_text()`、`run_agy_in_workdir()`                                                   | agy実行ファイル解決、`--dangerously-skip-permissions -p`起動、timeout、プロセスツリー終了、終了コード分類。 |
| `agy_runner.py`          | `run_agy_edit()`                                                                           | agyによる作業ツリー編集とedit_guardの適用。                                                                 |
| `jev_adapter.py`         | `verify_plan_conformance()`、`verify_review_conformance()`                                 | JEV Core SDK (NoulTask) を用いた Zero-Decode 判定。**据え置き**（Ollama に直接接続、DD-005 §1.1）。         |
| `run_task.py`            | `clean_satellite_repository()`、`main()`                                                   | 排他ロック保護下でのクリーンアップおよびオーケストレーター起動ラッパー。                                    |

### 2.2 LLM使用箇所と現行経路

JEVを除くLLM使用箇所は、`intent → routes → profile → agy backend` の流れで実行する。呼び出し側のシグネチャと返り値は維持する。

| #    | 使用箇所                                         | 現行経路                            | 詳細                  |
| :--- | :----------------------------------------------- | :---------------------------------- | :-------------------- |
| 1    | `code_node`（intent `code_edit` / `aider_edit`） | agyが作業ツリーを直接編集           | DD-004 §3、edit_guard |
| 2    | `spec_draft_node`（intent `spec_draft`）         | agyテキスト応答                     | DD-005 §4.1           |
| 3    | `test_feedback_node`（intent `test_feedback`）   | agyテキスト応答                     | DD-005 §4.1           |
| 4    | `review_node` / `escalate_node`                  | agyテキスト応答（reviewはJSON契約） | DD-005 §4.1、DD-006   |
| —    | JEV（`jev_adapter.py`、`screen_issues.py`）      | Ollamaへ直接接続、据え置き          | DD-005 §1.1           |

* 現行routeは `config/models.yaml` の `agy_default` を指す。旧Aider経路への復旧は、legacy/archive資産を復元する別作業であり、単純なroute変更では戻らない。
* agy の失敗時に、自動でローカルへフォールバックしない（§10.1）。
* 進捗: 契約検証 #117、`agy_client` #119、backend 追加 #120、`call_llm` 対応 #121、`code_node` 対応 #122、書き込み境界ガード #125、クォータ・障害中断ガード #126、新規ファイル許可 #102、routes 切り替え #123 まで実装完了。グラフ契約および状態遷移（外側契約）は完全不変。

- **agy client**: `agy --dangerously-skip-permissions -p <prompt>` を非対話subprocessとして起動する。テキスト応答は空の一時ディレクトリ、コード編集は解決済み衛星cwdで実行する。
- **実行入口**: `orchestrator_graph.py execute` が標準入口、`run_task.py` がクリーンアップ付きラッパー、`nightly_task_worker.py` が夜間反復実行を担当する。
- **prompt SSOT**: `config/prompt.yaml` を `tools/prompt_harness.py` が role・intent別に解決し、coder指示にはengine固有の安全規則を追加する。

👉 **[SBOS-DD-005_Backend_GPUリース仕様.md](SBOS-DD-005_Backend_GPUリース仕様.md)**

## 4. プロジェクト・メタデータ設計

ディレクトリ構成、メタデータ形式の詳細については、以下を参照すること。

👉 **[SBOS-DD-007_永続化_排他制御仕様.md](SBOS-DD-007_永続化_排他制御仕様.md)**

`resolve_project_context()` は順に `project.json.target_files`、`tasks.md` 内の Python パス、衛星内の Python ファイル探索から候補を得る。Issue 詳細ファイルに Target Files がある場合はそれを優先し、実在しない Python パスはファイル名の近似で衛星内ファイルへ補正する。衛星は `.git` が存在するディレクトリでなければ無効とする。

## 5. 実行ライフサイクル

### 5.1 実行開始前の契約

`execute_issue(issue_id, project_key, ..., resume=None, fresh=False)` は以下を順に実行する。

1. Issue ID とプロジェクトメタデータの整合性を検証する。
2. 衛星の `cwd`、対象ファイル、base branch、作業ブランチ prefix を解決する。無効な文脈ではagyを起動せず `FAILED_SYSTEM` を記録する。
3. `ProjectLockManager` で `metadata/projects/<PROJECT_KEY>/.lock` を取得する。競合時は `SKIPPED_LOCKED` と `LOCKED` を記録し、イベントファイルを作成して終了する。
4. Git ワークツリーを確認し、実行モードに応じて作業ブランチを準備する。
5. 初期 `GraphState` を生成して LangGraph を実行し、終了後に `state.json` と実行履歴を原子的に保存する。

### 5.2 Git ブランチ準備

| モード | 選択条件                                                                                   | 振る舞い                                                                                                                   |
| :----- | :----------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| Resume | `--resume`、または既存 state が `CHANGES_REQUESTED`、`PR_FAILED`、`FAILED_B7`、`IN_REVIEW` | 既存作業ブランチへ switch し、base branch へ rebase する（失敗時は中断）。未コミット差分は生成物を除いて WIP commit する。 |
| Fresh  | 上記以外、または `--fresh`                                                                 | base branch へ switch、`pull --ff-only`、既存の作業ブランチを削除し、base branch から再作成する。                          |

Fresh モードで既存の作業ブランチに未マージコミットがある場合（または未マージの監査に失敗した場合）は、強制削除せず `backup/<作業ブランチ>-<YYYYMMDDHHMMSS>` へリネームして退避してから再作成する。退避に失敗した場合は `FAILED_SYSTEM` で中断する。

**Resume の Git 安全性（Issue #92）**:

- **WIP コミットの対象**: dirty な作業ツリーは、生成物を除外して `git add -A -- . ':(exclude,glob)…'` でステージし、`wip: preserve uncommitted changes for <ISSUE_ID> before resume` でコミットする。除外対象は `tools/metadata_store.py` の定数 `GENERATED_ARTIFACT_GITIGNORE_ENTRIES`（`.aider*`、`.pytest_cache/`、`__pycache__/`、`.venv/`、`*.pyc`、`.ruff_cache/`、`.mypy_cache/`）から導出した `GENERATED_ARTIFACT_PATTERNS` で、dirty 判定と WIP の pathspec が共有する。同じ定義を `doctor.py` の `.gitignore` チェックと `ensure_satellite_gitignore` も使い、衛星の `.gitignore` に不足があれば警告・追記する（`.gitignore` が存在しない場合は新規作成しない）。照合はパスの要素単位で行い、`my.aider_notes.md` のような部分一致は除外しない。
- **WIP コミットの失敗**: `git add` の失敗、またはステージ済みの変更があるのに `git commit` が失敗した場合は、`FAILED_SYSTEM` で中断する。ステージ済みの変更が無い場合（除外後に何も残らない等）は、コミットを飛ばして続行する。
- **rebase の失敗**: base branch への rebase に失敗した場合は `rebase --abort` で元に戻し、衝突内容を記録して `FAILED_SYSTEM` で中断する。人が手動で解決するか、`--fresh` で作り直す。`FAILED_SYSTEM` は `consecutive_b7` を増やさず、自動 Resume の対象にもならない。

**連続 FAILED_B7 ガード**: `--resume` / `--fresh` を指定せず、既存 state の `status` が `FAILED_B7` で `consecutive_b7` が 2 以上のときは、自動 Resume を行わず実行を拒否して人に返す。この拒否では `state.json` を変更せず、拒否した事実だけを実行履歴に記録する。明示的な `--resume` / `--fresh` はこのガードを無視して実行できる。`consecutive_b7` の更新規則は §5.6 を参照する。

通常の実行で dirty working tree が見つかった場合は停止する。`allow_offline_git=True` を指定したプログラム呼び出しだけが、base branch の pull 失敗後も継続できる。作業ブランチの初期名は `project.json.work_branch_prefix` または `sbos/` と Issue ID の結合である。

### 5.3 GraphState

`GraphState` は LangGraph 内部の共有状態であり、外部永続化スキーマではない。

| 区分           | フィールド                                                                                                                   |
| :------------- | :--------------------------------------------------------------------------------------------------------------------------- |
| 識別・文脈     | `issue_id`、`project_key`、`execution_id`、`generation`、`cwd`、`base_branch`、`target_files`、`instruction`                 |
| 制御・失敗     | `status`、`error`、`error_category`、`llm_timeout_count`、`lint_round`、`test_round`、`review_round`、`max_round`            |
| 生成・品質結果 | `impl_plan`、`aider_message`、`test_feedback_instruction`、`lint_result`、`test_result`、`review_verdict`、`review_comments` |
| 監査結果       | `review_rounds`、`rdjson`、`reviewdog_result`、`history_summary`                                                             |

初期状態は `status='running'`、各 round と `llm_timeout_count` は 0、`max_round` は 3 とする。`TypedDict` は実行時検証を行わないため、各 node は存在しない任意値を `get()` または `setdefault()` で扱う。

#### Status taxonomy

| 区分                        | status                                                                                  | 役割・意味                                                      |
| :-------------------------- | :-------------------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| 実行中・中間状態            | `running`、`code_completed`、`lint_passed`、`test_passed`、`review_lgtm`                | LangGraph のノード間を遷移する進行中状態。                      |
| 再試行指示                  | `retry_spec_draft`、`retry_code`、`retry_review`                                        | 各ノード（品質判定やタイムアウト）からの再実行シグナル。        |
| 終端・成功                  | `COMPLETED`                                                                             | PR 作成または既存 PR 検出により正常完了した終端状態。           |
| 終端・失敗/エスカレーション | `FAILED_SYSTEM`、`FAILED_B7`、`ESCALATED_NEEDS_REVISION`、`PR_FAILED`、`SKIPPED_LOCKED` | ロック競合、システムエラー、品質上限超過、PR 失敗等の終端状態。 |

この分類は文書上の整理であり、現行実装では `status` は任意文字列 (`str`) として保持される。実装自体は安定稼働しているため即時の全面書き換えは不要だが、次回以降のリファクタリングにおいて Python の `Literal` または `Enum` として型安全に厳密化する。新しい status を追加する際は、§5.5 の遷移表、`state.json`、実行履歴、統合テストを同時に更新する。

### 5.4 正常系シーケンス

正常系では、品質検証とレビューが1回で完了する。再試行・例外は §5.5 と §5.6 を参照する。

```mermaid
sequenceDiagram
    actor Operator as 運用者
    participant CLI as Orchestrator CLI
    participant Meta as Metadata / Lock
    participant Git as Satellite Git
    participant Plan as Planner LLM
    participant Agy as agyコード編集
    participant Quality as Ruff / pytest
    participant Review as Reviewer / Reviewdog
    participant PR as GitHub CLI
    participant Audit as State / History

    Operator->>CLI: execute --issue-id
    CLI->>Meta: 整合性検証と文脈解決
    Meta-->>CLI: cwd、target_files、branch
    CLI->>Meta: プロジェクトロック取得
    CLI->>Git: 作業ブランチ準備
    CLI->>Plan: 実装計画を生成
    Plan-->>CLI: impl_plan
    CLI->>Aider: 指示と対象ファイルで編集
    Aider-->>CLI: 編集完了
    CLI->>Quality: Ruff format / fix / check
    Quality-->>CLI: lint_passed
    CLI->>Quality: pytest JSON report
    Quality-->>CLI: test_passed
    CLI->>Review: diff を LLM レビューし RDJSON を出力
    Review-->>CLI: review_lgtm
    CLI->>PR: stage、commit、push、PR 作成
    PR-->>CLI: COMPLETED
    CLI->>Audit: state と実行履歴を保存
    CLI->>Meta: ロック解放
```

### 5.5 状態遷移表

| 実行 node            | 成功時の status と次 node                                         | 再試行時の status と次 node                             | 終端・停止                                                       |
| :------------------- | :---------------------------------------------------------------- | :------------------------------------------------------ | :--------------------------------------------------------------- |
| `spec_draft_node`    | `running` (計画適合) → `code_node`                                | `retry_spec_draft` (timeout または YAGNI違反) → 同 node | `FAILED_B7` (計画不適合上限) / `FAILED_SYSTEM` → `escalate_node` |
| `code_node`          | `code_completed` → `lint_node`                                    | `retry_code` → 同 node                                  | `FAILED_SYSTEM` → `escalate_node`                                |
| `lint_node`          | `lint_passed` → `test_node`                                       | `retry_code` → `code_node`                              | `FAILED_B7` / `FAILED_SYSTEM` → `escalate_node`                  |
| `run_pytest_node`    | `test_passed` → `review_node`                                     | テスト失敗 → `test_feedback_node`                       | `FAILED_B7` / `FAILED_SYSTEM` → `escalate_node`                  |
| `test_feedback_node` | `retry_code` → `code_node`                                        | —                                                       | `FAILED_SYSTEM` → `escalate_node`                                |
| `review_node`        | `review_lgtm` → `done_node`                                       | `retry_review` → 同 node、`retry_code` → `code_node`    | `FAILED_B7` / `FAILED_SYSTEM` → `escalate_node`                  |
| `done_node`          | `COMPLETED` → 終了                                                | —                                                       | `PR_FAILED` → 終了                                               |
| `escalate_node`      | `FAILED_B7` / `FAILED_SYSTEM` / `ESCALATED_NEEDS_REVISION` → 終了 | —                                                       | —                                                                |

### 5.6 例外・再試行フロー

```mermaid
flowchart TD
    Start[Node の失敗] --> Type{失敗種別}
    Type -->|LLM またはコード編集エンジン timeout| Timeout[llm_timeout_count を加算]
    Timeout --> Limit{count >= 2?}
    Limit -->|No| RetryLLM[該当 node を再試行]
    Limit -->|Yes| System[FAILED_SYSTEM]
    Type -->|計画適合性 YAGNI 違反| PlanRound[plan_conformance_round を加算]
    PlanRound --> PlanLimit{round >= 2?}
    PlanLimit -->|No| RetrySpec[retry_spec_draft で再計画]
    PlanLimit -->|Yes| B7
    Type -->|lint / test / review の失敗| Round[対応する round を加算]
    Round --> RoundLimit{round >= max_round?}
    RoundLimit -->|No: lint/review| Code[code_node へ戻る]
    RoundLimit -->|No: test| Feedback[test_feedback_node 経由で code_node へ戻る]
    RoundLimit -->|Yes| B7[FAILED_B7]
    Type -->|その他の node 例外| System
    Type -->|Git / PR 失敗| PRFail[PR_FAILED]
    System --> Escalate[escalate_node]
    B7 --> Escalate
    Escalate --> Persist[状態・履歴を保存して終了]
    PRFail --> Persist
```

`llm_timeout_count` は planner、agyコード編集、reviewer 間で共有される。異なるnodeのtimeoutも合算され、2回目で `FAILED_SYSTEM` となる。判定は例外メッセージの文字列（`timeout` / `timed out`）で行うため、**agy のタイムアウトのメッセージにも `timed out` を含めることが契約**である（DD-004 §3.2）。`spec_draft_node` の計画適合性（DoD YAGNI検問）が不適合（`rejected`）となった場合、`plan_conformance_round` を加算して最大2回まで再ドラフトを試行し、上限到達時は `FAILED_B7` となる。`escalate_node` は lint または test の上限到達時に敗因レポートの生成を試み、成功時は最終 status を `ESCALATED_NEEDS_REVISION` に更新する。

#### ラウンド上限の意味（Issue #91 で確定）

- `max_round`（既定 3）は、`lint_round`、`test_round`、`review_round` それぞれの**累積失敗回数**に対する上限である。フェーズを通過してもカウンタはリセットしない。
- 上限は「失敗 3 回目で `FAILED_B7`」を意味する（`round >= max_round` で停止。再試行は最大 2 回）。
- 各カウンタは `execute_issue` の開始ごとに 0 から数える。実行をまたぐ上限は、次の `consecutive_b7` が担う。
- 1 回の実行で `code_node` が走る最悪回数は、初回 1 + 各フェーズの再実行 (max_round - 1) × 3 + timeout 再試行 2 となる。`recursion_limit` はこれから算出する（`compute_recursion_limit`）。

#### 連続 FAILED_B7 回数（`consecutive_b7`）

`state.json` の Issue エントリに保持し、実行終了時の最終 status で次のとおり更新する。

| 最終 status                                                                               | `consecutive_b7`                         |
| :---------------------------------------------------------------------------------------- | :--------------------------------------- |
| `FAILED_B7`                                                                               | +1                                       |
| `COMPLETED`                                                                               | 0 に戻す                                 |
| `--fresh` で開始した実行                                                                  | 0 から数え直す（実行後の status で更新） |
| 上記以外（`FAILED_SYSTEM`、`PR_FAILED`、`ESCALATED_NEEDS_REVISION`、`SKIPPED_LOCKED` 等） | 変更しない                               |

`ESCALATED_NEEDS_REVISION` は自動 Resume の対象外（次回は Fresh）のため数えない。未設定のエントリは 0 として扱う。上限（`MAX_CONSECUTIVE_B7` = 2）に達した場合の挙動は §5.2 を参照する。

### 5.7 Node 契約

| Node                 | 成功時                                                                                                                                                                                    | 再試行・エスカレーション                                                                                                                                                                                          |
| :------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `spec_draft_node`    | planner 出力を `impl_plan` へ保存し、JEV 計画適合性ゲートで検証。適合（`passed`）なら `code_node` へ進行。                                                                                | YAGNI違反は制約フィードバックを付与し初回 `retry_spec_draft`、2回目は `FAILED_B7`。timeout は初回再試行、2回目は `FAILED_SYSTEM`。その他例外は `SYSTEM_ERROR`。                                                   |
| `code_node`          | agyによるコード編集後、edit_guardを適用し、Git状態から変更済みファイルを `target_files` に追加する。                                                                                      | timeout は初回 `retry_code`、2回目は `FAILED_SYSTEM`。その他のagyエラーは即時 `SYSTEM_ERROR`。外側契約は不変。                                                                                                    |
| `lint_node`          | 対象 Python がなければ `lint_passed`。Ruff の最終 check 成功で `lint_passed`。                                                                                                            | 失敗時は `LINT_ERROR` と `lint_round` を更新し、3回目で `FAILED_B7`。                                                                                                                                             |
| `run_pytest_node`    | pytest の JSON report を解析し、成功なら `test_passed`。                                                                                                                                  | 失敗時は `TEST_ERROR` と `test_round` を更新し、3回目で `FAILED_B7`。実行・解析例外は `SYSTEM_ERROR`。                                                                                                            |
| `test_feedback_node` | reasoning LLM の助言を `test_feedback_instruction` と `aider_message` に保存する。                                                                                                        | 助言作成失敗時も raw テスト出力を維持して `retry_code`。                                                                                                                                                          |
| `review_node`        | LLM 判定を実施し、`LGTM` の場合は JEV レビュー合否二次ゲート（`verify_review_conformance`）で検証。適合なら `review_lgtm` を確定して `done_node` へ進行。RDJSON・レビュー履歴を保存する。 | JEV 不適合時は `changes_requested` に上書きし `aider_message` を付与して `code_node` へ差し戻し。指摘は 3 回目で `FAILED_B7`（それ以前は `retry_code`）。timeout は初回 `retry_review`、2回目は `FAILED_SYSTEM`。 |
| `done_node`          | 対象ファイルを stage・commit・push し PR を作成、または既存 PR を検出して `COMPLETED`。                                                                                                   | Git/PR 操作失敗は `PR_FAILED` / `PR_ERROR`。                                                                                                                                                                      |
| `escalate_node`      | 最終状態を防御的に `FAILED_B7` または `FAILED_SYSTEM` とする。                                                                                                                            | lint/test の上限到達時は敗因レポート生成を試み、成功時は `ESCALATED_NEEDS_REVISION` とする。                                                                                                                      |

## 6. 外部ツール Adapter 契約

### 6.1 LLM Adapter & Backend Coordinator

LLMへのリクエスト構成、OpenAI互換APIエンドポイントの切り替え、およびGPUリソースのリース制御の詳細については、以下を参照すること。

👉 **[SBOS-DD-005_Backend_GPUリース仕様.md](SBOS-DD-005_Backend_GPUリース仕様.md)**

### 6.2 コード編集エンジン Adapter（agy）

agyの実行仕様、edit_guardによる対象外変更の後始末、外部送信と失敗契約の詳細については、以下を参照すること。

👉 **[SBOS-DD-004_Aider統合仕様.md](SBOS-DD-004_Aider統合仕様.md)**（本書は編集エンジン全般の仕様に拡張されたが、他文書からのリンク維持のためファイル名は当面変更しない）

### 6.3 品質・レビュー Adapter

Ruff (lint)、pytest (test)、LLM レビューおよび Reviewdog の詳細仕様とエスカレーション処理については、以下を参照すること。

👉 **[SBOS-DD-006_品質ゲート_レビュー仕様.md](SBOS-DD-006_品質ゲート_レビュー仕様.md)**

### 6.6 Git・PR Adapter

`done_node` は次の順序を守る。

1. 既存 staged 変更を拒否する。
2. `target_files` のみを `git add --` し、stage 後のファイル集合が対象外を含まないことを検証する。
3. 未コミット差分があれば commit する。
4. `git fetch origin` 後、`git push --force-with-lease -u origin <head>` を実行する。
5. `gh pr list --head <head> --json number` で既存 PR を確認し、なければ `gh pr create` を実行する。

いずれかの Git または GitHub CLI 操作が失敗した場合、ブランチ・差分を巻き戻さず `PR_FAILED` と `PR_ERROR` を設定する。PR 作成に使用する head は現在 `sbos/<ISSUE_ID>` に固定されるため、`work_branch_prefix` を変更する場合は §12 の制約を確認すること。

## 7. 永続化・監査・排他制御

`state.json` および `execution_history.json` の永続化契約（fsync + 原子置換）、ならびに `ProjectLockManager` による排他制御（ロック取得・競合時の挙動）の詳細については、以下を参照すること。

👉 **[SBOS-DD-007_永続化_排他制御仕様.md](SBOS-DD-007_永続化_排他制御仕様.md)**

## 8. CLI・運用 Interface

### 8.1 オーケストレーター CLI

```text
uv run python tools/orchestrator_graph.py orchestrate [--project-key <PROJECT_KEY>]
uv run python tools/orchestrator_graph.py execute --issue-id <ISSUE_ID> [--project-key <PROJECT_KEY>] [--resume] [--fresh]
```

| コマンド      | 契約                                                                                                                                                          |
| :------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `orchestrate` | 既存の `tools/.cache/priority-cache.json` から `issues`、互換形式として `tasks` を読み、score 降順の上位3件を表示する。キャッシュ生成・Issue 実行は行わない。 |
| `execute`     | Issue ID の prefix から project key を補完し、整合性検証後に `execute_issue()` を呼ぶ。                                                                       |
| legacy 入口   | サブコマンドなしでも `--issue-id` と `--project-key` が両方指定される場合だけ実行する。                                                                       |

### 8.2 run_task ラッパー

`run_task.py` は衛星のクリーンアップと `orchestrator_graph.py execute` の起動を担当する別 Interface である。`--dry-run` は実行予定だけを出力し、`--resume` はクリーンアップを省略する。既定では `git checkout -f <base>`、`git reset --hard origin/<base>`、`git clean -fd` を実行するため、未コミット変更・未追跡ファイルを破棄する。運用者は破壊的操作を理解した上でのみ利用すること。

## 9. セキュリティ・安全性の不変条件と制約

| 項目               | 実装上の保証・制約位置づけ                                                                                                      |
| :----------------- | :------------------------------------------------------------------------------------------------------------------------------ |
| 母艦誤編集の防止   | 無効な台帳・衛星ディレクトリ・対象ファイルでは Graph を開始しない。                                                             |
| 並行実行           | 同一 project key は `run_task.py` を含め `ProjectLockManager`（`.lock`）により排他する。                                        |
| LLM の実行先       | intent は route を経由し、未定義 intent は拒否する。                                                                            |
| コード編集         | agyが衛星ワークツリーを編集し、edit_guardが境界外変更を戻す。**サテライトの内容が外部送信される。**                             | 衛星ワークツリー、外部サービス |
| `call_llm()` / agy | 空の一時ディレクトリでagyを起動し、サニタイズ済みpromptを送信する。                                                             | 一時ディレクトリ、外部サービス |
| Stage 前検証       | 既存 staged 変更を拒否し、`target_files` に含まれない stage 変更を拒否する（※Aider 後に追加された変更済み Python も検証対象）。 |
| レビューの差分     | Git diff が取得できない場合は review を失敗させる。                                                                             |
| Reviewdog          | 補助的な表示であり、失敗しても品質判定は継続する。                                                                              |
| 状態保存           | state と履歴は個別ロック・一時ファイル置換で保護する。                                                                          |

### 9.1 副作用一覧

システム全体における全コンポーネントの副作用を以下の表に集約する。

| 実行箇所            | 副作用                                                                                                                                     | 影響範囲                       |
| :------------------ | :----------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------- |
| `run_task.py`       | ロック取得後、checkout, hard reset, clean で変更・未追跡ファイルを破棄する。                                                               | 衛星ワークツリー               |
| `get_git_diff()`    | `git add -N .` を実行して未追跡ファイルを差分対象へ登録する。                                                                              | 衛星 Git index                 |
| `code_node()` / agy | agyが作業ツリーを直接編集し、edit_guardで対象外変更を戻す。agyの成果物が残る場合は試験書へ記録する。**サテライトの内容が外部送信される。** | 衛星ワークツリー、外部サービス |
| `call_llm()` / agy  | 空の一時ディレクトリでagyを起動し、終了後に削除する。サニタイズ済みpromptが外部送信される。                                                | 一時ディレクトリ、外部サービス |
| `lint_node()`       | Ruff format と `--unsafe-fixes` で対象 Python ファイルを修正する。                                                                         | 衛星ワークツリー               |
| `run_pytest_node()` | `.report.json` を一時作成し、終了時に削除する。                                                                                            | 衛星ワークツリー               |
| `escalate_node()`   | lint/test の上限到達時に `FAILURE_REPORT_<ISSUE_ID>.md` を作成する。                                                                       | 衛星ワークツリー               |
| `done_node()`       | `target_files` を stage・commit・`push --force-with-lease` し、PR を作成する。                                                             | 衛星 Git／リモート             |

副作用を伴う Module の変更時は、対象、失敗時の保持・復元方針、関連テストをこの表と §12 に反映する。

## 10. 現行仕様の制約・既知の実装差異・課題整理

### 10.1 現行仕様の制約

以下は現行実装の動作として受け入れる制約である。

1. **自動backend fallbackはない。** routeに指定されたagy profileだけを実行し、agyの失敗は安全停止する。Aiderへ戻す場合はlegacy/archiveから資産を復元する。
8. **agy経路では `temperature` / `max_tokens` を指定しない。** agy側設定へ委譲する。
9. **agy経路の認証・クォータ障害を分類する。** `AGY_AUTH` / `AGY_QUOTA` として記録し、nightly workerは連続失敗で停止する。
10. **JEVはOllamaに依存する。** agy移行後もJEVを有効にするにはOllamaと既定モデルの配備が必要である。

### 10.2 既知の実装不整合と改修状況

1. **`run_task.py` のロック非取得クリーンアップ【Rev.6.0 で改修済み】**
   - 以前はロック取得前に cleanup を実行していたが、`ProjectLockManager` 内で cleanup および orchestrator 呼び出しを行うよう修正。
2. **作業ブランチ prefix の不一致【Rev.6.0 で改修済み】**
   - PR 作成時（`done_node`）に `sbos/<ISSUE_ID>` がハードコードされていたが、`GraphState` で `work_branch_prefix` を保持し動的適用するよう修正。
3. **`GraphState` の `test_feedback_instruction` の初期値**
   - 型定義上必須だが初期 state では未設定である。各 node は `.get()` を使用するため実行時には支障ない。
4. **`status` の Enum / Literal 化および Metadata モジュールの独立分離【Rev.6.1 で改修済み (Issue #22)】**
   - `tools/metadata_store.py` を新設し、`TaskStatus` / `ErrorCategory` Enum & Literal を導入して型安全性を担保。
   - プロジェクト台帳、タスク状態（`state.json`）、実行履歴（`execution_history.json`）、排他ロック管理（`ProjectLockManager`）を独立分離。
5. **機密情報マスキング・サニタイズ共通モジュール `tools/sanitizer.py` の導入【Rev.6.2 で改修済み (Issue #20)】**
   - `tools/sanitizer.py`（`sanitize_text`, `sanitize_data`）を新設。
   - APIキー、アクセストークン、秘密鍵、Basic認証URL、Key-Valueシークレット、メールアドレス（RFC 2606テストドメイン除外）等のマスキング基盤を確立。
   - `tools/llm_client.py`（プロンプト送信直前）、`tools/metadata_store.py`（履歴・イベント保存直前）、`orchestrator_graph.py`（Failure Report出力時）の全境界へ統合完了。

### 10.3 未確認事項（実機環境が必要）

- agy CLIの導入、認証、ネットワーク接続
- 実モデルのJSON遵守率、編集品質、入力長上限
- 実サテライトでのL3〜L5運用試験
- 本番project keyの `agy_external_send` allowlist登録

### 10.4 将来のリファクタリング候補

### 10.4 将来のリファクタリング候補

- **`run_task.py` と CLI の責務整理**: 破壊的クリーンアップ機能と通常実行の連携のさらなる整理。

## 11. テスト・検証設計

| テスト                                                                         | 対応する Interface・契約                                                                                                                           |
| :----------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_orchestrator_agy_integration.py`                                   | Issue/プロジェクト検証、文脈解決、timeout、状態遷移、Ruff・pytest、レビュー/RDJSON/Reviewdog、PR branch prefix、履歴、CLI、resume を統合検証する。 |
| `tests/test_agy_runner.py`                                                     | Git diff、初回 commit 前 fallback、Aider 引数・timeout・非ゼロ終了、一時ファイル削除、`/v1` 除去を検証する。                                       |
| `tests/test_backend_coordinator.py`                                            | intent route、Ollama/llama-server Adapter、GPU リース、未定義 intent、Ollama 到達不能時の llama-server 起動を検証する。                            |
| `tests/test_llm_client.py`                                                     | role 設定、OpenAI SDK へのパラメータ伝達、intent 補完を検証する。                                                                                  |
| `tests/test_run_task.py`                                                       | ロック保護下でのクリーンアップ順、resume 時の skip、dry-run の非実行性を検証する。                                                                 |
| `tests/test_agy_client.py`                                                     | agy実行ファイル解決、timeout、プロセスツリー終了、非0終了・未導入例外を検証する。                                                                  |
| `tests/test_agy_runner.py`                                                     | `run_agy_edit` の成功・timeout・非0終了、edit_guard呼び出しを検証する。                                                                            |
| `tests/test_llm_client.py`（agy経路）                                          | 通常テキスト・JSON・抽出失敗フォールバック・sanitize適用を検証する。                                                                               |
| `tests/test_config_loader.py` / `tests/test_backend_coordinator.py`（agy経路） | agy profile検証と、agy実行時にGPUリースを取得しないことを検証する。                                                                                |

### 11.1 保証範囲

| 検証層            | 現在の保証（モックベース検証）                                                                          | 未保証・実環境接続が必要な検証（smoke test）                                                                                                                               |
| :---------------- | :------------------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit / 契約テスト | 設定解決、agy引数・例外、Backend route、LLMパラメータ、run_taskのロック・分岐をモックで検証する。       | 実行ファイルのインストールや外部サービスの可用性。                                                                                                                         |
| 統合テスト        | LangGraph の状態遷移、監査保存、Git/PR の失敗正規化、レビュー結果の構造化を隔離環境とモックで検証する。 | 実 Git remote、実 GitHub PR、実 LLM (Ollama/llama-server) の応答品質。                                                                                                     |
| 実環境 smoke test | 自動テストスイートには含まれない（分離運用）。                                                          | JEV用Ollama、Ruff、pytest、Reviewdog、GitHub CLI、リモートGit、agyを実接続した最小Issueの完走検証。agy実機テストは `integration` マーカーで分離し、CIはagyに依存させない。 |

実環境 smoke test は、衛星リポジトリを破壊しない専用の一時 repository と Issue を用意して別の運用手順として実施する。

```bash
uv run pytest
uv run ruff check tools tests
```

## 12. 変更時の設計判断

- 新しい LLM 用途を追加する場合は、role・intent・route・profile・テストを同時に追加する。暗黙の model 選択を導入しない。
- agy経路を呼び出し側（各ノード）に `if agy:` として散らさない。分岐はBackend Adapter、`call_llm`内部、`code_node`に限る。
- agyへ送るデータの範囲を広げる変更は、外部送信ポリシーへの影響を §9 に反映する。
- JEVには触れない。JEVをagyへ移す変更は別設計とする。
- 新しい終端状態を追加する場合は、Graph の route、`state.json`、実行履歴、運用手順、統合テストを同時に更新する。
- Git 操作を追加する場合は、衛星 `cwd`、対象ファイル制限、失敗時の差分保持、破壊的操作の有無をこの文書に記載する。
- 新しい外部ツールは、Module の Interface、例外変換、timeout、テスト用 seam を定義してから Graph node へ接続する。
- 本書にコード全文を複製しない。関数シグネチャ、状態遷移、永続化形式、外部コマンド契約の変更を伴う実装変更だけを追記・更新する。

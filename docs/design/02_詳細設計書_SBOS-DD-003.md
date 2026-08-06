# 詳細設計書（コンポーネント詳細・データフロー・実装仕様）
**LangGraph / OpenAI互換API / Aider / Ruff / Reviewdog 統合実装仕様**

| 項目     | 内容                                                                                                    |
| :------- | :------------------------------------------------------------------------------------------------------ |
| 文書番号 | SBOS-DD-003                                                                                             |
| 版数     | Rev.4.12（現行コードベース整合版）                                                                      |
| 改訂日   | 2026年8月6日                                                                                            |
| 作成日   | 2026年7月28日                                                                                           |
| 実装正本 | `tools/orchestrator_graph.py`、`tools/llm_client.py`、`tools/aider_runner.py`、`tools/config_loader.py` |
| 関連文書 | SBOS-BD-002、SBOS-MULTI-001、SBOS-OP-001、SBOS-ENV-001、SBOS-PM-005                                     |

---

## 1. 依存パッケージおよび環境構築

依存関係は `pyproject.toml` を正本とし、`uv sync --extra dev` で開発環境を構築する。実行時は LangGraph、OpenAI SDK、Aider、Pydantic、filelock、pytest-json-report を使用する。`litellm` は依存関係に残るが、現行の `llm_client.py` は利用しない。

## 2. 状態管理とエラー契約

`tools/orchestrator_graph.py` の `GraphState` がグラフ実行時の正本である。識別・実行情報は `issue_id`、`project_key`、`execution_id`、`generation`、`cwd`、`base_branch`、`target_files`、`instruction` で保持する。処理結果は `status`、`error`、`error_category`、`impl_plan`、`aider_message`、`lint_result`、`test_result`、`review_verdict`、`review_comments`、`review_rounds`、`rdjson`、`reviewdog_result`、`history_summary` で保持する。リトライ制御には `lint_round`、`test_round`、`review_round`、`max_round`、`llm_timeout_count` を用いる。

| 検知箇所               | エラー分類        | 実装上の処理                                                                                                               |
| :--------------------- | :---------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `lint_node`            | `LINT_ERROR`      | Ruff の失敗時に `lint_round` を加算し、上限未満なら `retry_code`、上限到達時は `FAILED_B7`。                               |
| `run_pytest_node`      | `TEST_ERROR`      | pytest の失敗時に `test_round` を加算し、上限未満なら `test_feedback_node` を経て `retry_code`、上限到達時は `FAILED_B7`。 |
| `review_node`          | `REVIEW_REJECTED` | レビューごとに `review_round` を加算し、上限未満なら `retry_code`、上限到達時は `FAILED_B7`。                              |
| LLM/Aider タイムアウト | `LLM_TIMEOUT`     | 初回は該当ノードを再試行し、`llm_timeout_count >= 2` で `FAILED_SYSTEM`。                                                  |
| その他の例外           | `SYSTEM_ERROR`    | 再試行せず `FAILED_SYSTEM`。                                                                                               |
| PR 作成失敗            | `PR_ERROR`        | 作業ブランチと差分を保持したまま `PR_FAILED`。                                                                             |

## 3. コンポーネント設計

| モジュール               | 実装契約                                                                                                                                                                                                                                                                     |
| :----------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llm_client.py`          | `BackendExecutionCoordinator` が intent からプロファイルを選択し、環境変数で設定された OpenAI 互換エンドポイントへ `openai.OpenAI` で接続する。モデル名はプロファイル、temperature と max_tokens は `models` の role 設定から取得する。                                      |
| `config_loader.py`       | `config/models.json` を Pydantic で strict に検証する。必須構造は `models`、`aider`、`backend_execution` であり、後者で `routes` と `profiles` を定義する。                                                                                                                  |
| `aider_runner.py`        | `aider_edit` または `code_edit` のプロファイルからモデルを解決し、`--no-auto-commits`、`--yes-always`、`--message-file` を指定して実行する。UUID 付き一時指示ファイルは必ず削除する。非ゼロ終了・タイムアウトは `AiderRunError`、Git diff 取得失敗は `GitDiffError` とする。 |
| `backend_coordinator.py` | `backend_execution` の route/profile に従い Ollama または llama-server を選択し、GPU リースで排他実行する。                                                                                                                                                                  |

## 4. LangGraph 実行フロー

`execute_issue()` は Issue ID と project key を検証し、衛星リポジトリの文脈を解決してからグラフを実行する。主要ノードは `spec_draft_node`、`code_node`、`lint_node`、`run_pytest_node`、`test_feedback_node`、`review_node`、`done_node`、`escalate_node` である。`spec_draft_node` が実装計画を作成し、`code_node` が Aider を実行する。lint・test・review の失敗はフィードバックを `aider_message` に保存して修正ループへ戻す。Reviewdog の実行失敗はレビュー本体を停止させない。`done_node` は対象ファイルのみを stage/commit/push し PR を作成する。終了時は `metadata/projects/<PROJECT_KEY>/state.json` と実行履歴へ結果を保存し、ロックを解放する。

## 5. CLI 仕様

```text
uv run python tools/orchestrator_graph.py orchestrate [--project-key <PROJECT_KEY>]
uv run python tools/orchestrator_graph.py execute --issue-id <ISSUE_ID> [--project-key <PROJECT_KEY>] [--resume] [--fresh]
```

`orchestrate` は既存の `tools/.cache/priority-cache.json` を読み、未完了 Issue の上位3件を表示する。キャッシュ生成機能はこのモジュールには含まれない。`execute` は project key を Issue ID のプレフィックスから補完できる。`--resume` は既存の作業ブランチを継続し、`--fresh` は既存の作業ブランチを削除して base branch から再作成する。

## 6. テスト・検証設計

| テスト                                         | 検証対象                                                                                       |
| :--------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| `tests/test_orchestrator_aider_integration.py` | Issue ID・プロジェクト整合性・文脈解決・状態遷移・タイムアウト再試行・PR失敗・Reviewdog・CLI。 |
| `tests/test_aider_runner.py`                   | Git diff、Aider 起動引数、モデル／タイムアウト指定、例外変換。                                 |
| `tests/test_llm_client.py`                     | role パラメータ、intent の補完、OpenAI SDK 呼び出し。                                          |
| `tests/test_backend_coordinator.py`            | Ollama／llama-server のルーティング、GPU リース、未定義 intent。                               |
| `tests/test_run_task.py`                       | 衛星リポジトリの初期化、`--resume`、`--dry-run`。                                              |

```bash
uv run pytest
uv run ruff check tools tests
```
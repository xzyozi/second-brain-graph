# 詳細設計書（Backend LLM 制御・GPU リース仕様）

| 項目               | 内容                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 文書名             | Second Brain OS - Backend LLM 制御・GPU リース仕様                                                                      |
| 版数               | Rev.1.0                                                                                                                 |
| 改訂日             | 2026年8月8日                                                                                                            |
| 関連文書           | SBOS-BD-002（基本設計書）、SBOS-DD-003（オーケストレーター統合設計）                                                    |
| 対象コンポーネント | `tools/backend_coordinator.py`、`tools/llama_backend.py`、`tools/config_loader.py`、`tools/llm_client.py`               |
| 役割               | LLM プロファイルの検証、Ollama と llama-server の排他制御、GPU リソースのリース管理、OpenAI 互換 API へのリクエスト構成 |

---

## 1. 概要と基本方針

本仕様は、オーケストレーターが多様な LLM バックエンド（Ollama、llama-server 等）を利用する際の、設定の検証（Pydantic）、Intent によるルーティング解決、およびローカル GPU リソースの排他リース制御について定義する。

## 2. 設定モデルとスキーマ (`config/models.json`)

`config/models.json` は LLM 関連設定の SSOT である。`RootConfig` は `extra='forbid'` の Pydantic 検証を行うため、未知のキーを許可しない。

| 設定ブロック        | 主な項目                                                      | 契約                                                                    |
| :------------------ | :------------------------------------------------------------ | :---------------------------------------------------------------------- |
| `models.<role>`     | `temperature`、`max_tokens`                                   | `planner`、`coder`、`reviewer` の生成パラメータ。モデル名は保持しない。 |
| `backend_execution` | `mode`、`fallback`、`gpu_lease_timeout`、`routes`、`profiles` | backend の排他実行と intent ルーティング。                              |
| `profiles.<name>`   | `backend`、`model`、`openai_endpoint`                         | `ollama` は管理 endpoint、`llama_server` は port と model_path も必須。 |

※ `load_model_config()` と `get_coordinator()` は `lru_cache` によりプロセス内でキャッシュされるため、設定変更を反映する場合は新しい Python プロセスで実行すること。

## 3. Intent Route とルーティング

各タスクの目的に応じた `intent` が、どの設定プロファイルに割り当てられるかを定義する。

| intent                                                    | 現行 profile       | role               |
| :-------------------------------------------------------- | :----------------- | :----------------- |
| `spec_draft`、`task_decomposition`、`task_prioritization` | `reasoning_ollama` | planner            |
| `code_edit`、`aider_edit`                                 | `coding_ollama`    | coder / Aider      |
| `code_review`、`failure_analysis`、`test_feedback`        | `reasoning_ollama` | reviewer / planner |

* **自動 fallback はない**: `fallback` 設定は検証されるだけで、Coordinator は route に指定された profile だけを実行する。

## 4. LLM Adapter (`llm_client.py`)

`call_llm(role, system_prompt, user_prompt, expect_json=False, timeout=300, intent='', **kwargs)` は次の手順で動作する。

1. intent が未指定の場合、`planner`、`coder`、`reviewer` をそれぞれ `spec_draft`、`code_edit`、`code_review` に補完する。補完不能な role は `ValueError` とする。
2. `BackendExecutionCoordinator` から intent に対応する profile を取得する。
3. profile の model、role 設定の temperature・max_tokens、呼び出し時の上書き値で OpenAI SDK のリクエストを構成する。
4. Coordinator が一時設定した `OPENAI_API_BASE`、なければ `OLLAMA_API_BASE` を `OpenAI(base_url=..., api_key='local')` に渡す。
5. 通常応答は `{"raw": <text>}` を返し、`expect_json=True` は JSON object を解析して返す。JSON object にできない応答は `changes_requested` の安全側フォールバックとして扱う。

## 5. Backend Coordinator と GPU リース管理

`BackendExecutionCoordinator.execute(intent, {"action": callable})` は route を profile に解決し、`GpuLeaseAdapter` のコンテキスト内で該当 Adapter を実行する。未定義 intent、未定義 profile、`action` の欠落は例外とする。

### 5.1 GPU リース機構
* GPU リースは `metadata/.gpu_lease.lock` を利用し、待機時間は `gpu_lease_timeout` を使用する。
* **排他性**: `mode` は `exclusive` のみを許容し、複数 backend の同時 GPU 利用は行わない。

### 5.2 各 Backend Adapter の挙動
* **Ollama Adapter**: action 実行中のみ OpenAI 互換 endpoint と Ollama 管理 endpoint を環境変数へ設定し、終了後に復元する。
* **llama-server Adapter**: Ollama profile がある場合はロード済みモデルの解放を試み、`managed_llama_server()` 内で action を実行する。Ollama 管理 API が到達不能な場合は VRAM が空いているものとして起動を継続する。

# 詳細設計書（Backend LLM 制御・GPU リース仕様）

| 項目               | 内容                                                                                                                               |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号           | SBOS-DD-005                                                                                                                        |
| 文書名             | Second Brain OS - Backend LLM 制御・GPU リース仕様                                                                                 |
| 版数               | Rev.2.1（agy外部送信ポリシーとproject key allowlistを追記）                                                                        |
| 改訂日             | 2026年11月4日                                                                                                                      |
| 関連文書           | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、SBOS-DD-004（コード編集エンジン統合）、Issue #39、Epic #116                  |
| 対象コンポーネント | `tools/backend_coordinator.py`、`tools/llama_backend.py`、`tools/gguf_manager.py`、`tools/config_loader.py`、`tools/llm_client.py` |
| 役割               | LLMプロファイル検証、agy backendの実行、JEV用Ollamaの据え置き、GPUリース管理、外部送信ポリシーの適用                               |

> **現行構成**: JEVを除くLLM処理はagy backendへルーティングする。JEV（`tools/jev_adapter.py`、`submodules/jev-localsystem`、`tools/screen_issues.py`）だけは本書のroutes/profilesを経由せず、Ollama（既定モデル `qwen2.5:0.5b`）へ直接接続する。Aiderとllama-serverはruntimeから退役し、旧資産はlegacy/archiveに保存する。

---

## 1. 概要と基本方針

本仕様は、オーケストレーターが多様な LLM バックエンド（Ollama、llama-server 等）を利用する際の、設定の検証（Pydantic）、Intent によるルーティング解決、およびローカル GPU リソースの排他リース制御について定義する。

Epic #116のagy移行は実装済みである。`intent → routes → profile → agy backend adapter` の流れを使い、呼び出し側（`call_llm`の4箇所、`code_node`）のシグネチャと返り値を維持する。

### 1.1 本書の対象外（据え置き）

**JEV（`tools/jev_adapter.py`、`submodules/jev-localsystem`、`tools/screen_issues.py`）は本書の `routes` / `profiles` を経由せず、Ollama（既定モデル `qwen2.5:0.5b`、環境変数 `JEV_MODEL` で上書き）へ直接接続する。** JEV は Zero-Decode（logprobs）を使うため agy へ置き換えられず、Epic #116 でも据え置きとする。したがって、**agy へ移行した後も Ollama の実行環境は運用上必要**である。JEV は利用できない場合に判定をバイパスする（フェイルオープン、DD-006 §1.1・§3.1.1）。

## 2. 設定モデルとスキーマ (`config/models.yaml`)

`config/models.yaml` は LLM 関連設定の SSOT である。`tools/config_loader.py` の `load_model_config()` は `models.yaml` **のみ**を読み込む。ファイルが存在しない場合は `FileNotFoundError` となり、`models.json` へのフォールバックは行わない。YAML 形式の採用により、各設定パラメータの選定理由や VRAM 推奨マージンをコメントとして直接記述できる。

> **訂正（Rev.2.0）**: Rev.1.1 は「後方互換用フォールバックとして `models.json`」と記載していたが、実装には存在しない。`config/models.json` は旧版のコピーであり、loader は読まない。扱いは Issue #128 で決める。

`ModelConfig`（旧 `RootConfig`）は `extra='forbid'` の Pydantic 検証を行うため、未知のキーを許可しない。

| 設定ブロック        | 主な項目                                                      | 契約                                                                    |
| :------------------ | :------------------------------------------------------------ | :---------------------------------------------------------------------- |
| `models.<role>`     | `temperature`、`max_tokens`                                   | `planner`、`coder`、`reviewer` の生成パラメータ。モデル名は保持しない。 |
| `aider`             | `edit_format`、`timeout` ほか                                 | 【現行】Aider 実行の設定（DD-004）。                                    |
| `backend_execution` | `mode`、`fallback`、`gpu_lease_timeout`、`routes`、`profiles` | backend の排他実行と intent ルーティング。                              |
| `profiles.<name>`   | `backend`、`model`、`openai_endpoint` ほか                    | 下表のとおり backend ごとに必須項目が異なる。                           |

### 2.1 profile の必須項目

| backend        | 必須項目                                                 | 状態     |
| :------------- | :------------------------------------------------------- | :------- |
| `ollama`       | `model`、`openai_endpoint`、`ollama_management_endpoint` | 【現行】 |
| `llama_server` | `model`、`openai_endpoint`、`port`、`model_path`         | 【現行】 |
| `agy`          | `model`（識別ラベル）。`timeout`（任意、秒）             | 現行     |

### 2.1 agy profileの現行契約

* `backend` の取りうる値に `"agy"` を追加する。
* `openai_endpoint` は必須から**任意**へ変更する。`ollama` / `llama_server` では従来どおり必須（`^https?://`）とし、`agy` では**指定されたらエラー**にする。`port`・`model_path`・`ollama_management_endpoint` も `agy` では指定不可とする。
* `model` は agy のモデル指定オプションの有無（Issue #117 で確認）に応じて、実モデル名または識別ラベル（例 `agy-default`）とする。
* `timeout`（秒、1 以上）を任意項目として追加する。コード編集の実行（DD-004 §3.3）で使い、未設定時は 1200 秒とする。
* `openai_endpoint` が任意になることで、これを文字列として参照する既存コード（`OllamaBackendAdapter`、`LlamaServerBackendAdapter`）には、未設定時に例外とする型の絞り込みが必要になる。

```yaml
backend_execution:
  profiles:
    agy_default:
      backend: "agy"
      model: "agy-default"   # 識別ラベル。#117 の結果で確定
      timeout: 1200
```

※ `load_model_config()` と `get_coordinator()` は `lru_cache` によりプロセス内でキャッシュされるため、設定変更を反映する場合は新しい Python プロセスで実行すること。

## 3. Intent Route とルーティング

各タスクの目的に応じた `intent` が、どの設定プロファイルに割り当てられるかを定義する。

| intent                                                    | 現行 profile                                                                     | role               |
| :-------------------------------------------------------- | :------------------------------------------------------------------------------- | :----------------- |
| `spec_draft`、`task_decomposition`、`task_prioritization` | `agy_default`                                                                    | planner            |
| `aider_edit` 互換intent                                   | `code_edit` と同じく `agy_default` へ解決する。Aider runtimeの選択を意味しない。 |
| `code_review`、`failure_analysis`、`test_feedback`        | `agy_default`                                                                    | reviewer / planner |

* **自動fallbackはない**: routeに指定されたagy profileだけを実行する。Aiderへ戻す場合はlegacy/archiveから資産を復元する。
* **ロールバック方針**: 現行routeを旧profileへ変更するだけではAider runtimeへ戻らない。Aiderへ戻す場合は `legacy/local_llm/` または archive tag から必要資産を復元し、別環境で比較検証する。
* `task_decomposition` と `task_prioritization` は `routes` に定義されているが、現行の `tools/` 配下にこの intent の呼び出し元は見つかっていない。

## 4. LLM Adapter (`llm_client.py`)

`call_llm(role, system_prompt, user_prompt, expect_json=False, timeout=600, intent='', **kwargs)` は次の手順で動作する。

1. intent が未指定の場合、`planner`、`coder`、`reviewer` をそれぞれ `spec_draft`、`code_edit`、`code_review` に補完する。補完不能な role は `ValueError` とする。
2. `BackendExecutionCoordinator` から intent に対応する profile を取得する。
3. profile の model、role 設定の temperature・max_tokens、呼び出し時の上書き値で OpenAI SDK のリクエストを構成する。
4. Coordinator が一時設定した `OPENAI_API_BASE`、なければ `OLLAMA_API_BASE` を `OpenAI(base_url=..., api_key='local')` に渡す。
5. 通常応答は `{"raw": <text>}` を返し、`expect_json=True` は JSON object を解析して返す。JSON object にできない応答は `changes_requested` の安全側フォールバックとして扱う。
6. system / user プロンプトは、送信直前に `sanitize_text` で機密情報をマスクする（Issue #20）。

> **訂正（Rev.2.0）**: Rev.1.1 は `timeout=300` と記載していたが、実装の既定値は 600 秒である。

### 4.1 agy経路（現行）

`profile.backend == "agy"` のとき、`call_llm` の内部処理（`_do_llm_call`）は OpenAI 経路ではなく agy を**テキスト応答器**として呼ぶ。シグネチャと返り値の形（`{"raw": ...}` または解析済み JSON object）は変えない。

| 項目                         | 契約                                                                                                                                |
| :--------------------------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| 呼び出し元                   | 変更しない（`spec_draft_node` / `test_feedback_node` / `review_node` / `escalate_node` の4箇所）                                    |
| プロンプト                   | `sanitize_text` でマスクした後に `[SYSTEM]` / `[USER]` の2ブロックへ連結する。`sanitize_text` による保護は維持する                  |
| JSON 指示                    | `expect_json=True` のときのみ、「JSON オブジェクト1つだけを出力し、コードフェンスや説明文を付けない」を末尾に追加する               |
| 起動                         | `agy_client.run_agy_text(prompt, timeout=timeout)`。**cwd は空の一時ディレクトリ**とし、リポジトリを読ませず、書かせない            |
| 後段処理                     | 得られた stdout を `raw_output` として、JSON 解析とフォールバックの既存処理へ渡す（OpenAI 経路と共有する関数に切り出す）            |
| `temperature` / `max_tokens` | agy 経路では**使わない**（指定手段が見つかれば #117 の結果で追加）。`get_model_params(role)` の取得・検証は OpenAI 経路のみ         |
| `OPENAI_API_BASE` の確認     | OpenAI 経路のみ。agy 経路ではこの環境変数を設定しないため、確認しない                                                               |
| 失敗                         | `AgyError` 系は握りつぶさず送出する。タイムアウトのメッセージには `timed out` を含める（呼び出し元が `LLM_TIMEOUT` を判定するため） |

呼び出し元ごとの失敗時の挙動（既存。変更しない）:

| 呼び出し元           | intent                              | 失敗時                                                                                                                                   |
| :------------------- | :---------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------- |
| `spec_draft_node`    | `spec_draft`                        | 例外文字列に `timeout` / `timed out` を含めば `LLM_TIMEOUT`（1回目は `retry_spec_draft`、2回目は `FAILED_SYSTEM`）。他は `FAILED_SYSTEM` |
| `test_feedback_node` | `test_feedback`                     | 例外は握りつぶし、生のテスト出力を維持して `retry_code`                                                                                  |
| `review_node`        | `code_review`（`expect_json=True`） | 構造不正は `FAILED_SYSTEM`                                                                                                               |
| `escalate_node`      | `failure_analysis`                  | 例外は握りつぶし、警告ログのみ（`status` は変えない）                                                                                    |

`review_node` は `verdict` が `LGTM` / `changes_requested` 以外だと `FAILED_SYSTEM` にする。agy が JSON の指示を守らない場合、既存の JSON 抽出フォールバックは `changes_requested` を返すため、**差し戻しが繰り返される**。JSON 遵守率の確認は Issue #127 で行う。

## 5. Backend Coordinator と GPU リース管理

`BackendExecutionCoordinator.execute(intent, {"action": callable})` は route を profile に解決し、`GpuLeaseAdapter` のコンテキスト内で該当 Adapter を実行する。未定義 intent、未定義 profile、`action` の欠落は例外とする。

### 5.1 GPUリース機構（現行）
* GPU リースは `metadata/.gpu_lease.lock` を利用し、待機時間は `gpu_lease_timeout` を使用する。取得できない場合は `TimeoutError` を送出する。
* **排他性**: `mode` は `exclusive` のみを許容し、複数 backend の同時 GPU 利用は行わない。
* 現行の実装では、**全 backend の実行が `with self.gpu_lease:` で包まれる**。

agyはGPUを使わないため、`backend == "agy"` のときはGPUリースを取得せずに実行する。これにより、agyの実行がOllama側の実行（JEVを含む）を待たせず、また待たされない。

### 5.2 各 Backend Adapter の挙動
* **Ollama Adapter【現行】**: action 実行中のみ OpenAI 互換 endpoint と Ollama 管理 endpoint を環境変数へ設定し、終了後に復元する。実行前に、ロード済みの別モデルを Ollama から解放する。
* **llama-server Adapter【現行】**: Ollama profile がある場合はロード済みモデルの解放を試み、`managed_llama_server()` 内で action を実行する。**Ollama 管理 API に到達できない場合は VRAM の状態が不明のため、環境変数 `SBOS_ALLOW_LLAMA_ON_UNKNOWN_VRAM` が `1` / `true` / `yes` でない限り、llama-server の起動を拒否して `RuntimeError` とする**（Issue #25）。許可されている場合のみ、警告を出して起動を続行する。
* **agy Adapter（現行）**: 環境変数のパッチを行わず、`request["action"]`を`action(profile)`として呼ぶだけの薄いAdapterとする。agyの起動処理は`agy_client`が持ち、Adapterは持たない。

> **訂正（Rev.2.0）**: Rev.1.1 は llama-server Adapter について「Ollama API 到達不能時は VRAM 解放済みと判定して処理を継続する」と記載していたが、実装は逆で、既定で起動を拒否する（Issue #25）。

## 6. GGUFモデル管理仕様 (`tools/gguf_manager.py`)【現行】

`llama-server` 起動時に読み込む GGUF フォーマットのモデルファイル（`*.gguf`）の配置・パス解決および存在検証を管理する。agy への移行後も、旧 profile を残す段階では有効である。旧 profile と llama-server 基盤の削除は Issue #128 で扱う。

### 6.1 配置ディレクトリ規約
* **正本配置パス**: プロジェクトルート直下の `./models/` (`get_models_dir()`) を標準配置場所とする。`models/*` は `.gitignore` により git 管理対象外である。
* **自動ディレクトリルート判定**: `ensure_models_dir()` により `models/` ディレクトリが存在しない場合は自動生成する。

### 6.2 パス解決と存在検証
* **パス解決 (`resolve_gguf_path`)**: 設定内の `model_path` または `draft_model_path` の相対パス・絶対パスをプロジェクトルート基準で一元的に解決する。
* **存在検証 (`validate_gguf_exists`)**: `managed_llama_server()` のプロセス起動前にモデルファイルおよびドラフトモデルファイルの存在を判定する。存在しない場合は `GgufFileNotFoundError` を送出し、モデルファイルの配置手順を案内するログを出力して安全に早期失敗させる。

## 7. 移行状況と未確定事項

| 項目                                                                    | 状況                                                                                                                                            | 確定先 / 実績   |
| :---------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------- | :-------------- |
| `ProfileConfig` の `agy` 対応、`AgyBackendAdapter`、GPU リース対象外    | **実装完了** (`tools/backend_coordinator.py`)                                                                                                   | PR #135 (#120)  |
| `call_llm` の agy 経路                                                  | **実装完了** (`tools/llm_client.py`)                                                                                                            | PR #135 (#121)  |
| `routes` の agy への切り替え                                            | **実装完了** (`config/models.yaml`)                                                                                                             | PR #137 (#123)  |
| agy の認証・クォータ障害分類と夜間バッチ安全中断ガード                  | **実装完了** (`tools/agy_client.py` 等)                                                                                                         | PR #139 (#126)  |
| agy のモデル指定オプション、`temperature` / `max_tokens` 相当の指定手段 | agy 側の設定に委譲（CLI側パラメータ指定なし）                                                                                                   | ADR 0001 (#117) |
| 外部送信の方針（agy 経路は `sanitize_text` の対象外の情報も送りうる）   | `backend_execution.agy_external_send` で認可。既定は移行互換の `allow_all`、実業務運用前に `allowlist` へ切り替える。秘密ファイル拒否も設定可能 | #124            |
| 旧 profile・llama-server 基盤・`openai` 依存の退役と後始末              | 未実施（JEV のため Ollama 環境は残る）                                                                                                          | #128            |

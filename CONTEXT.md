# CONTEXT.md - 用語集 ＆ ドメインコンテキスト定義

本ドキュメントは、Second Brain Graph (SBOS) プロジェクト全体で使用される用語、概念、およびコンテキストの SSOT（Single Source of Truth）です。

---

## 1. コア用語集 (Glossary)

### agy
- **定義**: Google Antigravity CLI の実行可能バイナリ (`agy` / `agy.exe`)、またはその CLI プロセスインターフェース。
- **役割**:
  1. **テキスト応答器**: `spec_draft`, `test_feedback`, `code_review`, `failure_analysis` などの推論インテントにおいて、空の一時ディレクトリを cwd として副作用なく高速にプロンプト応答・JSON応答を生成する (`tools/agy_client.py:run_agy_text`)。
  2. **コード編集器**: `code_node` (`code_edit` / `aider_edit`) において、サテライトの作業ツリーに入り非対話的かつ自律的にコード編集・新規作成を実行する (`tools/agy_runner.py:run_agy_edit`)。

### agys
- **定義**: Antigravity Skills (または Antigravity System 内蔵のスキル群)。
- **補足**: `agy`（CLIバイナリ本体）と混同しないこと。本プロジェクトでは、コード自動生成やレビュー巡回を担う専用スキル（例: `satellite-ideation-reviewer`）を指す際に用いられる。

### backend
- **定義**: LLM 推論またはコード編集を実行するエンジンの種別・実行基盤。
- **種別**:
  - `agy`: Antigravity CLI バックエンド。GPU リースを必要とせず外部モデルへ接続。
  - `ollama`: ローカル GPU 上で動作する Ollama サーバー。JEV 判定（`qwen2.5:0.5b`）などで常駐。
  - `llama_server`: `llama-server` 互換のローカル推論バックエンド。

### route
- **定義**: `config/models.yaml` の `routes` マッピングテーブル。
- **役割**: 各ノードの実行インテント（`spec_draft`, `code_review`, `code_edit` 等）が、どの `profile` を使用して実行されるかを一元決定する。ロールバック時は routes の向き先を変更するだけで即座に切り戻し可能。

### profile
- **定義**: `config/models.yaml` の `profiles` セクションで定義される実行構成。
- **項目**: `backend`, `model`, `timeout`, `context_window`, `temperature` などの接続・パラメータ仕様を定義する。

### satellite (サテライト / 衛星)
- **定義**: 母艦から独立して開発・運用される個別プロダクトのリポジトリ（`projects/<name>/` 配下、または外部リポジトリ）。
- **特徴**:
  - 自身で独立した Git リポジトリ（`.git`）を持つ。
  - プロダクトコード（`src/`, `tests/` 等）のほか、自律運用の正本メタデータ（`docs/project.json`, `docs/tasks.md`, `docs/issues/*.md`）を内包する。

### mother (母艦)
- **定義**: `second-brain-graph` リポジトリ本体。
- **役割**: サテライト台帳（`.project-registry.json`）、全体のタスクスコアリング、夜間バッチワーカー、品質ゲート、JEV 判定エンジンを中央集約管理する。
- **保護**: `tools/edit_guard.py` により、コード編集エンジンが母艦領域を直接編集することは厳格に遮断・保護される（`MotherRepositoryProtectionError`）。

### coder
- **定義**: LangGraph オーケストレーターの `code_node` で動作する自律コーディング役割。
- **エンジン**: `config/models.yaml` の設定に応じて、`agy`（推奨デフォルト）または `aider`（互換フォールバック）が作業ツリーの差分編集・新規ファイル生成を担う。

---

## 2. 状態・ライフサイクル用語

| 用語 | 説明 |
| :--- | :--- |
| `stage:ideation` | 要件定義・アイデア創出・壁打ちフェーズの Issue。自律実装パイプラインには投入されない。 |
| `stage:ready` | 壁打ちが完了し、仕様・受け入れ基準が確定した実装準備完了フェーズの Issue。夜間ワーカーの投入対象。 |
| `edit_guard` | 作業ツリー外や母艦リポジトリ、機密情報ファイルの書き込み・破壊を未然に防止・ロールバックする境界ガード。 |
| `allowed_new_file_globs` | サテライトの `project.json` で定義された、新規ファイルの作成を許可するワイルドカードパターン一覧。 |

# 「第二の脳」母艦 (second-brain-graph)

**LLMマルチエージェント × ナレッジグラフ統括・自律タスク実行基盤**

---

## 1. 概要
`second-brain-graph` は、LangGraph および LiteLLM をベースとした自律型タスク実行基盤（母艦）です。
「母艦 × 衛星アーキテクチャ」を採用し、母艦リポジトリ側で共通ツール・設計仕様・LLMオーケストレーションを集中管理しつつ、複数の独立プロダクト（衛星リポジトリ）のタスクを横断的に評価・自動実行します。

---

## 2. ディレクトリ構成（正本）

本プロジェクトの標準ディレクトリ構成および各ファイルの役割は以下の通りです。

```text
~/second-brain-graph/               # 母艦
├── docs/                           # 設計仕様書・各種ガイド
│   ├── design/                     # 各種設計書・運用設計・課題一覧
│   │   ├── SBOS-BD-002_基本設計書.md
│   │   ├── SBOS-DD-003_詳細設計書.md
│   │   ├── SBOS-DD-004_Aider統合仕様.md
│   │   ├── SBOS-DD-005_Backend_GPUリース仕様.md
│   │   ├── SBOS-DD-006_品質ゲート_レビュー仕様.md
│   │   ├── SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md
│   │   ├── SBOS-DD-007_永続化_排他制御仕様.md
│   │   ├── SBOS-ENV-001_環境構築仕様書.md
│   │   ├── SBOS-MULTI-001_複数リポジトリ_差分設計書.md
│   │   ├── SBOS-OP-001_運用詳細設計書.md
│   │   └── SBOS-PM-005_課題矛盾一覧.md
│   ├── features/                   # 機能別の利用契約と運用手順
│   ├── how-to/                     # 開発・運用各種ガイド
│   └── setup/                      # 環境構築手順・依存関係ガイド
│
├── tools/                          # オーケストレータ ＆ 自動化ツール群
│   ├── lang/                       # 多言語コード品質・構文検証基盤 (Tree-sitter)
│   ├── templates/                  # LLMエージェント用プロンプトテンプレート
│   │   ├── planner.md
│   │   ├── coder.md
│   │   └── reviewer.md
│   ├── orchestrator_graph.py       # LangGraph本体 ＆ CLI (JEV計画適合性ゲート内包)
│   ├── jev_adapter.py              # JEV (Zero-Decode判定エンジン) 連携アダプター
│   ├── metadata_store.py           # プロジェクト台帳・タスク状態・実行履歴・排他ロック管理
│   ├── sanitizer.py                # 機密情報マスキング共通モジュール
│   ├── llm_client.py               # LiteLLMラッパー
│   ├── aider_runner.py             # Aider自動制御モジュール
│   ├── add_project.py              # 新規衛星プロジェクト登録・ラベル同期
│   ├── screen_issues.py            # Issueの重複・カテゴリスクリーニング
│   ├── close_stale_issues.py       # 放置Issueの自動クローズ
│   ├── score_issues.py             # 全衛星横断タスクスコアリング
│   ├── promote_issue.py            # Issueの壁打ち完了・stage:ready昇格
│   ├── issue_spec_manager.py       # docs/issues仕様書の生成・自己修復
│   ├── periodic_review_runner.py   # 定周期レビュー・Issue/tasks.md同期
│   ├── run_task.py                 # タスク単位の実行CLI
│   ├── nightly_task_worker.py      # 夜間タスクワーカー
│   ├── backend_coordinator.py      # LLMバックエンドの実行調停
│   ├── build_modelfile.py          # Ollama Modelfile生成
│   ├── register_ollama_model.py    # Ollamaモデル登録
│   └── gguf_manager.py             # GGUFモデル管理
│
├── submodules/                     # 内部組み込みモジュール (Git Submodule)
│   └── jev-localsystem/            # JEV Zero-Decodeローカル判定推論基盤
│
├── metadata/                       # メタデータおよび台帳格納ディレクトリ（正本）
│   ├── .project-registry.json      # 衛星中央台帳 (Issueプレフィックス -> パスマッピング)
│   └── projects/
│       └── <PROJECT_KEY>/          # 衛星プロダクトのメタデータ
│           ├── project.json        # 衛星識別メタデータ
│           └── tasks.md            # タスク定義ファイル
│
├── .gemini/                        # エージェント連携・自律スキル群
│   └── skills/
│       └── satellite-ideation-reviewer/ # agysによるサテライトコード自律レビュー＆Issue起票スキル
│
└── projects/                       # 衛星プロダクト格納ディレクトリ（ソースコード専用・Git完全隔離）
    └── <project-name>/             # 各衛星プロダクト (個別のGitリポジトリ)
```

---

## 3. クイックスタート

### Step 1: 依存関係のセットアップ
`uv` を利用して仮想環境の作成とパッケージ同期を行います。

```bash
uv sync
```

### Step 2: 静的解析およびテスト
```bash
# コードチェック＆フォーマット
uv run ruff check .
uv run ruff format .

# 型チェック
uv run mypy .

# テスト実行
uv run pytest
```

### Step 3: スコアリングおよびオーケストレータの実行
```bash
# 全衛星プロジェクトのタスク優先度スコアリング
uv run python tools/score_issues.py

# 本日の実行計画（推奨上位3件）を表示
uv run python tools/orchestrator_graph.py orchestrate

# 指定された Issue ID の自律グラフ実行
uv run python tools/orchestrator_graph.py execute --issue-id EC-012
```

### Step 4: Issueライフサイクルとサテライトコードレビュー
```bash
# サテライトのセキュリティレビュー（ドライラン）
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py --target env_builder --theme security --dry-run

# Issueの壁打ち完了・stage:ready昇格（プレビュー）
uv run python tools/promote_issue.py --project env_builder --issue 123 --dry-run

# 定周期レビュー、GitHub Issueとtasks.mdの同期、docs/issues自己修復
uv run python tools/periodic_review_runner.py --status-only
```

---

## 4. ドキュメント体系

仕様および設計の詳細については、[docs/README.md](docs/README.md) をご参照ください。

- **[自律レビュー＆Issue起票仕様書](docs/features/satellite_ideation_reviewer.md)**: `agys` によるサテライトコードレビューと完全自動起票
- **[基本設計書 (SBOS-BD-002)](docs/design/SBOS-BD-002_基本設計書.md)**: システムアーキテクチャと全体方針
- **[詳細設計書 (SBOS-DD-003)](docs/design/SBOS-DD-003_詳細設計書.md)**: LangGraph / LiteLLM / Aider の内部構造
- **[Aider統合仕様 (SBOS-DD-004)](docs/design/SBOS-DD-004_Aider統合仕様.md)**: Aiderの起動・編集・フェイルセーフ契約
- **[Backend GPUリース仕様 (SBOS-DD-005)](docs/design/SBOS-DD-005_Backend_GPUリース仕様.md)**: LLMバックエンドとGPUリース制御
- **[品質ゲート・レビュー仕様 (SBOS-DD-006)](docs/design/SBOS-DD-006_品質ゲート_レビュー仕様.md)**: Ruff、pytest、LLMレビュー、Reviewdogの品質ゲート
- **[Issueライフサイクル仕様 (SBOS-DD-007)](docs/design/SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md)**: JEV検問、stageラベル、tasks.md/docs/issues同期
- **[永続化・排他制御仕様 (SBOS-DD-007)](docs/design/SBOS-DD-007_永続化_排他制御仕様.md)**: 状態保存とプロジェクトロック
- **[環境構築仕様書 (SBOS-ENV-001)](docs/design/SBOS-ENV-001_環境構築仕様書.md)**: パッケージ管理および環境変数規定
- **[運用詳細設計書 (SBOS-OP-001)](docs/design/SBOS-OP-001_運用詳細設計書.md)**: 日次バッチと監査ログ運用
- **[複数リポジトリ差分設計書 (SBOS-MULTI-001)](docs/design/SBOS-MULTI-001_複数リポジトリ_差分設計書.md)**: 母艦×衛星のGit隔離と中央台帳仕様
- **[課題・矛盾点一覧 (SBOS-PM-005)](docs/design/SBOS-PM-005_課題矛盾一覧.md)**: 仕様書間の矛盾解消・課題トラッキングマトリクス

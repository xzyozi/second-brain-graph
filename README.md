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
│   ├── design/                     # 各種設計書 (BD, DD, ORCH, ENV, OP, MULTI, PM)
│   │   ├── SBOS-BD-002_基本設計書.md
│   │   ├── SBOS-DD-003_詳細設計書.md
│   │   ├── SBOS-ORCH-001_オーケストレイト設計書.md
│   │   ├── SBOS-ENV-001_環境構築仕様書.md
│   │   ├── SBOS-OP-001_運用詳細設計書.md
│   │   ├── SBOS-MULTI-001_複数リポジトリ_差分設計書.md
│   │   └── SBOS-PM-005_課題矛盾一覧.md
│   ├── features/                   # 機能別の利用契約と運用手順
│   ├── how-to/                     # 開発・運用各種ガイド
│   └── setup/                      # 環境構築手順・依存関係ガイド
│
├── tools/                          # オーケストレータ ＆ 自動化ツール群
│   ├── .cache/                     # キャッシュディレクトリ (gitignore対象)
│   │   ├── priority-cache.json     # score-issues.py 優先度算出結果
│   │   ├── blocked.json            # check-blockers.py ブロッカー検知結果
│   │   └── execution_history.json  # 実行監査ログ
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
│   ├── add_project.py              # 新規衛星プロジェクト登録スクリプト
│   ├── score_issues.py             # 全衛星横断タスクスコアリングスクリプト
│   ├── check-blockers.py           # 依存関係ブロッキング検知スクリプト
│   ├── notify.py                   # 通知バッチ (--event daily_summary)
│   └── backup-second-brain.ps1     # 定期バックアップスクリプト
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

---

## 4. ドキュメント体系

仕様および設計の詳細については、[docs/README.md](docs/README.md) をご参照ください。

- **[基本設計書 (SBOS-BD-002)](docs/design/SBOS-BD-002_基本設計書.md)**: システムアーキテクチャと全体方針
- **[詳細設計書 (SBOS-DD-003)](docs/design/SBOS-DD-003_詳細設計書.md)**: LangGraph / LiteLLM / Aider の内部構造
- **[オーケストレイト設計書 (SBOS-ORCH-001)](docs/design/SBOS-ORCH-001_オーケストレイト設計書.md)**: 自律実行ループと依存関係解決
- **[環境構築仕様書 (SBOS-ENV-001)](docs/design/SBOS-ENV-001_環境構築仕様書.md)**: パッケージ管理および環境変数規定
- **[運用詳細設計書 (SBOS-OP-001)](docs/design/SBOS-OP-001_運用詳細設計書.md)**: 日次バッチと監査ログ運用
- **[複数リポジトリ差分設計書 (SBOS-MULTI-001)](docs/design/SBOS-MULTI-001_複数リポジトリ_差分設計書.md)**: 母艦×衛星のGit隔離と中央台帳仕様
- **[課題・矛盾点一覧 (SBOS-PM-005)](docs/design/SBOS-PM-005_課題矛盾一覧.md)**: 仕様書間の矛盾解消・課題トラッキングマトリクス

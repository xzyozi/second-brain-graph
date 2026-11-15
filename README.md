# 「第二の脳」母艦 (second-brain-graph)

**LLMマルチエージェント × ナレッジグラフ統括・自律タスク実行基盤**

---

## 1. 概要
`second-brain-graph` は、LangGraph・Antigravity CLI (`agy`)・Ollama (JEV) を基盤とした自律型タスク実行基盤（母艦）です。
「母艦 × 衛星アーキテクチャ」および **GitHub Issues SSOT（Single Source of Truth）** を採用し、母艦リポジトリ側で共通ツール・設計仕様・品質ゲート・LLMオーケストレーションを集中管理しつつ、複数の独立プロダクト（衛星リポジトリ）の Issue を横断的に評価・自律実行します。

---

## 2. ディレクトリ構成（正本）

本プロジェクトの標準ディレクトリ構成および各ファイルの役割は以下の通りです。

```text
~/second-brain-graph/               # 母艦
├── config/                         # モデル・プロンプト・ワーカー設定正本
│   ├── models.yaml                 # routes / profiles 定義 (agy / ollama)
│   ├── prompt.yaml                 # プロンプト設定
│   └── nightly_worker.toml         # 夜間ワーカー実行設定
│
├── docs/                           # 設計仕様書・各種ガイド・証跡
│   ├── adr/                        # アーキテクチャ決定記録 (ADR 0001〜0004)
│   ├── design/                     # 各種設計書・運用設計・課題一覧 (SBOS-*)
│   ├── features/                   # 機能別の利用契約と運用手順
│   ├── how-to/                     # 開発・運用各種ガイド
│   ├── setup/                      # 環境構築手順・依存関係ガイド
│   └── test/                       # agy 移行確認試験書・L3〜L5 エビデンス
│
├── tools/                          # オーケストレータ ＆ 自動化ツール群
│   ├── core/                       # オーケストレーション中核
│   │   ├── orchestrator_graph.py   # LangGraph本体 ＆ CLI (JEV検問・境界保護内包)
│   │   ├── edit_guard.py           # コード編集境界ガード (母艦保護・秘密検知・ロールバック)
│   │   ├── prompt_harness.py       # プロンプトSSOTハーネス
│   │   └── sanitizer.py            # 機密情報マスキング共通モジュール
│   ├── backends/                   # LLM / 判定バックエンドアダプター
│   │   ├── agy_client.py           # agy CLI プロセス制御・タイムアウト・エラー分類
│   │   ├── agy_policy.py           # agy 外部送信ポリシー・許可リスト検証
│   │   ├── agy_runner.py           # agy コード編集実行エンジン
│   │   ├── backend_coordinator.py  # バックエンド実行調停 (agy / GPUリース)
│   │   ├── jev_adapter.py          # JEV (Zero-Decode判定エンジン) 連携アダプター
│   │   └── llm_client.py           # LLM / agy テキスト応答ラッパー
│   ├── workspace/                  # ワークスペース・GitHub Issues SSOT 基盤
│   │   ├── github_issues.py        # GitHub Issues 共通取得・フィクスチャ解決層
│   │   ├── metadata_store.py       # 中央台帳・実行状態・排他ロック管理
│   │   ├── target_files.py         # Target Files 抽出・不正パス検証・実在解決
│   │   ├── config_loader.py        # YAML / プロジェクト設定ローダー
│   │   └── git_utils.py            # Git 操作ユーティリティ
│   ├── lifecycle/                  # Issue ライフサイクル管理
│   │   ├── periodic_review_runner.py # 定周期コードレビュー・GitHub Issues 状態評価
│   │   └── close_stale_issues.py   # 放置 stage:ideation Issue の自動クローズ
│   ├── lang/                       # 多言語コード品質・構文検証基盤 (Tree-sitter)
│   ├── models/                     # ローカルモデル管理 (Modelfile / GGUF / Ollama)
│   ├── templates/                  # Modelfile サンプルテンプレート
│   ├── score_issues.py             # 全衛星横断タスクスコアリング (GitHub Issues SSOT)
│   ├── promote_issue.py            # Issue 壁打ち完了・stage:ready 昇格ツール
│   ├── screen_issues.py            # Issue の JEV 重複検知・カテゴリスクリーニング
│   ├── run_task.py                 # 衛星クリーンアップ付きタスク実行 CLI
│   ├── nightly_task_worker.py      # 夜間自律タスクワーカー
│   ├── add_project.py              # 新規衛星プロジェクト登録・ラベル同期
│   └── doctor.py                   # サテライト受入態勢・環境診断ツール
│
├── submodules/                     # 内部組み込みモジュール (Git Submodule)
│   └── jev-localsystem/            # JEV Zero-Decode ローカル判定推論基盤
│
├── metadata/                       # メタデータおよびテンプレート格納ディレクトリ
│   ├── .project-registry.json      # 衛星中央台帳 (PROJECT_KEY -> パス・repo マッピング)
│   ├── templates/
│   │   └── issue_template.md       # 母艦標準 Issue テンプレート (0〜8章)
│   └── projects/
│       └── <PROJECT_KEY>/          # 実行状態・排他ロック等（仕様正本は GitHub Issues）
│
├── .gemini/                        # エージェント連携・自律スキル群
│   └── skills/
│       └── satellite-ideation-reviewer/ # agys によるサテライトコード自律レビュー＆Issue起票
│
└── projects/                       # 衛星プロダクト格納ディレクトリ（Git完全隔離）
    └── <project-name>/             # 各衛星プロダクト (個別のGitリポジトリ)
        └── docs/project.json       # 衛星構成・ブランチ・言語・テスト設定 (SSOT)
```

---

## 3. クイックスタート

### Step 1: 依存関係のセットアップ
`uv` を利用して仮想環境の作成と開発用を含むパッケージ同期を行います。

```bash
uv sync --extra dev
```

### Step 2: 静的解析およびテスト
```bash
# コードチェック＆フォーマット確認
uv run ruff check .
uv run ruff format --check .

# 型チェック
uv run mypy .

# テスト実行
uv run pytest
```

### Step 3: スコアリングおよびオーケストレータの実行
```bash
# 全衛星プロジェクトのタスク優先度スコアリング (GitHub Issues SSOT)
uv run python tools/score_issues.py

# 本日の実行計画（推奨上位3件）を表示
uv run python tools/core/orchestrator_graph.py orchestrate

# 指定された Issue ID ({PROJECT_KEY}-{issue_number:04d}) の自律実行
uv run python tools/core/orchestrator_graph.py execute --issue-id TFG-0005

# 衛星クリーンアップ付きタスク実行 CLI
uv run python tools/run_task.py TFG-0005 --dry-run
```

### Step 4: Issue ライフサイクル・サテライトレビュー・環境診断
```bash
# サテライトのセキュリティレビュー（ドライラン）
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py --target env_builder --theme security --dry-run

# Issue の壁打ち完了・stage:ready 昇格（プレビュー）
uv run python tools/promote_issue.py --project env_builder --issue 123 --dry-run

# 定周期レビューおよび GitHub Issues 状態評価（ステータス確認のみ）
uv run python tools/lifecycle/periodic_review_runner.py --status-only

# 衛星プロジェクト受入態勢の環境診断
uv run python tools/doctor.py
```

---

## 4. ドキュメント体系

仕様および設計の詳細については、[docs/README.md](docs/README.md) をご参照ください。

- **[用語集・ドメインコンテキスト (CONTEXT.md)](CONTEXT.md)**: 用語（`agy`, `agys`, `route`, `profile`, `satellite`, `mother`）の SSOT
- **[自律レビュー＆Issue起票仕様書](docs/features/satellite_ideation_reviewer.md)**: `agys` によるサテライトコードレビューと完全自動起票
- **[agy 移行確認試験書 (SBOS-TEST-001)](docs/test/SBOS-TEST-001_agy移行確認試験書.md)**: L0〜L5 検証項目およびエビデンス
- **[基本設計書 (SBOS-BD-002)](docs/design/SBOS-BD-002_基本設計書.md)**: システムアーキテクチャと全体方針
- **[詳細設計書 (SBOS-DD-003)](docs/design/SBOS-DD-003_詳細設計書.md)**: LangGraph / agy の内部構造
- **[コード編集エンジン統合仕様 (SBOS-DD-004)](docs/design/SBOS-DD-004_Aider統合仕様.md)**: `agy` の起動・編集・フェイルセーフ契約（Aider は退役済みの旧資産。ファイル名のみ互換のため維持）
- **[Backend GPUリース仕様 (SBOS-DD-005)](docs/design/SBOS-DD-005_Backend_GPUリース仕様.md)**: LLM バックエンドと GPU リース制御
- **[品質ゲート・レビュー仕様 (SBOS-DD-006)](docs/design/SBOS-DD-006_品質ゲート_レビュー仕様.md)**: 静的解析・テスト・LLM レビュー・JEV 品質ゲート
- **[Issueライフサイクル仕様 (SBOS-DD-007)](docs/design/SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md)**: JEV 検問、`stage:*` ラベル、GitHub Issues SSOT 運用
- **[永続化・排他制御仕様 (SBOS-DD-007)](docs/design/SBOS-DD-007_永続化_排他制御仕様.md)**: 状態保存とプロジェクトロック
- **[環境構築仕様書 (SBOS-ENV-001)](docs/design/SBOS-ENV-001_環境構築仕様書.md)**: パッケージ管理および環境変数規定
- **[運用詳細設計書 (SBOS-OP-001)](docs/design/SBOS-OP-001_運用詳細設計書.md)**: 日次バッチと監査ログ運用
- **[複数リポジトリ差分設計書 (SBOS-MULTI-001)](docs/design/SBOS-MULTI-001_複数リポジトリ_差分設計書.md)**: 母艦×衛星の Git 隔離と中央台帳仕様
- **[課題・矛盾点一覧 (SBOS-PM-005)](docs/design/SBOS-PM-005_課題矛盾一覧.md)**: 仕様書間の矛盾解消・課題トラッキングマトリクス

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
~/second-brain-graph/               # 母艦リポジトリ
├── .gitignore                      # /projects/* をGit遮断（衛星隔離）
├── pyproject.toml                  # Python プロジェクト設定 (uv / 依存関係)
├── ruff.toml                       # Ruff リンター/フォーマッタ設定
├── mypy.ini                        # MyPy 型チェック設定
├── README.md                       # 本ファイル (プロジェクト概要 & クイックスタート)
│
├── docs/                           # 仕様書・設計書・ドキュメント管理ディレクトリ
│   ├── README.md                   # 文書体系索引 (SBOS文書コード凡例)
│   ├── design/                     # 各種設計書 (BD, DD, ORCH, ENV, OP, MULTI)
│   │   ├── 01_基本設計書_SBOS-BD-002.md
│   │   ├── 02_詳細設計書_SBOS-DD-003.md
│   │   ├── 03_オーケストレイト設計書_SBOS-ORCH-001.md
│   │   ├── 04_環境構築仕様書_SBOS-ENV-001.md
│   │   ├── 05_運用詳細設計書_SBOS-OP-001.md
│   │   └── 06_複数リポジトリ_差分設計書_SBOS-MULTI-001.md
│   ├── setup/                      # 環境構築手順・依存関係ガイド
│   │   ├── dependency_management.md
│   │   ├── environment_setup_guide.md
│   │   └── toml_project_setup.md
│   └── how-to/                     # 開発・運用各種ガイド
│
├── tools/                          # オーケストレータ & 自動化ツール群
│   ├── .cache/                     # キャッシュディレクトリ (gitignore対象)
│   │   ├── priority-cache.json     # score-issues.py 優先度算出結果
│   │   ├── blocked.json            # check-blockers.py ブロッカー検知結果
│   │   └── execution_history.json  # 実行監査ログ
│   ├── templates/                  # LLMエージェント用プロンプトテンプレート
│   │   ├── planner.md
│   │   ├── coder.md
│   │   └── reviewer.md
│   ├── orchestrator_graph.py       # LangGraph本体 ＆ CLI
│   ├── llm_client.py               # LiteLLMラッパー
│   ├── aider_runner.py              # Aider自動制御モジュール
│   ├── score-issues.py              # 全衛星横断タスクスコアリングスクリプト
│   ├── check-blockers.py            # 依存関係ブロッキング検知スクリプト
│   ├── notify.py                    # 通知バッチ (--event daily_summary)
│   └── backup-second-brain.ps1      # 定期バックアップスクリプト
│
└── projects/                       # 衛星プロダクト格納ディレクトリ
    ├── .project-registry.json      # 衛星中央台帳 (Issueプレフィックス -> パスマッピング)
    └── <project-name>/              # 各衛星プロダクト (個別のGitリポジトリ)
        ├── project.json            # 衛星識別メタデータ
        └── tasks.md                # タスク定義ファイル
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
uv run python tools/score-issues.py

# 最優先タスクの自動実行
uv run python tools/orchestrator_graph.py --auto
```

---

## 4. ドキュメント体系

仕様および設計の詳細については、[docs/README.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/README.md) をご参照ください。

- **[基本設計書 (SBOS-BD-002)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/01_%E5%9F%BA%E6%9C%AC%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-BD-002.md)**: システムアーキテクチャと全体方針
- **[詳細設計書 (SBOS-DD-003)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/02_%E8%A1%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-DD-003.md)**: LangGraph / LiteLLM / Aider の内部構造
- **[オーケストレイト設計書 (SBOS-ORCH-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/03_%E3%82%AA%E3%83%BC%E3%82%B1%E3%82%B9%E3%83%80%E3%83%AC%E3%82%A4%E3%83%80%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-ORCH-001.md)**: 自律実行ループと依存関係解決
- **[環境構築仕様書 (SBOS-ENV-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/04_%E7%222%E6%A7%87%E7%AF%81%E4%BB%95%E6%A7%98%E6%9B%B8_SBOS-ENV-001.md)**: パッケージ管理および環境変数規定
- **[運用詳細設計書 (SBOS-OP-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/05_%E9%81%8B%E7%94%A8%E8%A1%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-OP-001.md)**: 日次バッチと監査ログ運用
- **[複数リポジトリ差分設計書 (SBOS-MULTI-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/06_%E8%A4%87%E6%95%B0%E3%83%AA%E3%83%9D%E3%82%B8%E3%83%88%E3%83%AA_%E5%B7%AE%E5%88%86%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-MULTI-001.md)**: 母艦×衛星のGit隔離と中央台帳仕様
- **[課題・矛盾点一覧 (SBOS-PM-005)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/07_%E8%AA%B2%E9%A1%8C%E7%9F%9B%E7%9B%BE%E4%B8%80%E8%A6%A7_SBOS-PM-005.md)**: 仕様書間の矛盾解消・課題トラッキングマトリクス

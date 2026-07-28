# second-brain-graph

「第二の脳」ナレッジグラフ＆LLMエージェント統括基盤リポジトリ。

---

## 1. 概要
`second-brain-graph` は、ナレッジのグラフ構造化、マルチエージェントオーケストレーション、および自律タスク実行基盤を提供するプロジェクトです。

---

## 2. ディレクトリ構造

```text
second-brain-graph/
├── docs/                      # 各種設計書・ドキュメント類
│   ├── design/                # 基本設計、詳細設計、複数リポジトリ差分設計書
│   ├── setup/                 # 環境構築・依存関係管理ガイド
│   └── how-to/                # 運用・開発ガイドライン
├── pyproject.toml             # Python プロジェクト設定 (uv / dependencies)
├── mypy.ini                   # MyPy 型チェック設定
├── ruff.toml                  # Ruff リンター / フォーマッタ設定
└── README.md                  # 本ファイル
```

---

## 3. クイックスタート

### 3.1 依存関係のセットアップ (`uv`)
```bash
# パッケージの同期と仮想環境構築
uv sync
```

### 3.2 静的解析・リンターの実行
```bash
# Ruff によるコードチェック & フォーマット
uv run ruff check .
uv run ruff format .

# MyPy による型チェック
uv run mypy .
```

### 3.3 テストの実行
```bash
# Pytest の実行
uv run pytest
```

---

## 4. ドキュメント一覧
詳細な設計および構築手順については以下を参照してください。
- [環境構築手順ガイド](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/environment_setup_guide.md)
- [依存関係管理仕様](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/dependency_management.md)
- [複数リポジトリ差分設計書 (SBOS-MULTI-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/06_%E8%A4%87%E6%95%B0%E3%83%AA%E3%83%9D%E3%82%B8%E3%83%88%E3%83%AA_%E5%B7%AE%E5%88%86%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-MULTI-001.md)

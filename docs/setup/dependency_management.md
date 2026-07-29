# uv による依存関係・パッケージ管理仕様

本プロジェクトでは、高速かつ確定的パッケージマネージャー **`uv`** (Astral製) および **`pyproject.toml`** を用いて依存関係を一元管理します。

---

## 1. 概要と構成ファイル

依存関係および仮想環境は以下のファイルで管理されます。

- **`pyproject.toml`**: プロジェクトが直接必要とするライブラリおよび開発依存関係 (`[project.optional-dependencies] dev`) を記述する標準設定ファイルです。手動編集を行います。
- **`uv.lock`**: `uv` によって自動更新・ロックされる完全確定バージョン一覧です。直接編集しません。

---

## 2. 依存パッケージの追加・同期手順

### ① 直接依存パッケージの追加
`pyproject.toml` の `dependencies` または `[project.optional-dependencies] dev` にライブラリ名を追加します。

### ② 仮想環境の同期 (`uv sync`)
ターミナルで以下のコマンドを実行し、依存関係をアトミックに同期します。

```bash
# 基本依存関係の同期
uv sync

# 開発用ツール (ruff, mypy, pytest, pip-licenses) も含めた同期 (推奨)
uv sync --extra dev
```

---

## 3. 品質チェック・診断コマンド

```bash
# コードチェック
uv run ruff check .

# 型チェック
uv run mypy .

# 単体テスト
uv run pytest

# ライセンス確認
uv run pip-licenses
```

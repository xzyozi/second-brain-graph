# 環境構築手順ガイド (Environment Setup Guide)

文書番号: SBOS-ENV-GUIDE-001  
最終更新: 2026年7月29日  

---

## 1. 概要
本ドキュメントは、`second-brain-graph` プロジェクトにおける開発環境の構築手順および静的解析ツール（Ruff, MyPy）、OSSライセンス検証の手順を解説する手順書です。

---

## 2. 前提条件
- **OS**: Windows 11 / Linux / macOS
- **Python**: 3.10 以上 3.14 未満 (推奨 `3.12`)
- **パッケージマネージャー**: `uv` (Astral uv)

---

## 3. 環境構築手順

### 3.1 `uv` のインストール
`uv` がインストールされていない場合は、以下のコマンドでインストールします。

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3.2 仮想環境の作成とパッケージ同期
プロジェクトルートディレクトリ（`second-brain-graph`）で以下のコマンドを実行し、仮想環境の作成および依存関係のインストールを行います。

```bash
# 仮想環境作成と依存関係同期 (Python 3.12 固定)
uv sync
```

---

## 4. 静的解析およびフォーマッタの実行

本プロジェクトでは、コード品質向上と型安全性のために `ruff` と `mypy` を使用します。

### 4.1 Ruff (コードフォーマット＆リンター)

```bash
# コードチェック
uv run ruff check .

# 自動修正可能なエラーの修正
uv run ruff check --fix .

# コードフォーマット
uv run ruff format .
```

### 4.2 MyPy (型チェック)

```bash
# 型チェックの実行
uv run mypy .
```

---

## 5. テスト実行 (Pytest)

```bash
# テストの実行
uv run pytest
```

---

## 6. OSS ライセンス遵守およびセキュリティ確認

本プロジェクトでは、商用・ローカル利用に寛容なライセンス（MIT, Apache-2.0, BSD等）のOSSのみを採用します。詳細は [oss_license_policy.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/oss_license_policy.md) を参照してください。

### 6.1 ライセンス適合性の確認
依存パッケージに禁忌とされるコピーレフト（GPL/AGPL）が含まれていないかを検証します。

```bash
# 依存パッケージのライセンス一覧表示
uv run pip-licenses

# 強コピーレフト (GPL/AGPL) のチェック
uv run pip-licenses | grep -iE "GPL|Affero"
```

---

## 7. ディレクトリ構造とドキュメント配置
```text
second-brain-graph/
├── docs/
│   ├── design/        # 設計書 (基本設計, 詳細設計, 差分設計書等)
│   ├── setup/         # 環境構築・依存関係・ライセンスポリシー
│   └── how-to/        # 開発手順・運用ガイド
├── pyproject.toml     # プロジェクト設定および依存関係
├── .python-version    # 利用するPythonバージョン固定 (3.12)
├── ruff.toml          # Ruffリンター/フォーマッタ設定
└── mypy.ini           # MyPy型チェック設定
```

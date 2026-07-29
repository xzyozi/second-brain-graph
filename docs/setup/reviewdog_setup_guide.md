# Reviewdog クローン・ビルド・配置ガイド

文書番号: SBOS-SETUP-REVIEWDOG-001  
最終更新: 2026年7月29日  

---

## 1. 概要
本ドキュメントは、コードレビュー自動化エンジン **Reviewdog** (MIT License) を GitHub リポジトリから `git clone` してビルド・配置し、ローカル開発環境で動作可能な状態にするための手順書です。

---

## 2. 動作要件
- **Git**: インストール済みであること
- **Go (Golang)** (ソースからビルドする場合): Version 1.21 以上
- **対応OS**: Windows 11 / Linux / macOS

---

## 3. クローンおよびビルド手順

### 3.1 Git Clone によるリポジトリ取得

```bash
# 作業ディレクトリまたは外部ツール用ディレクトリでクローン
git clone https://github.com/reviewdog/reviewdog.git
cd reviewdog
```

### 3.2 ソースコードからのビルド (Go がある場合)

```bash
# バイナリのビルド
go build -o reviewdog.exe ./cmd/reviewdog

# 動作確認
./reviewdog.exe -version
```

### 3.3 自動セットアップスクリプトによる配置 (Windows / Linux)

プロジェクト直下の `scripts/windows/setup_reviewdog.ps1` (Windows) または `scripts/linux/setup_reviewdog.sh` (Linux/macOS) を実行することでも自動取得・配置が可能です。

> **Windows Native 環境での注意:**  
> Reviewdog の出力文字化けを防ぐため、事前に PowerShell プロファイル (`$PROFILE`) への UTF-8 永続設定を行っておくことを推奨します。（詳細は [環境構築仕様書 (SBOS-ENV-001) §5.1](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/04_%E7%92%B0%E5%A2%83%E6%A7%8B%E7%AF%89%E4%BB%95%E6%A7%98%E6%9B%B8_SBOS-ENV-001.md#51-windows-native-%E7%92%B0%E5%A2%83%E5%90%91%E3%81%91%E6%9C%80%E9%81%A9%E5%8C%96%E8%A6%8B%E5%87%BA%E3%81%97-powershell) を参照）

```powershell
# Windows (PowerShell)
.\scripts\windows\setup_reviewdog.ps1
```

```bash
# Linux / macOS
bash scripts/linux/setup_reviewdog.sh
```

---

## 4. 本システムにおける利用方法
Reviewdog は、Ruff や MyPy のチェック結果を JSON/rdjson 形式でパースし、コード差分に対するアノテーション出力を生成するために利用されます。

```bash
# 例: Ruff の結果を reviewdog でチェック
uv run ruff check . --output-format=rdjson | reviewdog -f=rdjson -diff="git diff HEAD"
```

# SBOS (Second Brain OS) ドキュメント体系 & 索引

本ディレクトリ（`docs/`）は、**「第二の脳」母艦 (second-brain-graph)** の仕様書・設計書・運用ガイドラインを一括管理するディレクトリです。

---

## 1. 文書コード（プレフィックス）凡例

SBOSの仕様書は、役割ごとに以下の文書コード体系で分類されています。

| プレフィックス | 体系名 | 概要・対象範囲 |
| :--- | :--- | :--- |
| **`SBOS-BD`** | Basic Design (基本設計) | システム構成、全体コンセプト、アーキテクチャ設計 |
| **`SBOS-DD`** | Detailed Design (詳細設計) | エージェント構造、モジュール定義、データモデル |
| **`SBOS-ORCH`** | Orchestrator (オーケストレーション) | タスク自動実行ループ、ブロッカー判定、状態遷移 |
| **`SBOS-ENV`** | Environment (環境仕様) | パッケージ管理、依存関係、実行環境定義 |
| **`SBOS-OP`** | Operations (運用設計) | 日次バッチ、ログ監査、バックアップ運用 |
| **`SBOS-MULTI`** | Multi-Repo (複数リポジトリ) | 母艦×衛星のGit分離、中央台帳 (`.project-registry.json`) |
| **`SBOS-PM`** | Problem Management (課題・矛盾一覧) | 設計文書間の矛盾点、未決事項のトラッキング |

---

## 2. ドキュメント一覧およびリンク

### 2.1 設計書 (docs/design/)
- **[01_基本設計書 (SBOS-BD-002)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/01_%E5%9F%BA%E6%9C%AC%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-BD-002.md)**
- **[02_詳細設計書 (SBOS-DD-003)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/02_%E8%A1%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-DD-003.md)**
- **[03_オーケストレイト設計書 (SBOS-ORCH-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/03_%E3%82%AA%E3%83%BC%E3%82%B1%E3%82%B9%E3%83%80%E3%83%AC%E3%82%A4%E3%83%80%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-ORCH-001.md)**
- **[04_環境構築仕様書 (SBOS-ENV-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/04_%E7%222%E6%A7%87%E7%AF%81%E4%BB%95%E6%A7%98%E6%9B%B8_SBOS-ENV-001.md)**
- **[05_運用詳細設計書 (SBOS-OP-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/05_%E9%81%8B%E7%94%A8%E8%A1%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-OP-001.md)**
- **[06_複数リポジトリ_差分設計書 (SBOS-MULTI-001)](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/06_%E8%A4%87%E6%95%B0%E3%83%AA%E3%83%9D%E3%82%B8%E3%83%88%E3%83%AA_%E5%B7%AE%E5%88%86%E8%A8%AD%E8%A8%88%E6%9B%B8_SBOS-MULTI-001.md)**

### 2.2 セットアップ・環境ガイド (docs/setup/)
- **[environment_setup_guide.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/environment_setup_guide.md)**: 環境構築総合ガイド
- **[oss_license_policy.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/oss_license_policy.md)**: OSSライセンス・モデル利用規約管理ポリシー
- **[dependency_management.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/dependency_management.md)**: uvによる依存関係管理仕様
- **[toml_project_setup.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/setup/toml_project_setup.md)**: pyproject.toml / ruff / mypy 設定ガイド

---

## 3. ドキュメント配置規約
新しいドキュメントを作成・追加する際は、以下のルールに従って配置してください。

1. **アーキテクチャ・設計仕様**: `docs/design/` に配置し、ファイル名冒頭に連番および文書コードを付与する（例: `07_〇〇仕様書_SBOS-XXX-001.md`）。
2. **手順・開発ガイド**: `docs/setup/` または `docs/how-to/` に配置する。
3. **新規作成時の更新手続き**: ドキュメントを追加した場合は、必ず本ファイル (`docs/README.md`) の一覧および直下の [README.md](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/README.md) のリンク表を更新すること。

# ドキュメント管理・運用ガイド

本 `docs/` ディレクトリは、プロジェクトの設計仕様書および各種ガイドラインを管理する領域です。

---

## ディレクトリ構造とテンプレート

* **`docs/design/`**: システムの各種設計書（基本設計、詳細設計、データ構造仕様）および運用ガイドラインを格納する主領域
  * `SBOS-BD-002_基本設計書.md`: システム全体アーキテクチャ
  * `SBOS-DD-003_詳細設計書.md`〜`SBOS-DD-007_*.md`: 各モジュール、品質、Issueライフサイクル、永続化の詳細仕様
  * `SBOS-ENV-001_環境構築仕様書.md` / `SBOS-OP-001_運用詳細設計書.md`: 環境構築・運用仕様
  * `SBOS-MULTI-001_複数リポジトリ_差分設計書.md` / `SBOS-PM-005_課題矛盾一覧.md`: 母艦・衛星設計と課題管理
  * `TEMPLATE_*.md`: 基本設計、詳細設計、データ構造仕様の作成テンプレート
  * `README.md`: 設計ドキュメントの命名規則・執筆・更新運用ルール
* **`docs/features/`**: 機能別の利用契約と運用手順
  * [`aider_format_benchmark.md`](features/aider_format_benchmark.md): Aider edit_format 多角的実証ベンチマーク (`tools/benchmark_aider_formats.py`) 仕様書
  * [`coder_test_and_github_ci_pr_fixer.md`](features/coder_test_and_github_ci_pr_fixer.md): Coderモデル動作検証仕様・実績および GitHub CI PR Fixer 設計書
  * [`multi_language_verifiers.md`](features/multi_language_verifiers.md): 多言語対応コード品質・構文検証基盤 (`tools/lang/`, Tree-sitter) 仕様書
  * [`ollama_modelfile_profile_management.md`](features/ollama_modelfile_profile_management.md): GGUF向けQwen ModelfileのCLI入力契約・生成手順
  * [`satellite_ideation_reviewer.md`](features/satellite_ideation_reviewer.md): `agys` によるサテライトコード自律レビュー＆Issue自動起票スキル仕様書
  * [`yaml_configuration_system.md`](features/yaml_configuration_system.md): YAMLベース共通設定基盤仕様書 (`models.yaml`, `prompt.yaml`)
* **`docs/how-to/`**: 開発・運用の操作手順ガイド
  * [`ollama_gguf_registration.md`](how-to/ollama_gguf_registration.md): 独立GGUFファイルのOllamaローカルモデル登録手順
* **`docs/analysis/`**: 実装調査・フロー解析の記録
  * [`flow-gguf-20260907.md`](analysis/flow-gguf-20260907.md): GGUFバックエンド処理フローの解析記録
* **サテライト生成文書**: サテライト側の `docs/issues/<TASK_ID>.md` は、Issue起票・昇格・定周期同期時に自動生成・自己修復されます。仕様は [`SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md`](design/SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md) を参照してください。

---

## ドキュメント運用ルール概要

詳細な命名ルールや参照規約については **`docs/design/README.md`** を参照してください。

1. **命名ルール**: `[PROJECT_PREFIX]-[TYPE_CODE]-[NUMBER]_[TITLE].md` の統一フォーマットを使用
2. **環境依存リンクの禁止**: 特定環境の絶対パス (`file:///...`) を避け、相対パスまたは標準文書名テキストで参照
3. **具象コード非掲載**: プログラムコードを直接貼らず、パラメータ表・事前/事後条件・契約で記述
4. **SSOT原則**: 同一仕様の重複記述を避け、専門の設計書を一元管理正本とする

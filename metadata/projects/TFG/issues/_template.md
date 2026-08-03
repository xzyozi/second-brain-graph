# [PROJECT_KEY-XXXX] タスクタイトル

## 1. 概要・背景
タスクの背景や目的、解決すべき課題を記述します。

## 2. 仕様および要求事項
- [ ] 要求事項1
- [ ] 要求事項2

## 3. 段階的実装手順 (Step-by-step Execution)
- **Phase 1 (Core Implementation)**: まず `src/` 配下の本体モジュール・主要ロジック・例外クラスのみを最小変更で優先実装すること。
- **Phase 2 (Test Implementation & Refinement)**: 本体実装完了後、`tests/` 配下の単体テストを作成・修正し、テスト通過を確認すること。

## 4. 編集対象ファイル (Target Files)
- `src/path/to/file.py`
- `tests/path/to/test_file.py`

## 5. 除外条件・禁止事項 (Forbidden Actions)
- 無関係な設定ファイルやインターフェースを変更しないこと。
- 既存の公開 API シグネチャを破壊しないこと。
- スコープ外のテストファイルを自動生成しないこと。

## 6. 完了定義 (Definition of Done)
- [ ] 単体テストが通過すること
- [ ] Ruff の静的解析エラーがないこと

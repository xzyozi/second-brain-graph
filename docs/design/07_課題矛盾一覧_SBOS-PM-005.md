# 課題・矛盾点一覧 (Problem Management) Rev.1.1

文書番号: SBOS-PM-005  
版数: Rev.1.1  
改訂日: 2026年7月29日  
関連文書: SBOS-BD-002, SBOS-DD-003, SBOS-OP-001, SBOS-MULTI-001  

---

## 1. 概要
本ドキュメントは、Second Brain OS (SBOS) の各設計仕様書間および実際のツール実装における**矛盾点、非整合事項、および未解決課題の一覧と対応ステータス**を管理するトラッキングドキュメントです。

---

## 2. 矛盾点・課題トラッキングマトリクス

| 課題ID | 関連文書 | 検出された問題・矛盾点 | 解決方針・修正内容 | ステータス |
| :--- | :--- | :--- | :--- | :--- |
| **PM-001** | MULTI-001 §3 / OP-001 §5.1 | 衛星の発見方法が同一文書内で「glob分散スキャン」と「中央台帳スキャン」の2通り定義されていた | 中央台帳方式 (`.project-registry.json`) に一本化。実物実装と整合 | 🟢 解決済み |
| **PM-002** | MULTI-001 §4 / OP-001 | 優先度キャッシュのフィールド名 (`"project"`) が実物の `"project_key"` / `"project_dir"` と不一致 | フィールド名を `"project_key"` / `"project_dir"` に統一 | 🟢 解決済み |
| **PM-003** | ENV-001 §2.2 / DD-003 | 旧 OpenCode (`.opencode/opencode.json`) の廃止に伴うモデル設定の一元管理方法が未確定 | `config/models.json` および `tools/config_loader.py` を新設し一元管理 | 🟢 解決済み |
| **PM-004** | MULTI-001 §5 | 新規衛星を `.project-registry.json` へ手動登録する手順はあるが、CLIツール化されていない | `tools/add-project.py` CLIスクリプトの開発（今後実施予定） | 🟡 未解決・タスク化 |
| **PM-005** | ENV-001 §1.2 / pyproject.toml | Python 3.14 環境で `scipy` の Fortran ビルドエラーが発生する問題 | `.python-version` を `3.12` に固定し事前ビルドホイール利用を徹底 | 🟢 解決済み |

---

## 3. 詳細説明と今後の対応計画

### PM-004: 衛星プロジェクト追加 CLI (`tools/add-project.py`) の自動化
* **背景**: 新規衛星プロダクトを追加する際、`project.json` の作成と `.project-registry.json` への辞書登録ワンライナーを手動で実行する必要がある。
* **対応計画**: `python tools/add-project.py --name "新規サービス" --key "NEW"` コマンドで全初期化を完結させるスクリプトを実装予定。

---

## 4. 改訂履歴
- **2026/07/29 (Rev.1.1)**: 旧障害記録スクリプト (record-failure.py) に関する検討項目 (旧PM-005) を削除。
- **2026/07/29 (Rev.1.0)**: 初版作成。PM-001〜PM-006 の矛盾点・課題を整理・初出定義。

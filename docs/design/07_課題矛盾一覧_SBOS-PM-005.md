# 課題・矛盾点一覧 (Problem Management) Rev.1.4

文書番号: SBOS-PM-005  
版数: Rev.1.4  
改訂日: 2026年7月29日  
関連文書: SBOS-BD-002, SBOS-DD-003, SBOS-ORCH-001, SBOS-ENV-001, SBOS-OP-001, SBOS-MULTI-001  

---

## 1. 概要
本ドキュメントは、Second Brain OS (SBOS) の各設計仕様書間および実際のツール実装における**矛盾点、非整合事項、および未解決課題の一覧と対応ステータス**を管理するトラッキングドキュメントです。

---

## 2. 矛盾点・課題トラッキングマトリクス

| 課題ID | 関連文書 | 重要度 | 検出された問題・矛盾点 | 解決方針・修正内容 | ステータス |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **PM-001** | MULTI-001 §3 / OP-001 §5.1 | — | 衛星の発見方法が同一文書内で「glob分散スキャン」と「中央台帳スキャン」の2通り定義されていた | 中央台帳方式 (`.project-registry.json`) に一本化。実物実装と整合 | 🟢 解決済み |
| **PM-002** | MULTI-001 §4 / OP-001 | — | 優先度キャッシュのフィールド名 (`"project"`) が実物の `"project_key"` / `"project_dir"` と不一致 | フィールド名を `"project_key"` / `"project_dir"` に統一 | 🟢 解決済み |
| **PM-003** | ENV-001 §2.2 / DD-003 | — | 旧 OpenCode (`.opencode/opencode.json`) の廃止に伴うモデル設定の一元管理方法が未確定 | `config/models.json` および `tools/config_loader.py` を新設し一元管理 | 🟢 解決済み |
| **PM-004** | MULTI-001 §5 | 🟡 中 | 新規衛星を `.project-registry.json` へ手動登録する手順はあるが、CLIツール化されていない | `tools/add-project.py` CLIスクリプトの開発（今後実施予定） | 🟡 未解決・タスク化 |
| **PM-005** | ORCH-001 / DD-003 | 🟡 中 | 旧 ORCH-001 のエラー分類器・再試行上限ロジックと LangGraph ノード遷移のマッピングが未定義 | `OrchestratorState` にエラーカテゴリとカウントを持たせ、LangGraph 条件エッジで判定 | 🟡 未解決・設計中 |
| **PM-006** | MULTI-001 / DD-003 | — | Issue ID フォーマット（カッコ記法 `[EC-001]` vs カッコなし `EC-001`）の表記が全仕様書で不一致 | 内部処理キーおよび正本表記としてはカッコなし `EC-001` に確定・統一 | 🟢 解決済み |
| **PM-007** | DD-003 §3.1 / models.json | 🔴 高 | `config/models.json` の `temperature`, `max_tokens` が `llm_client.py` シグネチャに未結合 | `llm_client.call_llm` に `**kwargs` を受け渡す共通ラッパー仕様を適用 | 🟡 未解決・設計中 |
| **PM-008** | OP-001 §5.1 | — | OS別 (Windows Native vs Linux/WSL2) 自動バッチスクリプト (.ps1 vs .sh) の配置手順が混在 | `scripts/windows/` と `scripts/linux/` にスクリプト配置構造を明確に分離 | 🟢 解決済み |
| **PM-009** | MULTI-001 §2② | 🟡 中 | Issue ID プレフィックス決定ルール、連番4桁化 (`0001`〜`9999`)、およびサブタスク階層化の設計 | プレフィックス策定ルールおよび4桁化・サブタスク表現（例: `EC-0001-1`）の設計策定 | 🟡 今後実施する別タスク |
| **PM-010** | ENV-001 §2.1 / config/models.json | 🔴 高 | ENV-001 §2.1 のモデル記載 (`qwen2.5-coder`, `qwen3:32b`) が現行 `config/models.json` (`gemma4-12b-it`, `gemma-4-py_coder`) と乖離 | ENV-001 §2.1 の役割別推奨モデル記載をユーザー実環境の Gemma 4 系モデルに更新 | 🟡 未解決・要文書修正 |
| **PM-011** | DD-003 §3.1 / ENV-001 §2.2 / config/models.json | 🔴 高 | `llm_client.py` の `MODEL_MAP` がコード内にハードコードされており、`config/models.json` との二重管理 (SSOT 崩壊) が発生している | `llm_client.py` が `config_loader.py` 経由で `models.json` を読み込む設計に変更（PM-007 と連動） | 🟡 未解決・設計中 |
| **PM-012** | BD-002 §5 / scripts/ | 🟡 中 | `git config core.autocrlf input` の強制設定が環境構築スクリプト (`setup_reviewdog.ps1`) に未組み込み | `scripts/windows/setup_reviewdog.ps1` の冒頭に `git config --global core.autocrlf input` を追加 | 🟡 未解決・要スクリプト修正 |
| **PM-013** | DD-003 §4.1 | 🟡 中 | `escalate_node` から呼ぶ `update_task_metadata()` / `record_execution_history()` のシグネチャ・仕様・保存形式が未定義 | 両関数のシグネチャ・引数・戻り値・書き込み先スキーマを DD-003 に追記定義 | 🟡 未解決・設計欠落 |
| **PM-014** | DD-003 §4.1 / OP-001 §3.5 | 🔴 高 | `tasks.md` 内の B7 ブロッカー判定基準 `round:N` メタデータの書式（記載位置・フォーマット）が未定義 | `tasks.md` の Issue メタデータブロック書式 (`round:N`, `max_round:N`) を正式に仕様化 | 🟡 未解決・設計欠落 |
| **PM-015** | BD-002 §5 / scripts/windows/ | 🟠 中低 | PowerShell の UTF-8 強制設定 (`$OutputEncoding`) の適用タイミング・対象スコープが未規定 (`$PROFILE` への追記 vs スクリプト内設定) | `$PROFILE` への追記を正本手順とし、`scripts/windows/setup_reviewdog.ps1` 末尾に確認ステップを追加 | 🟡 未解決・要手順規定 |

---

## 3. 詳細説明と今後の対応計画

### PM-006: Issue ID 正本表記 (`EC-001`) への統一
* **対応内容**: システム内部キーおよび仕様書上の標準表記をカッコなしの `EC-001` に統一決定。表示上のカッコ `[EC-001]` は `tasks.md` 等のレンダリング時の表現としてのみ許容する。

### PM-008: OS別スクリプト配置構造の分離完了
* **対応内容**: `scripts/windows/setup_reviewdog.ps1` および `scripts/linux/setup_reviewdog.sh` へディレクトリ配置構造を明確に分離。

### PM-009: Issue ID スキーマ拡張（4桁化・サブタスク階層化・プレフィックス策定）
* **背景**: タスク数の増加（`001`〜`999` の上限超過）および複雑な親枝・子枝タスクの管理ニーズ。
* **検討項目**:
  1. プレフィックス命名決定ルールの標準化。
  2. 連番表記の 4 桁化 (`0001` 〜 `9999`)。
  3. サブタスク（例: `EC-0001-1` または `EC-0001-A`）のデータ構造・依存関係定義。

### PM-010: ENV-001 のモデル記載を現行 Gemma 4 系環境に更新
* **背景**: ENV-001 §2.1 は `qwen` 系モデルを前提として記載されているが、ユーザー実環境のローカル Ollama モデルは `gemma4-12b-it-Q4_K_M` (汎用) / `gemma-4-py_coder` (Code) に変更済み。
* **対応計画**: ENV-001 §2.1 の役割別推奨モデル表・`MODEL_MAP` コードサンプルを Gemma 4 系に更新。

### PM-011: `llm_client.py` の MODEL_MAP ハードコード廃止と `models.json` への一本化
* **背景**: 現状は `llm_client.py` 内の `MODEL_MAP` と `config/models.json` の 2 箇所を手動で同期する必要がある。
* **対応計画**: PM-007 のハイパーパラメータ結合設計と並行して、`llm_client.py` の初期化時に `config_loader.get_model_name()` を呼び出すよう変更する。

### PM-013: `escalate_node` 補助関数のシグネチャ定義追記
* **背景**: `update_task_metadata(project_path, issue_id, round_num)` および `record_execution_history(state, final_status, actual_round)` という呼び出しが仕様書コードサンプルに存在するが、その実装仕様が宙に浮いている。
* **対応計画**: DD-003 §4.1 の末尾に両関数のシグネチャ・引数・戻り値・`tasks.md` への書き込みフォーマットを追記定義する。

### PM-014: `tasks.md` の B7 ブロッカー判定メタデータ書式の仕様化
* **背景**: `tasks.md` のどの位置（例: Issue チェックボックス直下のコメント行）に `round:3` を記載するかが未定義であり、`check-blockers.py` のパース処理が設計できない。
* **対応計画**: 以下の書式を正本として確定し、DD-003 §4.1 および OP-001 §3 に記載する。
  ```markdown
  - [ ] EC-012: 決済例外処理ロールバックハンドラ
    <!-- round:3 max_round:3 status:FAILED_B7 -->
  ```

---

## 4. 改訂履歴
- **2026/07/29 (Rev.1.4)**: 横断的仕様書精査により新たに発見した設計上の懸念点 6 件 (PM-010〜PM-015) を追加。重要度列をマトリクスに追加。
- **2026/07/29 (Rev.1.3)**: PM-006 (`EC-001` 統一) および PM-008 (OS別配置構造分離) を解決済みに更新。新規検討タスク PM-009 (4桁化・サブタスク・プレフィックスルール) を追記。
- **2026/07/29 (Rev.1.2)**: 潜在的な仕様・設計レベルの課題 4 件 (PM-005〜PM-008) を追加。
- **2026/07/29 (Rev.1.1)**: 旧障害記録スクリプト (record-failure.py) に関する検討項目を削除。
- **2026/07/29 (Rev.1.0)**: 初版作成。

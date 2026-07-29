# 課題・矛盾点一覧 (Problem Management) Rev.1.8

文書番号: SBOS-PM-005  
版数: Rev.1.8  
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
| **PM-007** | DD-003 §3.1 / models.json | 🟢 | `config/models.json` の `temperature`, `max_tokens` (35000) を LiteLLM 呼び出しへ動的結合 | `tools/llm_client.py` 経由で `get_model_params` を呼び出し `litellm.completion` へ完全結合・検証完了 | 🟢 解決済み |
| **PM-008** | OP-001 §5.1 | 🟢 | OS別 (Windows Native vs Linux/WSL2) 自動バッチスクリプト (.ps1 vs .sh) の配置手順が混在 | `scripts/windows/` と `scripts/linux/` にスクリプト配置構造を明確に分離 | 🟢 解決済み |
| **PM-009** | MULTI-001 §2② | 🟡 中 | Issue ID プレフィックス決定ルール、連番4桁化 (`0001`〜`9999`)、およびサブタスク階層化の設計 | プレフィックス策定ルールおよび4桁化・サブタスク表現（例: `EC-0001-1`）の設計策定 | 🟡 今後実施する別タスク |
| **PM-010** | ENV-001 §2.1 / config/models.json | 🟢 | ENV-001 §2.1 のモデル記載 (`qwen` 系) が現行 `config/models.json` と乖離していた | モデル定義を `config/models.json` に一元管理し、仕様書内の特定モデル名直書きを排除・参照統一 | 🟢 解決済み |
| **PM-011** | DD-003 §3.1 / ENV-001 §2.2 / config/models.json | 🟢 | `llm_client.py` の `MODEL_MAP` ハードコードによる二重管理 (SSOT 崩壊) | `tools/llm_client.py` 内で `config_loader` を参照しモデル名を動的取得（PM-007 と同時統合完了） | 🟢 解決済み |
| **PM-012** | BD-002 §5 / scripts/ | 🟢 | `git config core.autocrlf input` の強制設定が環境構築スクリプトに未組み込みであった | `scripts/windows/setup_reviewdog.ps1` の冒頭に `git config --global core.autocrlf input` 組み込み完了 | 🟢 解決済み |
| **PM-013** | DD-003 §4.1 | 🟢 | `escalate_node` から呼ぶ `update_task_metadata()` / `record_execution_history()` のシグネチャ・仕様が未定義 | DD-003 §4.1.1 を新設し、関数契約・`history_path` スキーマを正式追記定義 | 🟢 解決済み |
| **PM-014** | DD-003 §4.1 / OP-001 §3.5 | 🟢 | `tasks.md` 内の B7 ブロッカー判定メタデータ書式が未定義であった | `tasks.md` 内 Issue 直下の `<!-- round:N max_round:N status:STATUS -->` タグ形式に確定し OP-001 に統一手順反映 | 🟢 解決済み |
| **PM-015** | BD-002 §5 / ENV-001 §5.1 / scripts/windows/ | 🟢 | PowerShell UTF-8 設定 (`$OutputEncoding`) の適用タイミングおよび対象スコープが未規定であった | ENV-001 §5.1 で `$PROFILE` 永続設定手順を正本化。`setup_reviewdog.ps1` を非変更確認モードに改修 | 🟢 解決済み |

---

## 3. 詳細説明と今後の対応計画

### PM-006: Issue ID 正本表記 (`EC-001`) への統一
* **対応内容**: システム内部キーおよび仕様書上の標準表記をカッコなしの `EC-001` に統一決定。表示上のカッコ `[EC-001]` は `tasks.md` 等のレンダリング時の表現としてのみ許容する。

### PM-007 & PM-011: `models.json` ハイパーパラメータ (`max_tokens: 35000`) 動的結合および二重管理 (SSOT 崩壊) の解消
* **対応内容**: `config/models.json` にて全モデルの `max_tokens` を `35000` に設定更新。`tools/config_loader.py` に `get_model_params()` を追加し、`tools/llm_client.py` 経由で LiteLLM (`litellm.completion`) へモデル名・`temperature`・`max_tokens` を動的自動結合する実装を完了。二重管理・不一致問題を完全に解消。

### PM-008: OS別スクリプト配置構造の分離完了
* **対応内容**: `scripts/windows/setup_reviewdog.ps1` および `scripts/linux/setup_reviewdog.sh` へディレクトリ配置構造を明確に分離。

### PM-009: Issue ID スキーマ拡張（4桁化・サブタスク階層化・プレフィックス策定）
* **背景**: タスク数の増加（`001`〜`999` の上限超過）および複雑な親枝・子枝タスクの管理ニーズ。
* **検討項目**:
  1. プレフィックス命名決定ルールの標準化。
  2. 連番表記の 4 桁化 (`0001` 〜 `9999`)。
  3. サブタスク（例: `EC-0001-1` または `EC-0001-A`）のデータ構造・依存関係定義。

### PM-010: ドキュメント内モデル名直書きの排除と `config/models.json` 一元管理化
* **対応内容**: ドキュメント（SBOS-ENV-001 等）およびモジュール内における特定モデル名の直書き・ハードコードを廃止。モデル定義は `config/models.json` にて一元管理（SSOT）し、ドキュメント上は役割定義 (`planner`, `coder`, `reviewer`, `aider`) および参照形式へと統一完了。

### PM-012: スクリプト内への `git config core.autocrlf input` 自動設定の組み込み
* **対応内容**: Windows Native 環境での Aider 改行コードバグ対策として、`scripts/windows/setup_reviewdog.ps1` の実行プロセス冒頭に `git config --global core.autocrlf input` の自動設定処理を組み込み完了。

### PM-013 & PM-014: `escalate_node` 補助関数契約、実行履歴スキーマ、および B7 メタデータ正本書式の定義
* **対応内容**:
  1. `DD-003 §4.1.1` を新設し、`update_task_metadata()` および `record_execution_history()` の関数シグネチャ・`history_path` (`tools/.cache/execution_history.json`) JSON スキーマを追記定義。
  2. `tasks.md` 内の Issue 直下の `<!-- round:N max_round:N status:STATUS -->` タグを B7 判定メタデータの正本書式として確定。
  3. `OP-001` ケース5 に、`max_round` を変えずに `round:0 status:PENDING` に手動リセットして復旧・再起動する運用手順を反映完了。

### PM-015: PowerShell UTF-8 永続設定手順の正本化とスクリプト改修
* **対応内容**:
  1. `ENV-001 §5.1` で `$PROFILE` への UTF-8 永続設定手順（重複しないアトミック追記ワンライナー）と新規セッションでの確認コマンド (`$OutputEncoding.EncodingName`) を正本化。
  2. `scripts/windows/setup_reviewdog.ps1` は `$PROFILE` を直接変更せず、設定の有無を点検して未設定時に案内コードを出力する安全な非変更モードへ改修。
  3. `docs/setup/reviewdog_setup_guide.md` の記述・パスを最新のスクリプト構造と UTF-8 導線に合わせて修正。

---

## 4. 改訂履歴
- **2026/07/29 (Rev.1.8)**: PM-013 (補助関数契約/履歴スキーマ), PM-014 (B7メタデータ正本書式/復旧手順), PM-015 (PowerShell UTF-8 $PROFILE 永続設定正本化/setup_reviewdog.ps1非変更確認化) をすべて解決済みに更新。
- **2026/07/29 (Rev.1.7)**: PM-007 (max_tokens: 35000 結合) および PM-011 (llm_client.py ハードコード完全削除) を解決済みに更新。
- **2026/07/29 (Rev.1.6)**: PM-012 (setup_reviewdog.ps1 への git autocrlf input 自動設定組み込み) を解決済みに更新。
- **2026/07/29 (Rev.1.5)**: PM-010 (モデルのドキュメント直書き排除・config/models.json 一元管理参照化) を解決済みに更新。
- **2026/07/29 (Rev.1.4)**: 横断的仕様書精査により新たに発見した設計上の懸念点 6 件 (PM-010〜PM-015) を追加。
- **2026/07/29 (Rev.1.3)**: PM-006 (`EC-001` 統一) および PM-008 (OS別配置構造分離) を解決済みに更新。新規検討タスク PM-009 (4桁化・サブタスク) を追記。
- **2026/07/29 (Rev.1.2)**: 潜在的な仕様・設計レベルの課題 4 件 (PM-005〜PM-008) を追加。
- **2026/07/29 (Rev.1.1)**: 旧障害記録スクリプト (record-failure.py) に関する検討項目を削除。
- **2026/07/29 (Rev.1.0)**: 初版作成。

# 課題・矛盾点一覧 (Problem Management) Rev.2.5

文書番号: SBOS-PM-005  
版数: Rev.2.5  
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
| **PM-005** | ORCH-001 / DD-003 | 🟢 | 旧 ORCH-001 のエラー分類器・再試行上限ロジックと LangGraph ノード遷移のマッピングが未定義 | `OrchestratorState` に `error_category` を持たせ、DD-003 §2.1 / §4 に条件エッジ判定とマッピングを規定完了 | 🟢 解決済み |
| **PM-006** | MULTI-001 / DD-003 | — | Issue ID フォーマット（カッコ記法 `[EC-001]` vs カッコなし `EC-001`）の表記が全仕様書で不一致 | 内部処理キーおよび正本表記としてはカッコなし `EC-001` に確定・統一 | 🟢 解決済み |
| **PM-007** | DD-003 §3.1 / models.json | 🟢 | `config/models.json` の `temperature`, `max_tokens` (35000) を LiteLLM 呼び出しへ動的結合 | `tools/llm_client.py` 経由で `get_model_params` を呼び出し `litellm.completion` へ完全結合・検証完了 | 🟢 解決済み |
| **PM-008** | OP-001 §5.1 | 🟢 | OS別 (Windows Native vs Linux/WSL2) 自動バッチスクリプト (.ps1 vs .sh) の配置手順が混在 | `scripts/windows/` と `scripts/linux/` にスクリプト配置構造を明確に分離 | 🟢 解決済み |
| **PM-009** | MULTI-001 §2② | 🟢 | Issue ID プレフィックス決定ルール、連番4桁化 (`0001`〜`9999`)、およびサブタスク階層化の設計 | SBOS-MULTI-001 §2② に連番4桁、サブタスク ID (A〜Z) 表記およびオーバーフロー時のタスク分解運用原則を規定・確定 | 🟢 解決済み |
| **PM-010** | ENV-001 §2.1 / config/models.json | 🟢 | ENV-001 §2.1 のモデル記載 (`qwen` 系) が現行 `config/models.json` と乖離していた | モデル定義を `config/models.json` に一元管理し、仕様書内の特定モデル名直書きを排除・参照統一 | 🟢 解決済み |
| **PM-011** | DD-003 §3.1 / ENV-001 §2.2 / config/models.json | 🟢 | `llm_client.py` の `MODEL_MAP` ハードコードによる二重管理 (SSOT 崩壊) | `tools/llm_client.py` 内で `config_loader` を参照しモデル名を動的取得（PM-007 と同時統合完了） | 🟢 解決済み |
| **PM-012** | BD-002 §5 / scripts/ | 🟢 | `git config core.autocrlf input` の強制設定が環境構築スクリプトに未組み込みであった | `scripts/windows/setup_reviewdog.ps1` の冒頭に `git config --global core.autocrlf input` 組み込み完了 | 🟢 解決済み |
| **PM-013** | DD-003 §4.1 | 🟢 | `escalate_node` から呼ぶ `update_task_metadata()` / `record_execution_history()` のシグネチャ・仕様が未定義 | DD-003 §4.1.1 を新設し、関数契約・`history_path` スキーマを正式追記定義 | 🟢 解決済み |
| **PM-014** | DD-003 §4.1 / OP-001 §3.5 | 🟢 | `tasks.md` 内の B7 ブロッカー判定メタデータ書式が未定義であった | `tasks.md` 内 Issue 直下の `<!-- round:N max_round:N status:STATUS -->` タグ形式に確定し OP-001 に統一手順反映 | 🟢 解決済み |
| **PM-015** | BD-002 §5 / ENV-001 §5.1 / scripts/windows/ | 🟢 | PowerShell UTF-8 設定 (`$OutputEncoding`) の適用タイミングおよび対象スコープが未規定であった | ENV-001 §5.1 で `$PROFILE` 永続設定手順を正本化。`setup_reviewdog.ps1` を非変更確認モードに改修 | 🟢 解決済み |
| **PM-016** | README / ENV-001 / OP-001 | 🔴 高 | オーケストレーター／スコアリング関連コード (`orchestrator_graph.py`, `score-issues.py` 等) が `tools/` に未存在 | 今後のモジュール実装フェーズにて `tools/` 配下へ段階的に実装予定 | 🟡 未解決・コード実装対象 |
| **PM-017** | README / DD-003 / OP-001 | 🟢 | README の CLI 例文 (`--auto`) が詳細・運用設計書 (`orchestrate` / `execute`) と不一致 | README.md の CLI 案内コマンドを `orchestrate` / `execute --issue-id` に修整完了 | 🟢 解決済み |
| **PM-018** | docs/setup/ | 🟢 | 依存管理方式のドキュメント記述が 3 系統に分裂 (`dependency_management.md` / `toml_project_setup.md`) | ドキュメントを現行の `pyproject.toml` + `uv` 仕様に完全統一・修整完了 | 🟢 解決済み |
| **PM-019** | pyproject.toml / docs/ | 🟢 | `uv sync` 後の品質確認・開発依存関係 (`ruff`, `pytest`, `pip-licenses` 等) が不足 | `pyproject.toml` に開発用依存パッケージを追加し `uv sync --extra dev` で一括正常化完了 | 🟢 解決済み |
| **PM-020** | reviewdog_setup_guide.md / ENV-001 | 🟢 | Reviewdog セットアップおよび検証手順コマンドが OS 別実スクリプト動作と不一致 | ガイドおよび ENV-001 の検証コマンドを Linux/Windows それぞれの実体へ修整完了 | 🟢 解決済み |
| **PM-021** | ENV-001 §2.2 / config/models.json | 🟢 | ENV-001 の `models.json` 構成サンプルが `config_loader.py` の実キー (`model_name` 等) と非互換 | ENV-001 §2.2 の JSON 構成例を `model_name`, `temperature`, `max_tokens` の実スキーマに修整完了 | 🟢 解決済み |
| **PM-022** | DD-003 §3.2 / tools/aider_runner.py | 🟢 | DD-003 の `run_aider` API 引数契約・戻り値型が実物 `tools/aider_runner.py` と非互換 | DD-003 §3.2 のコードサンプルを実物 `run_aider(instruction, target_files, model, cwd)` 仕様に修整完了 | 🟢 解決済み |
| **PM-023** | README / docs/ | 🟢 | 絶対 `file:///` リンクが特定環境パス (`c:/Users/xzyoi/...`) を指しリンク切れリスク | ドキュメント内の絶対 `file:///` リンクを標準的な相対パスリンク `[text](relative/path)` へ変換完了 | 🟢 解決済み |
| **PM-024** | oss_license_policy.md / models.json | 🟢 | ライセンスポリシー文書 (`oss_license_policy.md`) の利用中モデル表記が旧 Qwen 系のまま不一致 | `oss_license_policy.md` のモデル記載を現行の Gemma 4 系 (Gemma 4 12B IT, Gemma 4 Py Coder) へ修整完了 | 🟢 解決済み |
| **PM-025** | 全設計書 (BD/ORCH/ENV/OP/MULTI) | 🟢 | 設計書間の関連文書欄および本文中の他ドキュメント Rev バージョン表記の乖離 | 全設計書のヘッダー・関連文書欄の Rev 表記を最新確定バージョンへ一括整合修整完了 | 🟢 解決済み |
| **PM-026** | MULTI-001 / DD-003 | 🟢 | 衛星リポジトリ内への `project.json` / `tasks.md` 配置による衛星コードベース汚染 | 母艦側 `metadata/projects/<project-key>/` 階層へメタデータを引き上げ管理する構成へ移行完了 | 🟢 解決済み |
| **PM-027** | MULTI-001 / .gitignore | 🟢 | `projects/` ディレクトリ内部の安全かつ完全な Git 除外・遮断ルールの確立 | 台帳を `metadata/.project-registry.json` に配置転換し `.gitignore` で `projects/*` を完全除外設定完了 | 🟢 解決済み |
| **PM-028** | MULTI-001 §2④ / §4 | 🔴 高 | 台帳 `metadata/.project-registry.json` のネスト構造 (`projects`) と `score-issues.py` 概念パースコードの不一致 | `SBOS-MULTI-001 §2④` の概念コードを `registry.get("projects", {})` でネスト解釈する実装へ統一修整完了 | 🟢 解決済み |
| **PM-029** | BD-002 §4.1 | 🟠 中 | BD-002 §4.1 に旧 `.gitignore` 記述 (`!/projects/.project-registry.json`) が残存 | BD-002 §4.1 の記述を PM-027 確定後の完全遮断ルール (`/projects/*`, `/projects/.*`, `!.gitignore`) へ更新修整完了 | 🟢 解決済み |
| **PM-030** | ENV-001 Step 2 / §7 | 🟠 中 | ENV-001 の Step 2 および §7 診断スクリプト内台帳パスが旧パス (`projects/.project-registry.json`) のまま残存 | ENV-001 Step 2 および §7 診断スクリプト内台帳パスを `metadata/.project-registry.json` へ追従修整完了 | 🟢 解決済み |
| **PM-031** | 全設計書 (BD/DD/ORCH/ENV/OP/MULTI/PM) | 🟡 低 | 関連文書ヘッダーの Rev 表記が過去版数のまま一部未追従 | 全 7 設計書の関連文書ヘッダー版数表記を最新確定 Rev (BD Rev.4.5, DD Rev.4.6, ORCH Rev.3.3, ENV Rev.4.4, OP Rev.4.3, MULTI Rev.2.4, PM Rev.2.5) に完全整合統一完了 | 🟢 解決済み |
| **PM-032** | DD-003 §2, §3.2, §4.1.1 / tools/ | 🟡 低 | DD-003 の `Optional` インポート漏れ、`tools/aider_runner.py` 内 `get_git_diff()` 未存在、マッピング未明記 | Typing 修正、`aider_runner.py` へ `get_git_diff()` 本実装 & テスト追加、`round` → `review_round` マッピング注記を追記完了 | 🟢 解決済み |

---

### PM-005: エラー分類器および LangGraph ノード遷移マッピングの明確化
* **対応内容**: `SBOS-DD-003 §2.1` および §4 にて、`OrchestratorState` に `error_category` フィールド（`"LINT_ERROR"`, `"TEST_ERROR"`, `"REVIEW_REJECTED"`, `"LLM_TIMEOUT"`, `"SYSTEM_ERROR"`）を明示。各ノードの実行結果に基づく分類マッピングおよび `route_after_lint`, `route_after_test`, `route_after_review` のルーティング関数判定条件を規定・完了。

### PM-006: Issue ID 正本表記 (`EC-001`) への統一
* **対応内容**: システム内部キーおよび仕様書上の標準表記をカッコなしの `EC-001` に統一決定。表示上のカッコ `[EC-001]` は `tasks.md` 等のレンダリング時の表現としてのみ許容する。

### PM-007 & PM-011: `models.json` ハイパーパラメータ (`max_tokens: 35000`) 動的結合および二重管理 (SSOT 崩壊) の解消
* **対応内容**: `config/models.json` にて全モデルの `max_tokens` を `35000` に設定更新。`tools/config_loader.py` に `get_model_params()` を追加し、`tools/llm_client.py` 経由で LiteLLM (`litellm.completion`) へモデル名・`temperature`・`max_tokens` を動的自動結合する実装を完了。二重管理・不一致問題を完全に解消。

### PM-008: OS別スクリプト配置構造の分離完了
* **対応内容**: `scripts/windows/setup_reviewdog.ps1` および `scripts/linux/setup_reviewdog.sh` へディレクトリ配置構造を明確に分離。

### PM-009: Issue ID スキーマ拡張（4桁化・サブタスク A〜Z 階層化・タスク分解原則の規定）
* **対応内容**: `SBOS-MULTI-001 §2②` にて以下を正式な拡張仕様として規定・確定完了。
  1. **親タスク**: `[PROJECT_KEY]-[4桁連番]` （例: `EC-0001`）
  2. **サブタスク**: `[PROJECT_KEY]-[4桁連番]-[A-Z]` （例: `EC-0001-A`〜`EC-0001-Z`）
  3. **タスク分解原則**: サブタスクが `Z`（26個）を超える複雑なタスクは要件定義・タスク分解段階で独立した親タスクへ分割するか先行実装部を切り出して新規追加する運用ルールを策定。

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

### PM-026: 衛星メタデータ (`project.json`, `tasks.md`) の母艦階層分離設計
* **背景・動機**: 衛星プロダクト直下に `project.json` や `tasks.md` を配置すると、衛星ソースリポジトリの Git ログやコードツリーが汚染される。
* **解決案（`metadata/projects/<project-key>/` 階層管理）**:
  * 母艦側に `metadata/projects/` ディレクトリを新設。
  * `metadata/projects/EC/project.json` および `metadata/projects/EC/tasks.md` のように、プロジェクトキーごとの専用フォルダで一括管理。
* **検討項目・懸念点**:
  1. 汎用ファイル名の衝突回避: `metadata/projects/<KEY>/` 構造により解決。
  2. スコアリング・オーケストレーターのパス解決ロジック修正。
  3. Aider 実行作業ディレクトリ (`cwd`) とメタデータ更新パスの分離維持。

### PM-027: `projects/` ディレクトリ内部の完全 Git 管理除外設計
* **背景・動機**: 母艦リポジトリ (`second-brain-graph`) から `projects/` 内部の全コード・Git 履歴を完全に遮断・分断する。
* **解決案（中央台帳の移動と除外ルールの単純化）**:
  * 中央台帳 `.project-registry.json` を `projects/` 直下から `metadata/.project-registry.json` へ移動。
  * 母艦の `.gitignore` を `/projects/*` および `/projects/.*` の完全遮断ルールに簡略化。
* **検討項目・懸念点**:
  1. 空ディレクトリ保持 (`projects/.gitkeep`) または環境構築時の自動ディレクトリ生成。
  2. 開発者が新規マシン構築時の衛星クローン手順の明確化。

---

## 4. 改訂履歴
- **2026/07/29 (Rev.2.5)**: PM-028 (台帳ネスト構造パース整合), PM-029 (.gitignore 旧記述修整), PM-030 (ENV-001 台帳パス追従), PM-031 (全設計書 Rev 統一), PM-032 (DD-003 Typing & get_git_diff 契約 & マッピング明記) をすべて解決済みに更新。
- **2026/07/29 (Rev.2.4)**: PM-026 (衛星メタデータの母艦階層分離) および PM-027 (projects/ 完全 Git 遮断) の設計確定・反映完了に伴い解決済みに更新。
- **2026/07/29 (Rev.2.3)**: PM-005 (OrchestratorState への error_category 追加および LangGraph 条件付きエッジマッピング) を確定し解決済みに更新。
- **2026/07/29 (Rev.2.2)**: PM-009 (Issue ID 4桁化、サブタスク ID A〜Z 表記およびオーバーフロー時の分解原則) を確定し解決済みに更新。
- **2026/07/29 (Rev.2.1)**: 新規課題 PM-026 (衛星メタデータの母艦階層分離) および PM-027 (projects/ 完全 Git 除外) を追加登録。
- **2026/07/29 (Rev.2.0)**: 横断的不一致課題 (PM-017〜PM-025) のドキュメント・設定修整完了に伴いステータスを解決済みに更新。
- **2026/07/29 (Rev.1.9)**: リポジトリ全体の整合性検証により抽出された課題 10 件 (PM-016〜PM-025) を追加登録。
- **2026/07/29 (Rev.1.8)**: PM-013 (補助関数契約/履歴スキーマ), PM-014 (B7メタデータ正本書式/復旧手順), PM-015 (PowerShell UTF-8 $PROFILE 永続設定正本化/setup_reviewdog.ps1非変更確認化) をすべて解決済みに更新。
- **2026/07/29 (Rev.1.7)**: PM-007 (max_tokens: 35000 結合) および PM-011 (llm_client.py ハードコード完全削除) を解決済みに更新。
- **2026/07/29 (Rev.1.6)**: PM-012 (setup_reviewdog.ps1 への git autocrlf input 自動設定組み込み) を解決済みに更新。
- **2026/07/29 (Rev.1.5)**: PM-010 (モデルのドキュメント直書き排除・config/models.json 一元管理参照化) を解決済みに更新。
- **2026/07/29 (Rev.1.4)**: 横断的仕様書精査により新たに発見した設計上の懸念点 6 件 (PM-010〜PM-015) を追加。
- **2026/07/29 (Rev.1.3)**: PM-006 (`EC-001` 統一) および PM-008 (OS別配置構造分離) を解決済みに更新。新規検討タスク PM-009 (4桁化・サブタスク) を追記。
- **2026/07/29 (Rev.1.2)**: 潜在的な仕様・設計レベルの課題 4 件 (PM-005〜PM-008) を追加。
- **2026/07/29 (Rev.1.1)**: 旧障害記録スクリプト (record-failure.py) に関する検討項目を削除。
- **2026/07/29 (Rev.1.0)**: 初版作成。

# 課題・矛盾点一覧 (Problem Management) Rev.2.14

文書番号: SBOS-PM-005  
版数: Rev.2.14（PM-050: Ollama/llama-server バックエンド混在課題の追加）
改訂日: 2026年7月30日  
作成日: 2026年6月25日  
対象読者: 全開発・運用メンバー  
関連文書: SBOS-BD-002, SBOS-DD-003, SBOS-ORCH-001, SBOS-ENV-001, SBOS-OP-001, SBOS-MULTI-001  

---

## 更新履歴
- **2026/07/30 (Rev.2.14)**: 新規課題 PM-050 (LLMバックエンドの混在: Ollama vs llama-server) を追加登録。
- **2026/07/30 (Rev.2.13)**: PM-041〜PM-049の設計反映作業を完了し、ステータスを解決済みに更新（`state.json` の正本化、ロック等例外固定ルールの導入、Git復旧安全化など）。SBOS-DD-003, SBOS-ORCH-001, SBOS-ENV-001, SBOS-OP-001, SBOS-MULTI-001  
- **2026/07/29 (Rev.2.12)**: PM-036〜PM-038の対応完了、PM-039〜040は継続課題として整理

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
| **PM-013** | DD-003 §4.1 | 🟢 | `escalate_node` から呼ぶ `update_task_state()` / `record_execution_history()` のシグネチャ・仕様が未定義 | DD-003 §4.1.1 を新設し、関数契約・`history_path` スキーマを `state.json` 対応で正式追記定義 | 🟢 解決済み |
| **PM-014** | DD-003 §4.1 / OP-001 §3.5 | 🟢 | `tasks.md` 内の B7 ブロッカー判定メタデータ書式が未定義であった | B7状態管理を `state.json` へ一本化し、`tasks.md` のメタデータ埋め込みを廃止するよう設計変更 | 🟢 解決済み |
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
| **PM-030** | ENV-001 Step 2 / §7 | 🟠 中 | ENV-001 の Step 2 (`.gitignore` ヒアドキュメント / 台帳作成) および §7 診断スクリプト内台帳パスが旧仕様のまま残存 | ENV-001 Step 2 の `.gitignore` 生成スクリプト、台帳初期化コード、および §7 診断スクリプトのパスを正本ルールへ完全追従修整完了 | 🟢 解決済み |
| **PM-031** | 全設計書 (BD/DD/ORCH/ENV/OP/MULTI/PM) | 🟡 低 | 関連文書ヘッダーの Rev 表記が過去版数のまま一部未追従 | 全 7 設計書の関連文書ヘッダー版数表記を最新確定 Rev (BD Rev.4.6, DD Rev.4.8, ORCH Rev.3.5, ENV Rev.4.6, OP Rev.4.5, MULTI Rev.2.6, PM Rev.2.7) に完全整合統一完了 | 🟢 解決済み |
| **PM-032** | DD-003 §2, §3.2, §4.1.1 / tools/ | 🟡 低 | DD-003 の `Optional` インポート漏れ、`tools/aider_runner.py` 内 `get_git_diff()` 未存在、マッピング未明記 | Typing 修正、`aider_runner.py` へ `get_git_diff()` 本実装 & テスト追加、`round` → `review_round` マッピング注記を追記完了 | 🟢 解決済み |
| **PM-033** | MULTI-001 §5 Step 4 | 🟠 中 | MULTI-001 §5 Step 4 の登録確認コマンドが旧台帳パス (`projects/.project-registry.json`) のまま残存 | Step 4 の確認コマンドパスを `metadata/.project-registry.json` に修整完了 | 🟢 解決済み |
| **PM-034** | BD-002 ヘッダー | 🟡 低 | BD-002 ヘッダーの関連文書表記で `SBOS-MULTI-001 Rev.2.4）` と開き括弧が欠落していたタイポ | `SBOS-MULTI-001（差分設計書 Rev.2.6）` へ正確に修整完了 | 🟢 解決済み |
| **PM-035** | DD-003 §4.1.1 / OP-001 §2.1, §3.5 | 🟠 中 | `execution_history.json` 内レビュー指摘履歴構造の記述 (OP-001 §2.1) と正本 JSON スキーマ例 (DD-003 §4.1.1) の不一致 | `DD-003 §4.1.1` の正本 JSON スキーマ例に `review_rounds: [{round, verdict, comments}]` 履歴配列構造を追加定義し `OP-001 §2.1` および §3.5 の全記述と三者完全統合完了 | 🟢 解決済み |
| **PM-036** | BD-002 / DD-003 / ORCH-001 / MULTI-001 | 🟢 | 手動コミットから `develop` 基準の自動ブランチ作成および PR 自動作成運用への方針転換と Git 操作の厳格化 | 1. 派生元 `develop` / ターゲット `develop` の固定 (`gh pr create`) <br> 2. `escalate_node` での安全停止と差分保持 <br> 3. メタデータへの `base_branch` 追加 | 🟢 解決済み |
| **PM-037** | DD-003 / OP-001 | 🟢 | 衛星リポジトリの「排他制御（ロック機構）」の欠如。複数タスク同時実行時のワーキングツリー競合リスク | `plan_node` 前に `.lock` 機構を導入。取得失敗時は待機せず即時スキップ (`SKIPPED_LOCKED`) するようルール化 | 🟢 解決済み |
| **PM-038** | DD-003 / OP-001 / MULTI-001 | 🟢 | `tasks.md` へのシステム状態埋め込み（HTMLコメント）による脆弱性とB7管理の煩雑さ | システム状態を `metadata/projects/<PROJECT_KEY>/state.json` へ分離・SSOT化し、tasks.mdのHTMLコメントを廃止 | 🟢 解決済み |
| **PM-039** | DD-003 / OP-001 | 🟠 中 | 依存解決度（D）のスコア計算における先行タスク未完了（ブロッカーあり）Issueの「実行除外漏れ」リスク | `score-issues.py` 内でブロッカーを持つIssueはスコア計算前に除外（Drop）するハードリミットを実装 | 🟡 未解決・タスク化 |
| **PM-040** | DD-003 / ORCH-001 | 🔴 高 | 完全ローカル環境（max_tokens: 35000）におけるコンテキストウィンドウ枯渇および既存コード文脈の欠落リスク | `plan_node` 前にベクトル検索（RAG）やAST解析を用いた Context Fetching ノードを追加し関連ファイルを動的抽出 | 🟡 未解決・タスク化 |
| **PM-041** | 複数設計書横断 | 🟢 | 台帳・メタデータの正本パスが二重定義（`metadata/` vs 衛星直下） | `metadata/` を唯一の正本として文書体系全体で統一し、README等の旧配置情報を更新 | 🟢 解決済み |
| **PM-042** | DD-003 / ORCH | 🟢 | B7ブロッカー判定の履歴スキーマが新旧設計書間で非互換（安全回路不成立） | B7判定を `state.json` の `status == "FAILED_B7"` に完全一本化し、DD-003のスキーマ定義を更新 | 🟢 解決済み |
| **PM-043** | ORCH / DD | 🟢 | LLMタイムアウト・システム例外時の状態遷移契約の不足 | LLMタイムアウトは1回再試行後 `FAILED_SYSTEM`、他例外は即時 `FAILED_SYSTEM` となるようDD-003状態遷移表に追加 | 🟢 解決済み |
| **PM-044** | OP-001 / ORCH | 🟢 | 破壊的なGit復旧に対する保全・復元方針の欠如 | `git clean -fd` 等の破壊的操作をドキュメントから削除し、B7・例外時は差分保持・停止・人間確認運用へ変更 | 🟢 解決済み |
| **PM-045** | ORCH / BD | 🟢 | 自動ブランチ・PR運用が正常系のみで異常系状態の定義不足 | PR失敗時は作業ブランチ・差分を保持して停止 (`PR_FAILED`) するようDD-003の状態遷移ルールへ追加 | 🟢 解決済み |
| **PM-046** | DD / ORCH | 🟢 | 同一衛星への並行実行を扱う排他制御の契約未完成（PM-037関連） | ロック取得失敗時は待機せず即時スキップし `SKIPPED_LOCKED` となるようDD-003にルール明記 | 🟢 解決済み |
| **PM-047** | ENV-001 / DD | 🟢 | モデル設定SSOTとフォールバック方針の矛盾 | DD-003に残存していた直書きモデル名を廃止し、`models.json` フォールバック先例示へと一元化 | 🟢 解決済み |
| **PM-048** | 全文書横断 | 🟢 | 文書間の版数参照が現行版と不一致 | 本文・関連文書欄の他文書固定版数参照を削除し文書番号のみの参照へ統一 | 🟢 解決済み |
| **PM-049** | ORCH | 🟢 | 旧ORCH文書の位置付けが不明瞭（現行仕様との混同リスク） | `SBOS-ORCH-001.md` 各節に「非規範・参考資料」のアラートを追記し、正本は DD-003 である旨を明記 | 🟢 解決済み |
| **PM-050** | DD / ORCH | 🟠 中 | Ollama (localhost:11434) と llama-server (localhost:8080) のLLMバックエンド接続経路・起動方針が混在している | `BackendExecutionCoordinator` を導入し、推論目的（intent）に応じた排他併用（Exclusive Co-usage）アーキテクチャへ移行 | 🟢 解決済み |

---

### PM-005: エラー分類器および LangGraph ノード遷移マッピングの明確化
* **対応内容**: `SBOS-DD-003 §2.1` および §4 にて、`OrchestratorState` に `error_category` フィールド（`"LINT_ERROR"`, `"TEST_ERROR"`, `"REVIEW_REJECTED"`, `"LLM_TIMEOUT"`, `"SYSTEM_ERROR"`, `"LOCKED"`, `"PR_ERROR"` の7分類）を明示。
  * ※ `LOCKED` は即時スキップの `SKIPPED_LOCKED` へ、`PR_ERROR` はブランチ保持停止の `PR_FAILED` へ到達する終端分類である。
  各ノードの実行結果に基づく分類マッピングおよび `route_after_lint`, `route_after_test`, `route_after_review` のルーティング関数判定条件を規定・完了。

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
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
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

### PM-036: `develop` 基準・`main` 非参照の自動ブランチ作成および PR 自動作成運用の策定
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **背景・動機**:
  直接ワーキングツリーのファイルを編集させて人間が手動でコミットする現状の「permissionの維持」運用よりも、エージェントにブランチを切らせて PR (Pull Request) を作成させる方針へ変更。
  `main` ブランチを完全にスコープ外とし、常に `develop` ブランチから派生し、`develop` 宛てに PR を作成することで、本番環境 (`main`) への影響を完全遮断し安全性を高める。
* **具体的な設計方針・改修内容**:
  1. **LangGraph ノードにおける Git 操作の厳格化**:
     `orchestrator_graph.py` 内での自動処理において対象ブランチを `develop` に固定。
     * **作業開始時 (派生元の固定)**: グラフ初期化時または `plan_node` 直前で、衛星リポジトリを必ず `develop` に合わせる (`git checkout develop && git pull origin develop` 後に `git checkout -b sbos/<Issue-ID> develop` を実行)。
     * **`done_node` 到達時 (PR作成先の固定)**: タスク完了し PR を自動作成する際、ターゲット（ベース）ブランチを明示的に指定 (`gh pr create --base develop --head sbos/<Issue-ID> ...`)。
  2. **B7 ブロッカー到達時の安全な退避 (`escalate_node` の改修)**:
     * `escalate_node` に到達してタスクが失敗・中断した場合、実行中の作業ブランチ (`sbos/<Issue-ID>`) での変更を破棄または退避したのち、必ず `git checkout develop` を実行して衛星リポジトリをニュートラルな状態へ戻し、次回タスクへの環境汚染を防ぐ。
  3. **メタデータ定義への「デフォルトブランチ」項目の追加**:
     * `develop` のハードコードを避けるため、母艦側のメタデータ定義 `metadata/projects/<PROJECT_KEY>/project.json` に `"base_branch": "develop"` を追加する。
```json
{
  "name": "自社ECサイトリニューアル",
  "key": "EC",
  "base_branch": "develop",
  "created_at": "2026-06-26"
}
```

### PM-037: 衛星リポジトリの「排他制御（ロック機構）」の欠如
* **課題**: `orchestrator_graph.py` は対象Issueのグラフを実行し、Aiderを非対話バッチで起動してワーキングツリーを直接編集する。日次バッチや人間の `/work` コマンドによって、同一プロジェクト（例：EC）の2つのIssueが同時に起動した場合、同じワーキングツリー上でAiderが同時にファイルの読み書きを行い、コードが破壊されるかGit操作が衝突する。
* **解決案**: グラフ実行の開始時（`plan_node` の前）に、`metadata/projects/<PROJECT_KEY>/.lock` のようなロックファイルを生成し、他タスクの実行をブロック（またはキューイング）する排他制御機構を導入する。
  * **推奨実装 1（アトミックなロック取得）**: マイクロ秒単位のプロセス競合（Race Condition）を防ぐため、単純な `open()` ではなく `os.open` に `os.O_CREAT | os.O_EXCL` フラグを指定するか、信頼性の高い `filelock` パッケージを用いてOSレベルでアトミックにロックを取得・解放する。
  * **推奨実装 2（デッドロック対策）**: プロセスクラッシュ（OOMキル等）による残留ロック（Stale Lock）を防ぐため、「ロックファイルのタイムスタンプが一定時間経過していたら強制破棄して再取得する」セーフガードを組み込む。

### PM-038: `tasks.md` へのシステム状態埋め込みによる脆弱性
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
機械（LLMエージェントやバッチスクリプト）がMarkdownファイル内のHTMLコメントを状態管理として読み書きし続ける前提において、アーキテクチャ上の脆弱性が存在する。
* **課題**:
  1. **非表示メタデータの消失リスク**: LLM（planner等）が `tasks.md` を書き換える際、自然言語の文脈を重視するため、プロンプトで指示しても `<!-- round:3 max_round:3 status:FAILED_B7 -->` のような非表示タグを欠落・改変（ハルシネーション）させるリスクが極めて高い。
  2. **トランザクション処理と競合の危険性**: タスク詳細とシステム状態が相乗りしていると更新頻度が跳ね上がり、`code_node` 実行中に planner エージェントや日次バッチが状態を書き込もうとした際、I/O処理が競合して記述内容が破損する危険性がある。
* **解決案（「状態」と「コンテキスト」の分離）**: 完全自動化（M2M）を見据え、システムが管理するデータとLLMが読むドキュメントの責務を分離する。
  1. **SSOTは JSON へ**: タスクID、優先度、ステータス、ラウンド数、ブロッカーなどの機械的プロパティは `metadata/projects/<PROJECT_KEY>/tasks_state.json` などの構造化データで管理し、システムは正規表現ではなく JSON パースで安全に状態を処理する。
  2. **`tasks.md` は JSON からの自動生成（コンパイル）へ**: JSONをそのままLLMに読ませるとトークン浪費と文脈理解の低下を招くため、グラフ実行前やバッチのタイミングで `tasks_state.json` から「LLMが読みやすい自然言語の `tasks.md` (View)」を自動生成して配置する。これにより、`tasks.md` が破壊されても即座に再生成可能な堅牢なフローとなる。

### PM-039: 依存解決度（D）のスコア計算における「実行除外漏れ」リスク
* **課題**: 日次バッチのスコアリングによる実行タスク選定ロジックにおいて、先行タスクが未完了（ブロッカーが存在）の状態で依存解決度が 0 ($D=0$) となっても、優先度 ($P$) が最高値であれば上位にランクインしてしまう可能性がある。
* **解決案**: ブロッカーを持つIssueは「順位を低下させる」のではなく、スコア計算の前にフィルタリングし、実行候補リストから完全に「除外（Drop）」するハードリミット処理を `score-issues.py` に組み込む。
  * **推奨実装 1（フィルタリングフェーズの分離）**: `score-issues.py` において、スコアリング関数にリストを渡す前に前処理（Pre-filtering）フェーズを設け、未完了のIssueに依存している場合は評価用の配列に追加しない設計とする。
  * **推奨実装 2（除外理由の可視化）**: 運用者が日次サイクルの透明性を担保できるよう、「依存未解決のためスキップしたIssue」を標準出力やデバッグログに `[SKIPPED]` として残し、なぜ高優先度タスクが選定されなかったのかを可視化する。

### PM-040: コンテキストウィンドウ（35,000トークン）枯渇への対策不足
* **課題**: ローカルモデルのコンテキスト窓（`max_tokens: 35000`）の制約により、中規模以上の開発でコードツリー全体をプロンプトに流し込むことができない。現在の `plan_node` は `tasks.md` と `project.json` のみを読み込むため、既存コードのコンテキストを持たずに実装計画を立てることになり精度の低下や不整合が生じる。
* **解決案**: `plan_node` の前に、ベクトル検索（RAG）やAST解析を用いた「Context Fetching（関連ファイル抽出）ノード」を追加し、対象タスクに関連する最小限のファイル群を動的抽出してコンテキストに流し込むアーキテクチャへの拡張を行う。

### PM-041: 台帳・メタデータ正本パスの二重定義
* **課題**: `06_複数リポジトリ_差分設計書` などは `metadata/projects/<KEY>/` を正本としているが、README等の構成説明には衛星直下のメタデータ配置が残っている。
* **解決案**: `metadata/` を唯一の正本として文書体系全体で統一し、旧配置は移行情報としても明示的に廃止する。

### PM-042: B7ブロッカー判定履歴スキーマの新旧非互換
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **課題**: 詳細設計は `tasks.md` を判定正本とし履歴を補助とするが、旧オーケストレイト設計書は別フィールドを必要としており、リトライ上限到達を正しく検出できず再実行除外の安全回路が機能しない。
* **解決案**: B7の判定基準・履歴項目・最終状態を詳細設計書の定義へ一本化する。

### PM-043: システム例外時の状態遷移契約不足
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **課題**: LLMタイムアウトやシステムエラーの列挙はあるが、最大試行回数、バックオフ、状態更新、監査記録、最終エスカレーションが未定義。
* **解決案**: 例外種別ごとに、検知箇所、再試行上限、待機方針、終了状態、通知・履歴を状態遷移表で定義する。

### PM-044: 破壊的なGit復旧に対する保全・復元方針欠如
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **課題**: B7時の強制チェックアウトや未追跡ファイル削除手順において、退避対象や失敗時の停止条件、復元方法が定義されていない。
* **解決案**: 作業専用の worktree／ブランチを前提にし、削除前退避、dry-run、復旧先、コマンド失敗時は削除せず中止する方針を設計する。

### PM-045: 自動ブランチ・PR運用の異常系定義不足
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **課題**: 既存ブランチ、既存PR、dirty working tree、認証・ネットワーク障害、PR作成失敗後の状態が定義されていない。
* **解決案**: 事前検証、冪等な再実行、失敗時のブランチ保持、完了状態を確定する順序、人間への引継ぎを明文化する。

### PM-046: 排他制御の契約未完成（PM-037関連）
> [!WARNING] 本セクションの記述は廃止済みの旧案であり、現行仕様には適用しません。状態正本は `metadata/projects/<PROJECT_KEY>/state.json` に統一されています。
* **課題**: PM-037 は提起されたが、ロック取得失敗時の待機／中止、所有者、期限、stale lock、手動解除の監査が設計文書に反映されていない。
* **解決案**: グラフ開始前の必須処理として、原子的取得・解放・タイムアウト・異常終了・監査ログまで定義する。

### PM-047: モデル設定SSOTとフォールバック方針の矛盾
* **課題**: 環境構築書はモデル設定を一元管理するとしつつ、詳細設計には個別モデル名・上限値のフォールバックが残っている。
* **解決案**: 設定欠損時の振る舞いを明文化し、モデル値の管理先を一箇所に固定する。

### PM-048: 文書間版数参照の不一致
* **課題**: ORCH・ENVなどが古いBD/DD版数を参照する一方、PM-025等では整合済みと記録されている。
* **解決案**: ヘッダー、関連文書欄、移行注記を一括更新し、本文では固定版数より文書番号参照を優先する。

### PM-049: 旧ORCH文書の位置付け不明瞭
* **課題**: 冒頭では参考資料と明記されるが、本文に現行仕様のように読める完全な設計記述が残っている。
* **解決案**: 現行設計と旧設計を明確に分離し、旧仕様の節には「参考・非規範」と表示する。可能であれば docs/archive/ へ移動する。

### PM-050: LLM バックエンドの混在 (Ollama vs llama-server)
* **課題**: 現在の設計・実装において、LLM のバックエンド方針が 2 系統混在している。
  - 通常の LLM 呼び出しや Aider (`llm_client.py`, `config_loader.py`, `aider_runner.py` 経由) は **Ollama (localhost:11434)** へ接続する想定となっている。
  - Orchestrator の実行ラッパー (`orchestrator_graph.py`) はタスク実行時に `llama_backend.py` の `managed_llama_server()` を使い、**llama-server (localhost:8080)** を動的起動して GGUF モデルをロードする設計となっている。
  このままでは、`llm_client.py` の接続先とサーバー起動先が一致しない可能性があり、オーケストレーターとLLM間で通信エラーやリソースの二重起動が発生するリスクがある。
* **解決案（排他併用アーキテクチャ）**: 実運用に向けて用途別にバックエンドを最適化するため、「排他併用 (Exclusive Co-usage)」方針を採用する。
  - `BackendExecutionCoordinator` を新設し、推論目的（`intent`）に応じて `Ollama` または `llama-server` へ動的にルーティングする。
  - 両者が VRAM を奪い合わないよう、`metadata/.gpu_lease.lock` を用いた単一のGPUリース管理を導入する。
  - `llm_client.py` および `aider_runner.py` は Coordinator 経由でバックエンドを呼び出すよう統合する。

---

## 4. 改訂履歴
- **2026/07/30 (Rev.2.14)**: 新規課題 PM-050 (LLMバックエンドの混在: Ollama vs llama-server) を追加登録。
- **2026/07/30 (Rev.2.13)**: 設計文書レビューに基づく9件の重要指摘（PM-041〜PM-049: 台帳正本一本化、B7安全回路、例外状態遷移、Git保全等）の設計決定および各設計書への反映完了。
- **2026/07/30 (Rev.2.12)**: PM-036〜PM-038の対応を完了。PM-039およびPM-040は継続課題として整理。
- **2026/07/30 (Rev.2.11)**: 新規課題 PM-040 (35,000トークン制限に伴う Context Fetching ノード / RAG・AST関連ファイル動的抽出の必要性) を追加登録。
- **2026/07/29 (Rev.2.10)**: 新規課題 PM-037 (衛星排他制御・ロック機構), PM-038 (システム状態の state.json 分離), PM-039 (先行未完了Issueのハードリミット除外) を追加登録。
- **2026/07/29 (Rev.2.9)**: PM-036 (develop基準の自動ブランチ・PR運用への方針転換) の内容を BD-002, DD-003, ORCH-001, OP-001, MULTI-001 の各設計書へ反映完了し、ステータスを解決済みに更新。
- **2026/07/29 (Rev.2.8)**: PM-036 (develop 基準・main 非参照の自動ブランチ作成および PR 自動作成運用の策定、escalate_node での develop 退避、project.json への base_branch 追加) を新規追加登録。
- **2026/07/29 (Rev.2.7)**: PM-030 (ENV-001 Step 2 .gitignore ヒアドキュメントの正本化追従), PM-035 (OP-001 §2.1 旧記述の review_rounds 構造への修整完全整合) を完了し解決更新。
- **2026/07/29 (Rev.2.6)**: PM-033 (MULTI-001 §5 Step 4 台帳確認パス修整), PM-034 (BD-002 ヘッダーカッコタイポ修整), PM-035 (DD-003 §4.1.1 への review_rounds レビュー指摘履歴配列追加定義および OP-001 三者整合) をすべて解決済みに更新。
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

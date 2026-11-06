# 詳細設計書（コード編集エンジン統合・コンポーネント仕様）

| 項目               | 内容                                                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- |
| 文書番号           | SBOS-DD-004                                                                                                      |
| 文書名             | Second Brain OS - コード編集エンジン統合（agy / Aider）および自律コーディング仕様                                |
| 版数               | Rev.3.0（agyを現行コード編集エンジンとして確定。Aider退役資産・実機未確認範囲を明記）                            |
| 改訂日             | 2026年11月4日                                                                                                    |
| 関連文書           | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、SBOS-DD-005（Backend 仕様）、Epic #116                     |
| 対象コンポーネント | `tools/agy_runner.py`・`tools/agy_client.py`・`tools/edit_guard.py`・`tools/orchestrator_graph.py` (`code_node`) |
| 役割               | LLM を利用した非破壊的な Git ワーキングツリー差分編集および新規ファイル生成                                      |

> **ファイル名について**: 本書は当初Aider専用だったためファイル名にAiderを含む。現行仕様はagyコード編集エンジンを正本とし、Aiderは `legacy/local_llm/` と archive tag に退避した旧資産として扱う。リンク互換性のため、ファイル名変更は別Issueで行う。
>
> **現行範囲**: agy CLIの実行ファイル解決、`--dangerously-skip-permissions -p`起動、timeout、終了コード分類、衛星cwd編集、edit_guardによる保護を定義する。agy未導入・認証・実モデル品質は試験書のL3以降で確認する。

---

## 1. 概要と基本方針

コード編集エンジンは、Gitのワーキングツリーへ差分を適用し、構文エラーや対象外変更を防ぐ。現行runtimeでは **agy** が唯一のコード編集Adapterであり、Aiderは旧資産として退役済みである。

| 呼び出しの形を維持する | `code_node` は `coordinator.execute("code_edit", ...)` 経由でengineを実行する。現行routeのbackendはagyである。 |
| 外側契約を変えない | `code_node` のstatus/error_categoryとグラフ配線は維持する。 |
| 変更境界を守る | `edit_guard` が母艦cwd、target_files外、秘密ファイル、未許可新規ファイルを保護する。 |
| Git操作を分離する | agyにはcommit/push/PR作成をさせず、`done_node`に委譲する。 |

## 1.1 エンジンの比較（現行agyと退役Aider）

| 項目                            | Aider【退役資産】                                     | agy【現行】                                                                                                       |
| :------------------------------ | :---------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------- |
| 推論の場所                      | ローカル（Ollama の `coding_ollama` プロファイル）    | クラウド（agy 側のモデル）                                                                                        |
| 起動                            | `aider --model ... --message-file ... <target_files>` | `agy`（非対話・ヘッドレス）。起動方式は #117（A1）で確定                                                          |
| 編集方式                        | Aider の `diff` 形式で `target_files` を編集          | agy がツールで作業ツリーを直接編集                                                                                |
| 指示の渡し方                    | UUID 付き一時ファイル `--message-file`                | #117 で確定（コマンドライン長の上限を超えない方式）                                                               |
| 出力の解析                      | しない（終了コードのみ）                              | しない（終了コードと作業ツリーの状態のみ）                                                                        |
| GPU リース                      | 取得する（`BackendExecutionCoordinator`）             | 取得しない（GPU を使わない）                                                                                      |
| `target_files` 外の変更の後始末 | `cleanup_unauthorized_aider_artifacts`（旧資産）      | `edit_guard`（engine非依存）                                                                                      |
| 外部送信                        | なし                                                  | **あり**（`backend_execution.agy_external_send`で制御。既定は`allow_all`、実業務運用前に`allowlist`へ切り替える） |

---

## 2. Aider旧資産（runtime非使用）

Aiderの詳細CLI仕様は archive tag `archive/local-llm-20261104` と `legacy/local_llm/` に保存する。現行routeからAiderを選択できず、Aiderへの復旧は資産復元を伴う別作業である。

## 3. agy CLI実行仕様（現行）

agyは非対話型subprocessとして `agy --dangerously-skip-permissions -p <prompt>` で起動する。起動処理は `tools/agy_client.py`、編集用のcwd・対象ファイル保護は `tools/agy_runner.py` と `tools/edit_guard.py` が担当する。

* **テキスト応答**: `run_agy_text()` は空の一時ディレクトリで実行し、リポジトリを読み書きさせない。
* **コード編集**: `run_agy_edit()` は解決済み衛星cwdで実行し、編集前後にedit_guardを適用する。
* **タイムアウト**: `profile.timeout`（既定1200秒）を適用し、超過時はプロセスツリーを終了して `AgyTimeoutError` を返す。
* **認証・クォータ**: 終了結果を `AGY_AUTH` / `AGY_QUOTA` に分類し、夜間workerの連続失敗停止へ渡す。
* **Git操作**: commit、push、PR作成は行わず、`done_node`へ委譲する。

### 3.1 対象外ファイルの保護

編集エンジンの実行前後で、`target_files` 外の変更を `tools/edit_guard.py` が復元・削除する。許可された新規ファイルは `allowed_new_file_globs` により保持し、秘密ファイル検出と母艦cwd拒否を適用する。

* **前提:** 編集前の作業ツリーは clean とみなす（Fresh は dirty を拒否し、Resume は WIP コミット済み）。このため `target_files` 外の変更はエンジン由来と判断し、実行前のスナップショットとの比較は行わない。実行前に clean でない場合は、警告ログを残す（`warn_if_working_tree_dirty`）。
* **追跡済みファイル（`??` 以外）:** 削除せず `git restore --staged --worktree` で HEAD の内容に戻す。ステージ済みの変更や、削除（ステージ有無を問わず）も取り消す。
* **新規にステージされたファイル（`A`、リネーム・コピー先）:** `git rm -f` で取り消し、実体も削除する。リネーム元は復元する。
* **未追跡ファイル（`??`）:** プロンプトの会話文等から誤って作られたゴミとみなして削除する。**ディレクトリは対象外。**
* **マージ中の衝突ファイル（`U`）:** 触らずに警告する。
* **対象外（保護）:** `target_files`、`.aider*`（旧資産）、`.agy*`、`.pytest*`、`.gitignore`。
* **新規ファイル許可（allowed_new_file_globs / Issue #102）:**
  * `docs/project.json` に `allowed_new_file_globs: ["tests/**", "src/**/*.rs"]` 等が設定されている場合、未追跡ファイルが該当 glob に一致すれば削除せず保持し、`target_files` へ動的追加する。
  * 追跡済みファイルが `target_files` 外で変更された場合は、たとえ glob に一致していても元に戻す（既存設定等の勝手な改変を防止）。
  * 未設定の場合は従来どおり厳格モード（未宣言の新規ファイルは削除）。
* **既知の制約:** `git status` に現れない変更（`.gitignore` 済みファイル、`cwd` 外への書き込み）は検知できない。復元・削除の監査ログ保存は今後の改善候補である。
* **既知の限界:** `git status` に現れない変更（`.gitignore` 済みファイル、`cwd` 外への書き込み）は検知できない。旧Aider由来の関数名が残る箇所は、互換性を壊さない範囲で将来整理する。

## 3.2 agy編集実行仕様（現行） (`agy_runner.py` / `agy_client.py`)

> 本章は現行実装（`tools/agy_client.py` / `tools/agy_runner.py`）の契約である。agy CLIそのものの認証、ネットワーク、実モデル品質は本書では保証せず、`docs/test/SBOS-TEST-001_agy移行確認試験書.md` のL3〜L5で確認する。

### 3.2 モジュール構成

| モジュール            | 責務                                                                           | しないこと                                    |
| :-------------------- | :----------------------------------------------------------------------------- | :-------------------------------------------- |
| `tools/agy_client.py` | agy実行ファイル解決、起動、timeout、**プロセスツリーごとの終了**、エラー種別化 | プロンプト組み立て、JSON解析、Git後始末       |
| `tools/agy_runner.py` | `run_agy_edit()`、`AgyRunError`への変換、edit_guard呼び出し                    | prompt SSOT、外部送信認可、commit/push/PR作成 |
| `tools/edit_guard.py` | cwd検証、target_files外変更・秘密ファイル・新規globの保護                      | agyの起動、LLM応答解析                        |

依存の向きは `code_node` → `agy_runner` → `agy_client` の一方向とする。promptのrole/intent解決は `prompt_harness`、外部送信認可は `agy_policy` が担当する。`tools/` から `.gemini/skills/` 配下のスクリプトをimportしない。

### 3.3 インターフェース

```python
class AgyError(Exception): ...


class AgyNotFoundError(AgyError): ...  # 実行ファイルが見つからない


class AgyTimeoutError(AgyError): ...  # メッセージに必ず "timed out" を含める


class AgyExitError(AgyError): ...  # 非0終了（returncode と stderr の要約を保持）


class AgyRunError(CoderRunError): ...  # agy編集実行のエラー


def run_agy_edit(
    instruction: str, target_files: list[str], cwd: str, *, timeout: int = 1200
) -> bool:
    """成功時 True。非0終了・タイムアウト・未導入は AgyRunError。"""
```

* `AgyRunError` を `AiderRunError` のサブクラスにするのは、`code_node` の `except AiderRunError` で捕捉させ、`code_node` を変更せずに済ませるための暫定措置である。
* **タイムアウトのメッセージに `timed out` を含めることは契約**である。`code_node` は `"timed out" in str(e).lower()` で `LLM_TIMEOUT` を判定する。含めないと、リトライ制御が効かず即座に `FAILED_SYSTEM` となる。

### 3.3 処理の流れ

1. `cwd` が未指定なら `AgyRunError`。`cwd` は常に**衛星**であり、母艦リポジトリを `cwd` にして起動しない（母艦の検証は #125 で強化する）。
2. `agy_client` で agy を `cwd` において起動する。内側のタイムアウトは `profile.timeout`（未設定時 1200 秒）とし、外側の worker タイムアウト（`nightly_worker.toml` の `timeout_seconds`、1800 秒）より短くする。
3. タイムアウト時は、子孫プロセスを含めて終了する（#105 と同じ問題を避ける）。
4. **成功・失敗にかかわらず**、`cleanup_unauthorized_aider_artifacts(cwd, target_files)` を呼ぶ（§2.1）。この後始末は、`code_node` が変更済み `.py` を `target_files` へ追記する処理より**前**に実行される。順序を逆にすると、境界外のファイルが後段の lint / test / review の対象に取り込まれる。

### 3.4 指示（Instruction）の構築

`code_node` が組み立てる指示のうち、Aider 専用のブロックだけを agy では送らない。

| 要素                                                                              | Aider | agy                                                                                                                                       |
| :-------------------------------------------------------------------------------- | :---- | :---------------------------------------------------------------------------------------------------------------------------------------- |
| 初期指示・実装計画・`[SCOPE RESTRICTION]`・`[EXECUTION STRATEGY]`・フィードバック | 送る  | 送る                                                                                                                                      |
| `[STRICT AIDER OUTPUT FORMAT RULES]`（1行目にパス＋コードブロックの出力形式）     | 送る  | **送らない**（agy はツールで直接編集するため不要で、誤誘導になる）                                                                        |
| 代替の追加指示                                                                    | なし  | 「ファイルを直接編集する。対象外ファイルは作成・変更しない。完全な実装を書く（プレースホルダ禁止）」の1ブロック。文面は #117 の結果で調整 |

Aider に渡る指示文は、変更前とバイト単位で一致させる。

### 3.5 エンジンの選択

`code_node` の `_do_aider(profile)` は、`coordinator.execute` から渡される**解決済み profile** の `backend` を見て分岐する。

* `profile.backend == "agy"` → `run_agy_edit(...)`
* それ以外（`ollama` / `llama_server`） → `run_aider(...)`

エンジンの切り替えは `config/models.yaml` の `routes`（`code_edit` / `aider_edit`）が指す profile を変えるだけで行う（DD-005）。`code_node` に独自のエンジン設定項目は設けない。

### 3.6 作業ツリーに作られる成果物

agy が作業ツリーに作る成果物（セッション、キャッシュ、一時ファイル）の名前は #117 で確認する。成果物がある場合は、`tools/metadata_store.py` の `GENERATED_ARTIFACT_GITIGNORE_ENTRIES` にパターンを追加する。

**後始末との相互作用（要注意）**: `cleanup_unauthorized_aider_artifacts` の保護対象（`_is_protected_path`）は、`target_files`、`.aider` 始まり、`.pytest` 始まり、`.gitignore` の4種に固定されている。agy の成果物は保護対象外のため、**未追跡の「ファイル」であれば削除される**。一方、**ディレクトリは削除対象外**（§2.1）で、そのまま残る。agy が実行中に自分のセッション情報を作業ツリー内のファイルに書く場合、編集の最中に後始末で消えるわけではない（後始末は agy の終了後に走る）が、次回の実行で前回の情報が使えなくなる可能性がある。成果物の置き場所と、保護対象へ追加すべきかは #117 の結果で判断する。これは `run_task.py` の dirty 判定、Resume の WIP コミットの除外（DD-003 §5.2）、`doctor.py` の `.gitignore` チェックが共通で参照する定義であり、追加しないと成果物が dirty と判定され、実行が中断または汚染される。

## 4. モデル解決と環境変数・API制御【現行・Aider のみ】

ローカルLLM環境（Ollama 等）とシームレスに連携するため、Aider 実行直前に以下の動的解決およびサニタイズ処理を実施する。agy は OpenAI 互換 endpoint を使わないため、本章は agy には適用されない。

* **動的モデル解決 (`get_default_aider_model`):**
  * モデル名をハードコードせず、実行時に `config/models.yaml` の設定プロファイル（`config.routes` 内の `aider_edit` または `code_edit`）から動的に解決する。
  * 選択されたバックエンドが `ollama` であり、かつモデル名にプレフィックスが無い場合は、自動的に `ollama/` を付与して Aider に渡す。
  * 解決に失敗した場合は、エラーログを出力して固定のフォールバックモデル名を返す（実装は `aider_runner.py` の `get_default_aider_model`）。

* **API エンドポイントのサニタイズ:**
  * 環境変数 `OLLAMA_API_BASE` に `/v1` または `/v1/` のサフィックスが含まれている場合、Aider 側の接続エラーを防ぐため、実行時の環境変数からこれを自動的に除去（サニタイズ）する。

### 5. LangGraph統合とフェイルセーフ仕様（現行agy）

LangGraph上の `code_node` は、現行のagy編集Adapterを呼び出すタスク実行ノードとして機能する。旧Aider資産を復元した比較環境でも、外側契約は同一とする。

### 5.1 プロンプト（Instruction）の動的構築

編集エンジンへ渡す指示は、以下の要素を結合して構築される。

1. **初期指示:** Issue 実装の基本指示（`instruction`）。
2. **実装計画:** `spec_draft_node` が生成した事前実装計画（`impl_plan`）。
3. **フィードバックループ:** 後続ノード（Ruff による静的解析、Pytest、Reviewer）で失敗した際に蓄積されたエラーログやレビュー指摘事項（`aider_message`）。

`aider_message` は状態フィールド名であり、エンジンが agy になっても名称は変更しない（グラフ契約の維持）。

### 5.2 エラー制御とリトライ遷移回路

編集エンジンの実行における異常系は、以下のとおり LangGraph のステータスとして正規化され、安全に処理される。

* **タイムアウト時のリトライ (LLM_TIMEOUT):**
  * プロセスタイムアウト等により `AiderRunError`（または、そのサブクラスである `AgyRunError`）が発生し、メッセージに `timed out` が含まれる場合は、`LLM_TIMEOUT` エラーとして分類する。
  * `llm_timeout_count` をインクリメントし、1回目のタイムアウト時は再度 `code_node` をリトライ（`retry_code`）する。
  * 2回連続でタイムアウトした場合は上限超過とみなし、即座に `FAILED_SYSTEM` へ遷移して安全停止する。

* **CLI異常終了 (SYSTEM_ERROR):**
  * 編集エンジンが非ゼロの終了コードを返した場合、リカバリ不能なシステム異常とみなし、再試行を行わずに `FAILED_SYSTEM` として処理を停止する。
  * agy では認証切れ・クォータ切れも、移行の段階では**この分類に含まれる**（原因は区別されない）。種別ごとの分類と、連続失敗時の中断は #126 で扱う。

* **データ欠損防止のフェイルセーフ:**
  * State 内に `target_files` キーが存在しない場合でも、`code_node` 側で KeyError を起こさず空リストに初期化し、異常停止を防ぐ（編集エンジンによる自律的なファイル抽出に委ねられる）。

### 5.3 `.gitignore` の保護（Issue #26）【現行・エンジン共通】

`code_node` は編集エンジンの実行前に `.gitignore` の内容をスナップショットし、実行後に内容が変化していた場合のみ HEAD の内容へ戻す。編集エンジンを問わず動作する。

## 6. 現行実装と未確認事項

| 項目                                                                 | 状況                                                                      | 確認先          |
| :------------------------------------------------------------------- | :------------------------------------------------------------------------ | :-------------- |
| agyの起動方式・入力の渡し方・終了コード                              | 実装済み。`agy --dangerously-skip-permissions -p` を使用                  | #117 / L1-L2    |
| agyが作業ツリーに作る成果物の名前                                    | fake CLIで確認済み。実agy固有成果物はL3で確認                             | L2 / L3         |
| `agy_client` / `agy_runner` の実装                                   | 実装済み                                                                  | #119 / #122     |
| 外部送信の方針（許可リスト）                                         | `agy_external_send` 実装済み。既定は `allow_all`、本番はallowlist判断待ち | #124 / ADR 0004 |
| 書き込み境界（母艦拒否・秘密情報ファイル検出・ディレクトリの後始末） | `edit_guard` 実装済み。実agyでのL3確認待ち                                | #125 / L1-L3    |
| 認証切れ・クォータの分類、自動フォールバック                         | `AGY_AUTH` / `AGY_QUOTA` 分類済み。自動fallbackなし                       | #126 / L5       |
| Aiderの退役、`CoderRunError`への整理                                 | Aider退役済み。旧資産はlegacy/archiveに保存                               | #128 / #144     |

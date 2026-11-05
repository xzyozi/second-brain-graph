# SBOS-TEST-001 agy 移行確認試験書

| 項目         | 内容                                                                             |
| :----------- | :------------------------------------------------------------------------------- |
| 文書番号     | SBOS-TEST-001                                                                    |
| 文書名       | agy 移行確認試験書（実機なし準備版）                                             |
| 基準コミット | `6a7d6d8`（`origin/develop`、B5および確認試験書PR #145 マージ後）                |
| 対象         | agy CLI、`agy_client`、テキスト応答、コード編集、routes、edit_guard、夜間 worker |
| 関連         | Epic #116、#117、#119、#121、#122、#123、#124、#125、#126、#127、#128、#131      |
| 状態         | **PREPARED / L0確認済み**（L1実行・実機試験待ち）                                |

> 本書は、agy がインストールされていない環境でも作業を途中で止めず、モック試験・静的確認を先に進め、agy 導入後に同じ項目へ実測結果を追記するための正本である。

---

## 1. 現在の実行構成

基準コミット時点の実行経路は次のとおりである。

```text
planner / advisor / reviewer / failure analyst
  -> call_llm
  -> BackendExecutionCoordinator
  -> AgyBackendAdapter
  -> agy_client.run_agy_text

coder
  -> code_node
  -> BackendExecutionCoordinator
  -> AgyBackendAdapter
  -> agy_runner.run_agy_edit
  -> agy_client.run_agy_in_workdir

JEV
  -> tools/jev_adapter.py
  -> Ollama (agy移行対象外)
```

`config/models.yaml` の routes は基準コミットで全て `agy_default` を指す。したがって、agy CLI が無い環境で通常の Issue 実行を行うと `AgyNotFoundError` 系の失敗になる。**本書のモック試験を通さずに実サテライトで実行してはならない。**

### Aider との関係

基準コミットでは、Aider は現役の runtime backend ではない。

- `tools/aider_runner.py` は削除済み。
- Aider の資産は `legacy/local_llm/` とタグ `archive/local-llm-20261104` に保存されている。
- `aider_edit` という intent 名は互換上残っているが、route の向き先は `agy_default` である。
- 現在の runtime で Aider と agy を同じ route の代替として同時実行する機能はない。
- Aider へ戻す場合は、`legacy/local_llm/` または archive tag から復元する別の復旧作業になる。

よって、本試験書では「Aider と agy の同時併用」ではなく、**現行 agy 経路の契約確認と、旧資産からの復旧可能性確認**を扱う。

---

## 2. 試験レベルと実施条件

| レベル | 名称               | agy実機 | 目的                                                                 | 実施可否        |
| :----- | :----------------- | :-----: | :------------------------------------------------------------------- | :-------------- |
| L0     | 静的・構文確認     |  不要   | import、設定、routes、削除漏れ、改行を確認                           | 直ちに実施      |
| L1     | モック単体試験     |  不要   | `agy_client`、`agy_runner`、`call_llm`、`code_node` の契約を確認     | 直ちに実施      |
| L2     | モックプロセス試験 |  不要   | `Popen` 境界、stdout/stderr、終了コード、timeout、ファイル編集を確認 | fake CLI 準備後 |
| L3     | agy契約試験        |  必須   | 実CLIの起動、認証、入力長、出力、成果物を確認                        | agy導入後       |
| L4     | サンドボックスE2E  |  必須   | `spec_draft → code → lint → test → review → done` を確認             | L3合格後        |
| L5     | 運用試験           |  必須   | 夜間 worker、auth/quota、連続失敗停止、ロールバックを確認            | L4合格後        |

### 実機なしで完了できる範囲

- `agy_client` の実行ファイル解決、引数、例外、timeout の単体契約
- `agy_runner` の `AgyRunError` 変換と後始末呼び出し
- `call_llm` の `[SYSTEM]` / `[USER]` 連結、`sanitize_text`、JSON抽出
- `code_node` の agy 分岐、成功、timeout再試行、非0終了
- routes/profile/backend の解決
- `edit_guard` の母艦拒否、秘密情報検出、target_files 外変更の復元
- CI の ruff / mypy / pytest（integration 除外）の合否

### 実機なしでは判定できない範囲

- agy CLI の実際の認証とネットワーク接続
- `--dangerously-skip-permissions -p` の実環境での意味
- 実モデルのJSON遵守率、計画品質、コード編集品質
- 長文diffの入力上限
- agy が作るキャッシュ・セッション・一時ファイル
- クォータ・レート制限・実応答時間
- クラウドへの実際の送信範囲

---

## 3. 試験項目一覧

### 3.1 L0 静的・構文試験

| ID     | 確認項目                                       | 合格条件                                                 | 実施状態                 | 証跡                                   |
| :----- | :--------------------------------------------- | :------------------------------------------------------- | :----------------------- | :------------------------------------- |
| L0-001 | `tools/agy_client.py` / `agy_runner.py` の存在 | 両ファイルが存在しimport可能                             | 確認済み                 | `6a7d6d8`                              |
| L0-002 | `config/models.yaml` の routes                 | 対象intentが `agy_default` を指す                        | 確認済み                 | `config/models.yaml`                   |
| L0-003 | `agy_default` profile                          | `backend: agy`、接続不要、timeoutあり                    | 確認済み                 | `config/models.yaml`                   |
| L0-004 | Aider runtime の退役                           | `tools/aider_runner.py` がruntimeに無く、legacyに保存    | 確認済み                 | `legacy/local_llm/` / #128             |
| L0-005 | JEV の据え置き                                 | `jev_adapter.py` とJEV submoduleが残り、Ollama接続を維持 | 確認済み                 | `tools/jev_adapter.py` / `.gitmodules` |
| L0-006 | Python構文                                     | `python -m py_compile` が成功                            | 確認済み                 | ローカル実行                           |
| L0-007 | CI静的検査                                     | ruff / mypy が成功                                       | ruff確認済み・mypy未確認 | CI/依存環境待ち                        |

実行例:

```powershell
python -m py_compile tools/agy_client.py tools/agy_runner.py tools/llm_client.py tools/orchestrator_graph.py
uv run ruff check tools tests
uv run ruff format --check tools tests
uv run mypy tools
```

### 3.2 L1 モック単体試験

既存の次のテストを対象とする。実 agy は起動しない。

| ID     | テスト対象       | 合格条件                                                | 対応テスト                                   |
| :----- | :--------------- | :------------------------------------------------------ | :------------------------------------------- |
| L1-001 | 実行ファイル解決 | PATH / 既知パス / 未導入例外が正しい                    | `tests/test_agy_client.py`                   |
| L1-002 | コマンド構築     | `agy --dangerously-skip-permissions -p <prompt>` になる | `tests/test_agy_client.py`                   |
| L1-003 | timeout          | `AgyTimeoutError` に `timed out` が含まれる             | `tests/test_agy_client.py`                   |
| L1-004 | 非0終了          | `AgyExitError.returncode` が保持される                  | `tests/test_agy_client.py`                   |
| L1-005 | テキスト応答     | `call_llm` が `{"raw": ...}` を返す                     | `tests/test_llm_client.py`                   |
| L1-006 | JSON応答         | `verdict` / `comments` を解析できる                     | `tests/test_llm_client.py`                   |
| L1-007 | 秘密情報マスク   | agyに渡すpromptにsecret値が残らない                     | `tests/test_llm_client.py`                   |
| L1-008 | coder成功        | `code_completed` へ遷移する                             | `tests/test_orchestrator_agy_integration.py` |
| L1-009 | coder timeout    | 1回目retry、2回目`FAILED_SYSTEM`                        | `tests/test_orchestrator_agy_integration.py` |
| L1-010 | coder非0終了     | `SYSTEM_ERROR` / `FAILED_SYSTEM`                        | `tests/test_orchestrator_agy_integration.py` |
| L1-011 | target外後始末   | 成功・失敗の両方でcleanupが呼ばれる                     | `tests/test_agy_runner.py`                   |
| L1-012 | edit_guard       | 母艦拒否・秘密情報・glob許可・復元                      | `tests/test_edit_guard.py`                   |

実行例:

```powershell
uv run pytest -m "not integration" `
  tests/test_agy_client.py `
  tests/test_agy_runner.py `
  tests/test_llm_client.py `
  tests/test_orchestrator_agy_integration.py `
  tests/test_edit_guard.py
```

### 3.3 L2 モックプロセス試験（準備項目）

`subprocess.Popen` のモックだけでは、実際のプロセス境界やファイル編集を確認できない。必要に応じて、テスト専用の fake agy CLI を用意する。

| ID     | fake CLI の動作                | 合格条件                                | 状態     |
| :----- | :----------------------------- | :-------------------------------------- | :------- |
| L2-001 | stdoutに短いテキストを返す     | `run_agy_text` が受け取る               | PREPARED |
| L2-002 | JSONを返す                     | `call_llm(expect_json=True)` が解析する | PREPARED |
| L2-003 | stderrと非0終了                | `AgyExitError` が分類される             | PREPARED |
| L2-004 | 指定秒数sleep                  | timeoutとプロセス終了を確認する         | PREPARED |
| L2-005 | cwd内のtarget fileを書き換える | `run_agy_edit` と後始末を確認する       | PREPARED |
| L2-006 | target外ファイルも作る         | edit_guardが削除・復元する              | PREPARED |

fake CLI は本番の `agy` と同一視しない。`tests/fixtures/` または一時ディレクトリ内だけで使い、通常のCIで実行するかは実装時に決める。

### 3.4 L3 agy契約試験（実機）

**前提条件**:

- `agy` または `agy.exe` がPATH/既知パスに存在する
- 認証済みであること。認証情報の内容はログ・Issue・証跡へ保存しない
- 実業務コードを使わない使い捨てサテライトを用意する
- サテライト外の秘密情報ファイルを置かない
- 外部送信を許可した試験用データだけを使う

| ID     | 試験         | 操作                           | 合格条件                        | 結果 |
| :----- | :----------- | :----------------------------- | :------------------------------ | :--- |
| L3-001 | CLI存在      | `agy --version`                | versionが返る                   | TODO |
| L3-002 | 最小応答     | `PONG`のみを要求               | 空でないstdout、exit 0          | TODO |
| L3-003 | 長文入力     | 1KB / 10KB / diff相当を送る    | timeout・WinError 206なし       | TODO |
| L3-004 | JSON契約     | reviewer promptを送る          | JSON object、verdict有り        | TODO |
| L3-005 | テキスト契約 | planner promptを送る           | raw応答が空でない               | TODO |
| L3-006 | 編集契約     | 1ファイルを変更                | target fileだけが変更           | TODO |
| L3-007 | 新規ファイル | 許可glob内のファイルを作る     | 許可ファイルが保持される        | TODO |
| L3-008 | 不正ファイル | target外ファイルを作る         | edit_guardが削除・復元          | TODO |
| L3-009 | timeout      | 長時間処理を発生               | 子孫プロセスが残らない          | TODO |
| L3-010 | auth/quota   | 認証またはクォータエラーを確認 | `AGY_AUTH` / `AGY_QUOTA` に分類 | TODO |
| L3-011 | 成果物       | 実行前後の`git status`を比較   | 未知のcache/一時ファイルを記録  | TODO |

実行例:

```powershell
uv run python -m pytest -m integration tests/test_model_contract_agy.py
uv run python -m pytest -m integration tests/test_coder_practical_gui_agy.py
```

### 3.5 L4 サンドボックスE2E

| ID     | 試験              | 合格条件                                          | 結果 |
| :----- | :---------------- | :------------------------------------------------ | :--- |
| L4-001 | 小規模Issue完走   | `spec_draft → code → lint → test → review → done` | TODO |
| L4-002 | planner timeout   | retry後に正常復帰または安全停止                   | TODO |
| L4-003 | reviewer JSON不正 | changes_requestedへ安全側遷移                     | TODO |
| L4-004 | code編集外変更    | edit_guardが境界外変更を処理                      | TODO |
| L4-005 | JEV               | Ollamaを起動した状態でJEV判定が動く               | TODO |
| L4-006 | JEV unavailable   | fail-openでパイプラインが継続                     | TODO |

### 3.6 L5 運用・復旧試験

| ID     | 試験             | 合格条件                            | 結果     |
| :----- | :--------------- | :---------------------------------- | :------- |
| L5-001 | auth連続失敗     | 2回連続でnightly workerを停止       | TODO     |
| L5-002 | quota連続失敗    | 2回連続でnightly workerを停止       | TODO     |
| L5-003 | timeout          | 指数バックオフ後に上限停止          | TODO     |
| L5-004 | worker子プロセス | timeout後に子孫が残らない           | TODO     |
| L5-005 | 旧資産復旧       | archive tagから必要資産を復元できる | PREPARED |
| L5-006 | routes復旧       | 現行構成での切り戻し手順が実行可能  | TODO     |

> 現行 `develop` は Aider runtime を退役済みで、routes は agy を指す。Aider へ戻す場合は `legacy/local_llm/` または `archive/local-llm-20261104` から資産を復元するため、単純なroute変更だけでは戻らない。

---

## 4. 証跡の保存規則

試験結果は本ファイルの `結果` / `実施状態` 欄を更新し、必要なログ・差分・stateは次の相対パスへ保存する。

```text
docs/test/evidence/agy/<YYYYMMDD-HHMMSS>/<TEST_ID>/
```

保存してよいもの:

- exit code、実行時間、判定結果
- sanitized済みのstderr要約
- `git status --porcelain` のパス一覧
- 対象ファイルの差分統計
- state/historyの該当メタデータ

保存してはいけないもの:

- token、API key、Cookie、認証ファイル
- 完全なコマンドラインに含まれる秘密値
- 秘密情報を含むソースコード・プロンプト全文
- ユーザーの認証情報や個人情報

---

## 5. 再開チェックポイント

### 実機なしでの現在地点（基準コミット `6a7d6d8`）

- routes は全て `agy_default` に切り替え済み
- `tools/agy_client.py`、`tools/agy_runner.py`、`tools/edit_guard.py` が現行 runtime に存在する
- Aider runtime は退役済みで、資産は `legacy/local_llm/` と archive tag に保存されている
- agy CLI はこの環境に存在しない
- L0-001〜L0-006は静的確認済み、L0-007のmypyとL1以降のpytestは依存環境/実機待ち

- [x] L0/L1 の実装・テストコードが存在する
- [x] `tests/test_model_contract_agy.py` と `tests/test_coder_practical_gui_agy.py` が `integration` として分離されている
- [x] Aider資産は `legacy/local_llm/` と archive tagへ退避済み
- [ ] fake CLI による L2 は未実装
- [ ] agy CLI導入後のL3は未実施
- [ ] サンドボックスE2EのL4は未実施
- [ ] auth/quota/workerのL5は未実施

### 次に実行する順序

1. `uv run pytest -m "not integration"` を実行してCI相当の基礎を確認する。
2. fake CLIが必要と判断した場合、L2-001〜L2-006を実装する。
3. agy導入環境で `agy --version` と認証を確認する。
4. L3-001〜L3-011を小さい試験から順に実施する。
5. L3合格後にL4-001を実施する。
6. L5のauth/quota/worker試験を実施する。
7. 結果を本書へ追記し、未解決のIssueをクローズまたは再計画する。

---

## 6. 判定ルール

- L0/L1が未通過のまま、agy routesを変更しない。
- L3-001〜L3-006が未通過のまま、実業務サテライトでの運用を開始しない。
- L3-008、L3-009、L5-001〜L5-004が未通過のまま、夜間workerを無人運用しない。
- JSON遵守率、target_files境界、timeout率のいずれかが合格条件を下回った場合、routesを戻すのではなく、原因をIssue化して運用を停止する。
- Aiderとagyの比較が必要な場合、同一入力を別クローンで実行する。現行developではAiderをruntimeへ自動fallbackする機能はない。

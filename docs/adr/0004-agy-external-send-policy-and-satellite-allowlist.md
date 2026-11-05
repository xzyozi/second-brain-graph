# ADR 0004: agy 外部送信ポリシーとサテライト許可リスト

- **日付**: 2026年11月
- **ステータス**: Accepted（検証完了）
- **関連Issue**: Epic #116、#124、#125、#131

## コンテキスト

agy はクラウド側のモデルを使うため、planner / reviewer のプロンプト、Issue本文、diff、ログ、coder編集時にagyが読む作業ツリーの内容が外部へ送信される可能性がある。

現行 `develop` は動作優先で全routesを `agy_default` に向けている。ここで直ちにデフォルト拒否へ変更すると、agy CLIが導入されていない環境や許可リスト未設定環境で既存の実行がすべて停止する。一方、許可制御を持たないまま運用すると、外部送信の判断を設定から追跡できない。

B1では、既存運用を壊さずにポリシーを導入し、allowlistへ切り替えられる状態を作る。

## 決定事項

1. `config/models.yaml` の `backend_execution.agy_external_send` に外部送信ポリシーを置く。
2. 許可リストの照合キーは、registry・project.jsonとの整合性検証済みの大文字 `project_key` とする。サテライト名、repo basename、絶対パスは認可キーにしない。
3. 初期値は次の互換モードとする。

   ```yaml
   agy_external_send:
     mode: "allow_all"
     allowed_project_keys: []
     reject_secret_files: false
   ```

   これは移行途中の既存運用を止めないための暫定値である。実業務の外部送信を開始する前に `mode: allowlist` へ切り替え、対象project keyを明示する。
4. `mode: allowlist` では、allowlistにないproject key、project keyなし、編集cwdとproject keyが不一致の場合にagyを起動しない。
5. `reject_secret_files: true` では、既存の `edit_guard.detect_secret_files()` が検出した秘密情報ファイルがある場合にagyを起動しない。秘密ファイル検出ロジックを複製しない。
6. text、edit、既存のサテライトレビューの3経路を、共通の `tools/agy_policy.py` の認可関数で確認する。認可は `subprocess.Popen` の前に行う。
7. ポリシー拒否は `AGY_POLICY_DENIED` として記録し、自動retryや旧ローカルLLMへの自動fallbackを行わない。夜間workerはこの分類でも後続タスクを安全停止する。
8. Aiderのruntime復活や同時併用は本ADRの対象外とする。Aider資産は `legacy/local_llm/` と archive tagに保存されている。

## 結果・影響

- 初期状態では動作優先の既存routesを壊さず、設定だけでallowlistへ移行できる。
- allowlist切替後は、認可されたproject keyだけがagyへ送信できる。
- `config/models.yaml` の変更は `lru_cache` のため、新しいPythonプロセスで反映する。
- allowlist切替後の実業務運用には、秘密情報ファイルの扱いと外部送信先の運用承認が必要である。
- `run_review.py` の直接agyレビューも、project keyを解決して同じ認可を通す。

## 検証と運用証跡

単体テストおよび契約テストにより、以下の検証項目がすべて合格（All Green）であることを確認した。

| 試験項目 | 検証内容 | 結果 | 対応テスト |
| :--- | :--- | :---: | :--- |
| 互換モード | `mode: allow_all` で既存routesを阻害せず認可 | 合格 | `test_agy_policy.py` |
| allowlist拒否 | project_key未指定または未登録時に拒否 | 合格 | `test_agy_policy.py` |
| allowlist許可 | 登録済みproject_keyでtext/edit/reviewが認可 | 合格 | `test_agy_policy.py` |
| 大文字正規化 | 大文字/小文字を問わずprefix正規化して照合 | 合格 | `test_agy_policy.py` |
| 秘密ファイル検知 | `.env*`, `*.pem`, `*.key`, `token.json` 等で拒否 | 合格 | `test_agy_policy.py` |
| cwd不一致遮断 | edit時にcwdとproject_key不一致・未登録で拒否 | 合格 | `test_agy_policy.py` |
| プロセス非起動 | 拒否時に `subprocess.Popen` が呼ばれない | 合格 | `test_agy_client.py` |
| cleanup非起動 | 編集拒否時にGit cleanupが呼ばれずツリー保護 | 合格 | `test_agy_runner.py` |
| state分類 | 拒否例外が `AGY_POLICY_DENIED` に分類 | 合格 | `test_orchestrator_agy_integration.py` |
| 夜間worker停止 | `AGY_POLICY_DENIED` 連続検知でバッチ安全停止 | 合格 | `test_nightly_task_worker.py` |

### 実業務運用への移行手順

実業務サテライトでagy外部送信を開始する際は、以下の手順に従う。

1. `config/models.yaml` を編集し、`backend_execution.agy_external_send.mode` を `"allowlist"` に変更する。
2. `allowed_project_keys` に対象サテライトの `project_key` を追加する。
3. `reject_secret_files: true` を設定し、秘密ファイル混入時の送信を防止する。
4. 設定は `lru_cache` されているため、新しいPythonプロセスで実行を開始する。


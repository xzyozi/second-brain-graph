# ADR 0004: agy 外部送信ポリシーとサテライト許可リスト

- **日付**: 2026年11月
- **ステータス**: Accepted（互換モードで導入。allowlist切替待ち）
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

## 検証

実機agyなしで、次を単体テストする。

- allow_allの互換動作
- allowlistの許可・拒否
- project keyの大文字比較
- 秘密ファイル検出時の拒否
- cwdとproject key不一致の拒否
- text/edit/reviewの各呼び出し境界で、拒否時にPopenが呼ばれないこと
- `AGY_POLICY_DENIED` のstate分類と夜間workerの停止

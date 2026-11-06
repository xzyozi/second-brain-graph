# ADR 0001: agy バックエンドの追加と routes 抽象による移行方針

- **日付**: 2026-11-04
- **ステータス**: Accepted
- **関連Issue**: Epic #116, #117, #119, #120, #121, #122, #123

## コンテキスト (Context)
これまで本プロジェクトでは、ローカル LLM（Ollama / llama-server）および Aider CLI を用いて自律コーディングおよび計画・レビュー・分析（4つの LLM intent）を実行していた。
しかしローカル LLM は推論速度やコンテキスト窓、モデル性能に限界があり、夜間ワーカーの自律完走率の向上のため、高性能な Google Antigravity CLI (`agy`) への置き換えが求められた。
一方で、JEV（Zero-Decode 検問）は Ollama に依存して据え置く方針であり、また検証段階での安全な切り戻し（ロールバック）手段を維持する必要があった。

## 決定事項 (Decision)
1. **既存の routes 抽象の維持 (Q8)**:
   - 呼び出し側（`call_llm`, `code_node`）のシグネチャと返り値の契約は一切変更しない。
   - `config/models.yaml` の `profiles` に `backend: "agy"` の `agy_default` を追加し、`routes` 8件の向き先を `agy_default` に切り替える。
   - 旧プロファイル（`reasoning_ollama`, `coding_ollama`）は維持し、障害時は `routes` の向き先を戻すだけで即座にロールバック可能とする。
   - `agy` プロファイルは GPU リース（`GpuLeaseAdapter`）の対象外とする。

2. **agy の役割分担と実行境界 (Q2)**:
   - **coder (`code_node`)**: agy がサテライト作業ツリーに入り、ツールを用いて直接差分編集および新規ファイル生成を行う。
   - **planner / reviewer (`call_llm`)**: agy を純粋な「テキスト応答器」として使用する。副作用を防止するため、空の一時ディレクトリ（`tempfile.TemporaryDirectory`）を cwd に指定して起動し、リポジトリの読み書きを行わせない。

3. **プロンプトの扱い (Q9)**:
   - coder 向けプロンプトからは Aider 専用の `[STRICT AIDER OUTPUT FORMAT RULES]` を除去し、直接編集用の指示のみを渡す（`tools/prompt_harness.py` で SSOT 管理）。
   - planner / reviewer では既存のプロンプトをそのまま活用し、`expect_json=True` の場合のみ「JSON オブジェクトのみを出力」する旨の制約を末尾に付与する。

4. **プロセスツリー終了と入力長 (Q14)**:
   - 長大なプロンプトによる Windows コマンドライン長制限（WinError 206）を回避し、一時ファイル経由または堅牢な引数渡しを行う。
   - タイムアウト時には子プロセスツリー全体を確実に強制終了（`taskkill /F /T` / `SIGKILL`）し、プロセスのゾンビ化を防ぐ。

## 結果・影響 (Consequences)
- 既存の LangGraph オーケストレーターのコード構造を破壊することなく、設定ファイルとアダプターの追加のみで高速・高精度な agy 実行基盤へ移行完了。
- ロールバックが設定変更のみで瞬時に可能。
- Ollama は JEV 専用として稼働を継続。

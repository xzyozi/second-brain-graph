# 基本設計書（基本仕様・システム全体アーキテクチャ定義）
**実在OSSスタック統合による Second Brain OS 再設計（LangGraph / LiteLLM / Aider / Ruff / Reviewdog）**

| 項目     | 内容                                                           |
| :------- | :--------------------------------------------------------------- |
| 文書番号 | SBOS-BD-002                                                      |
| 版数     | Rev.4.4（全仕様書完全整合・最終安定版）|
| 改訂日   | 2026年7月29日                                                     |
| 作成日   | 2026年7月28日                                                     |
| 関連文書 | SBOS-DD-003（詳細設計書 Rev.4.5）、SBOS-MULTI-001 Rev.2.3、SBOS-OP-001（運用詳細設計書 Rev.4.2）、SBOS-ENV-001（環境構築仕様書 Rev.4.3）、SBOS-PM-005（課題一覧 Rev.2.4） |
| 対象読者 | システムアーキテクト / リード開発エンジニア / ナレッジマネジメント運用者 / DevOpsエンジニア |

---

## 1. 概要と基本方針

### 1.1 文書の目的と対象範囲
本書は、クラウドLLM APIに依存せず、完全なローカル環境（Ollama + オープンウェイトLLM）および実績あるオープンソースソフトウェア（OSS）を統合して動作する「第二の脳（Second Brain OS）」自律開発・ナレッジ管理スタックの基本設計を定義する。

特に **Rev.4.x 改版**（Rev.4.1で導入され、Rev.4.3で全文書間の完全整合を確定）においては、従来の自前手書きループ（`orchestrator.py` や `agent_client.py` 等）を廃止し、**LangGraph（状態管理・条件分岐グラフ）、LiteLLM（統一LLMインターフェース）、Aider（コード自動編集・Gitワーキングツリー管理）、Ruff（一次高速静的解析）、Reviewdog（差分行アノテーション表示）** という実在OSSスタックへ全面的に置き換えたアーキテクチャを規定する。

### 1.2 構造的課題とOSS統合による解決

| 従来自前実装の課題 | OSS統合（Rev.4.x）での解決策 | 担当コンポーネント |
| :--- | :--- | :--- |
| 手書き `while` ループと Enum 状態管理の不透明性 | 宣言的な StateGraph による状態遷移と視覚的デバッグ | **LangGraph** (`StateGraph`) |
| CLI subprocess 起動による argv 長制限・パース失敗 | HTTP 経由の直接 Ollama `/v1` 接続 | **LiteLLM** (`completion()`) |
| 自作 AST マージの破綻・コード一部消失 | 堅牢な Git ワーキングツリー差分編集と修復 (`--no-auto-commits`) | **Aider** (`aider-chat`) |
| 構文エラー等での無駄な LLM トークン消費 | 高速な一次機械チェックによる即時リジェクト | **Ruff** (`--output-format=json`) |
| レビュー結果の視覚的アノテーション欠落 | 差分行単位でのターミナル出力アノテーション表示 | **Reviewdog** (`-f=rdjson -reporter=local`) |

---

## 2. コンポーネント置き換えマッピング

| # | 旧自前実装 | 置き換え先OSS | ライセンス | 役割と統合方針 |
| --- | --- | --- | --- | --- |
| 1 | `orchestrator.py` (`State` Enum + `while`) | **LangGraph** (`StateGraph`) | MIT | 状態遷移・リトライ・条件分岐エッジを制御。コンテキスト共有を TypedDict State として一元管理。 |
| 2 | `agent_client.py` (`subprocess` + OpenCode) | **LiteLLM** | MIT | Ollama (`http://localhost:11434`) へ直接接続。argv 長制限を解消。 |
| 3 | Coder Agent + `_merge_python_code` | **Aider** (`aider-chat`) | Apache-2.0 | `--no-auto-commits` (複数形) で衛星ワーキングツリーに変更を反映。自動コミットは行わない。 |
| 4 | (なし・LLM任せ) | **Ruff** | MIT | 一次静的解析。LLM呼び出し前に機械的エラーをフィルタリング。 |
| 5 | 自作レビュープロンプト | LiteLLM + **Reviewdog** | MIT | レビュー指摘を rdjson 化し、`-reporter=local -diff="git diff HEAD"` で表示。 |
| 6 | `context_manager.py` (未使用) | LangGraph の `State` | MIT | エージェント間全状態・指摘・ログの確実な共有。 |

---

## 3. システム全体アーキテクチャと安全回路

```text
[ tools/orchestrator_graph.py ]  ← LangGraph StateGraph (母艦)

  gather_requirements (tasks.md / project.json 読み込み)
         │
         ▼
  plan_node (Executor役: LiteLLM 経由で要件指示書生成)
         │
         ▼
  code_node (Aider を衛星リポジトリに対して実行: --no-auto-commits)
         │
         ▼
  lint_node (Ruff 高速静的解析) ─────[失敗 (lint_round < 3)]───┐
         │ [PASSED]                                             │ (指摘を message に追加)
         ▼                                                      │
  test_node (pytest + json-report) ──[失敗 (test_round < 3)]───┤
         │ [PASSED]                                             │
         ▼                                                      │
  review_node (LiteLLM レビュー ＋ Reviewdog 出力)             │
         │                                                      │
         ├─ [LGTM] ─────────────────────────────► done_node (tasks.md 完了更新)
         └─ [changes_requested] ────────────────┤
                                                ▼
                               (round / lint_round / test_round < max_round ?)
                                                │
                                 ├─── [Yes] ───► code_node
                                 └─── [No: 上限到達] ───► escalate_node (tasks.md round:N 動的更新 / B7 ブロッカー化)
```

> **リトライ安全回路（F3対応）:** `review_node` だけでなく、`lint_node`（Ruff）および `test_node`（pytest）の失敗修正ループについても、無制限の無限試行を防止するため `lint_round` / `test_round` (上限 各3回) の安全回路を配備する。上限超過時は直ちに `escalate_node` に遷移してタスクを安全停止させる。

---

## 4. 母艦×衛星 Git 隔離モデルとの整合

1. **`.gitignore` による遮断 (SBOS-MULTI-001)**:
   母艦の `.gitignore` (`/projects/*`, `!/projects/.project-registry.json`) により、衛星内の差分は母艦 Git に影響しない。
2. **Aider のコミット制御 (F1対応)**:
   Aider 起動オプションに正しく `--no-auto-commits`（複数形）を指定。Aider はファイルの修正のみを行い、`git commit` は行わない。
3. **人間の最終承認**:
   `done_node` 到達後、運用者が成果物を確認し、衛星内で手動で `git add && git commit` を行う（`permission` 理念の維持）。

---

## 5. 動作前提および Windows Native 環境特有の制約 (F4対応)

- **対応OS**: Windows Native (PowerShell / `uv`), Linux (Ubuntu), macOS
- **依存管理**: `uv pip install langgraph litellm aider-chat ruff pytest pytest-json-report`
- **LLMサーバー**: Ollama (`localhost:11434`)
- **Windows Native 環境特有の注意点**:
  - **日次タイマージョブ**: Linux の `cron` に代わり、Windows Task Scheduler (`schtasks`) または PowerShell の `Register-ScheduledTask` を使用して日次評価バッチをスケジュールする。
  - **改行コード管理**: Git 設定で `git config --global core.autocrlf input` を指定し、Aider による差分生成時に CRLF / LF の混在で diff が巨大化する問題を防御する。
  - **PowerShell 文字コード**: 日本語パスやプロンプト文字化け防止のため、`$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()` を適用する。
# 設計書バックアップ（agy 移行前）

| 項目 | 内容 |
| :--- | :--- |
| 目的 | JEV を除くローカルLLM使用箇所を agy へ置き換える（Epic #116）に先立ち、改定前の設計書を保存する |
| 取得元コミット | `4e44375`（`develop`、PR #113 のマージ時点） |
| 取得日 | 2026年11月4日 |
| 対象 | `docs/design/SBOS-*.md` の11文書と `docs/design/README.md` |
| 参照Issue | #116（Epic）、#118（A2: 資産退避）、#129（B6: 設計書更新） |

## 扱い

- 本ディレクトリは**参照専用**。内容を更新しない。移行後の正本は `docs/design/` である。
- 改行コードのみ LF に正規化している（取得元の `SBOS-DD-005` は作業ツリーで CRLF が混在していた）。それ以外は取得元と一致する。
- 取得元との一致は、改行正規化後の SHA-256 で11ファイルすべて確認済み。
- 完全な復元点は git の履歴（コミット `4e44375`）と、#118 で作成する `archive/local-llm-*` タグが担う。本ディレクトリは日常の参照用である。

## 復元方法

改定前の状態に戻す場合は、次のいずれかを使う。

1. git から取得する: `git show 4e44375:docs/design/<ファイル名>`
2. 本ディレクトリのファイルを `docs/design/` へコピーする。

## この時点の設計書の主な前提（改定で変わる点）

- BD-002 は「クラウド LLM API に依存せず、ローカル環境の Ollama / llama-server を使う」ことを前提としていた。
- coder は Aider、planner / reviewer は OpenAI 互換 API 経由で Ollama / llama-server を使う構成だった。
- GPU リース（`BackendExecutionCoordinator`）が全 intent の実行を排他していた。

# 詳細設計書（品質ゲート・レビュー仕様）

| 項目               | 内容                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------- |
| 文書名             | Second Brain OS - 品質ゲートおよびレビュー仕様                                        |
| 版数               | Rev.2.1（Node.js・Rustプロファイルとautomationフラグ追記）                            |
| 改訂日             | 2026年9月14日                                                                         |
| 関連文書           | [SBOS-DD-003](SBOS-DD-003_詳細設計書.md)、[SBOS-DD-004](SBOS-DD-004_Aider統合仕様.md) |
| 対象コンポーネント | `metadata/projects/<PROJECT_KEY>/project.json`、`tools/orchestrator_graph.py`         |

---

## 1. 概要と基本方針

品質検証は、実装言語・テストフレームワーク・パッケージマネージャーをオーケストレーターに埋め込まない。各衛星プロジェクトが `project.json` に宣言する品質ゲートを実行し、失敗出力を Aider の修正ループへ返す。

母艦の GitHub Actions は母艦自身の CI であり、衛星 PR の CI 結果を現在のグラフへ取り込む機能は未実装である。CI 結果の監視、失敗ログ取得、再修正・再評価は、後続の CI Adapter 実装で追加する。ローカル品質ゲートと外部 CI を混同して成功扱いにしてはならない。

## 2. プロジェクト宣言型品質ゲート

### 2.1 設定契約

`metadata/projects/<PROJECT_KEY>/project.json` の `quality_gates` に任意のゲートを定義する。各ゲートは shell 文字列ではなく、`subprocess` に渡す引数配列とする。

```json
{
  "language": "nodejs",
  "automation": {
    "quality_gates_enabled": true,
    "ci_enabled": true,
    "ci_auto_fix": false
  },
  "quality_gates": {
    "lint": {
      "command": ["<package-manager>", "run", "lint"],
      "timeout": 300
    },
    "test": {
      "commands": [
        ["<package-manager>", "run", "test"],
        ["<package-manager>", "run", "typecheck"]
      ],
      "timeout": 300
    }
  }
}
```

| 項目                               | 制約                                | 意味                                                                            |
| ---------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------- |
| `language`                         | `python`、`nodejs`、`rust`、`other` | プロジェクトの言語ラベル。現在は設定・将来のCI選択に使用し、実行分岐はしない。  |
| `automation.quality_gates_enabled` | 真偽値、既定 `true`                 | `false` の場合、ローカル品質ゲートを実行せず成功状態へ遷移する。                |
| `automation.ci_enabled`            | 真偽値、既定 `false`                | PR CI 監視を要求する宣言。CI Adapter 実装まで外部CIを実行・判定しない。         |
| `automation.ci_auto_fix`           | 真偽値、既定 `false`                | CI 失敗の自動修正を許可する予約フラグ。`ci_enabled: true` が必須。              |
| ゲート名                           | 任意の文字列                        | `lint` と `test` は現行グラフが呼び出す標準名。追加名は将来のノードで利用する。 |
| `command`                          | 空でない文字列配列                  | 単一コマンド。衛星の `cwd` で直接実行し、シェル展開・連結文字列は許可しない。   |
| `commands`                         | 空でない `command` 配列             | 順に実行する複数コマンド。いずれかの失敗で停止する。`command` と併用不可。      |
| `timeout`                          | 1 以上の整数、既定 300 秒           | ゲート内の各コマンドの停止上限。                                                |

設定が不正なら `resolve_project_context()` は衛星を無効として安全停止する。標準ゲートが未宣言の場合、現行実装は後方互換のためスキップして成功状態へ遷移する。新規衛星では `lint` と `test` の明示を推奨する。

### 2.2 Node.js / Rust プロファイル

| 言語    | `language` | `lint` の推奨 `commands`                                                                                        | `test` の推奨 `command`               | 前提                                                                                                                    |
| ------- | ---------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Node.js | `nodejs`   | `[["npm", "run", "lint"]]`                                                                                      | `["npm", "run", "test"]`              | `package.json` に対応する scripts をプロジェクト自身が定義する。pnpm を使う場合はすべてのコマンドを `pnpm` に統一する。 |
| Rust    | `rust`     | `[["cargo", "fmt", "--check"], ["cargo", "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"]]` | `["cargo", "test", "--all-features"]` | Rust toolchain とプロジェクトの `Cargo.toml` が存在する。                                                               |

これらはオーケストレーターへ言語別ロジックを追加しない宣言例である。実行環境、lockfile、プロジェクト固有の scripts は衛星リポジトリの正本に従う。`ci_enabled` は CI Adapter 実装後にだけ外部CIの監視を開始し、言語ラベルと必須チェックの対応はその Adapter の設定で決定する。

### 2.3 実行・再試行契約

`execute_quality_gate()` は、宣言済みのコマンドを衛星の `cwd` で実行する。成功時は `<gate>_passed`、失敗時は `<GATE>_ERROR` を記録し、`<gate>_round` を加算する。標準出力または標準エラーは `aider_message` に正規化して保存し、`max_round` 未満では `retry_code` により Aider へ戻す。上限到達時は `FAILED_B7`、実行例外は `FAILED_SYSTEM` とする。

`lint_node` は `lint`、互換名を維持する `run_pytest_node` は `test` の品質ゲートを実行する。後者は pytest 専用ではない。`test_feedback_node` は `test_result` の出力を Planner に渡すが、言語・テストフレームワーク・ディレクトリ構成を仮定しない。

## 3. CI フィードバックループ（後続実装の設計方針）

PR 作成後は、ローカル品質ゲートを通過していても CI の完了を待ち、必須チェックの結果で判定する。CI 失敗はコード・設定・ワークフローのいずれに起因するかを区別し、修正可能な失敗だけを Aider の再編集へ戻す。

1. PR URL と対象リポジトリを明示的に確定する。母艦 CI と衛星 PR CI を同一視しない。
2. 必須チェックを監視し、成功・失敗・キャンセル・タイムアウトを正規化する。
3. 失敗時は対象チェックのログだけを取得し、認証情報を除去してサイズを制限した要約を作る。
4. コードまたはプロジェクト設定で解消可能な失敗は `aider_message` に渡して再編集・再 push・再監視する。
5. CI 定義自体の不具合が疑われる場合は、ワークフローと設定を検証対象に含める。ただし必須チェックの無効化、権限昇格、秘密情報の出力は行わない。
6. 取得不能、最大試行超過、または人間判断が必要な失敗は、PR とログ要約を保持して明示的に停止する。

この Adapter は、ユーザーが明示した PR URL を対象に CI 結果を取得・修正・再監視する `github-pr-ci-fixer` と同等の安全境界を持つ。実装時には `CI_PENDING`、`CI_PASSED`、`CI_FAILED`、`CI_UNAVAILABLE` などを `PR_FAILED` と別の状態として定義し、DD-003 の状態遷移・永続化・統合テストを同時に更新する。

## 4. Review Adapter (`review_node` / Reviewdog)

### 4.1 LLM レビュー仕様
* **実行内容**: `review_node` は `implementation_plan` と現在の Git diff を Reviewer LLM に渡し、判定（`LGTM` または `changes_requested`）およびコメント配列を要求する。
* **コメントの構造化**: 
  * LLMからのコメントは `file`、`line`、`message`、`severity` を補完して構造化される。
  * `changes_requested` と判定されたにもかかわらずコメントが空の場合は、フェイルセーフとして `LGTM` に自動補正される。
* **フィードバックの反映**:
  * severityが `structural`、`major`、`error` 等の重大な指摘、または対象外ファイルへの指摘がある場合は、その内容を Aider への次回のフィードバック指示（`aider_message`）に優先的に追加する。
  * 修正要求（`changes_requested`）は最大3回まで `retry_code` で Aider に差し戻される。

### 4.2 Reviewdog によるアノテーション
* **実行内容**: 構造化されたLLMレビューコメントを RDJSON 形式に変換し、それを標準入力で渡して `reviewdog -f=rdjson -diff="git diff HEAD"` を実行する。
* **副作用・失敗契約**: Reviewdogは補助的な表示機能（CLIやPR上のコメント用）であり、Reviewdog自体の非ゼロ終了や実行例外はログに記録するが、LLMレビュー結果（`review_verdict`）を無効化・中断させることはない。

## 5. エスカレーション (`escalate_node`)

lint または test が上限回数に到達し修正不可能な場合、`escalate_node` が呼び出される。
* **敗因レポートの生成**: 失敗原因とログを含む敗因レポート（`FAILURE_REPORT_<ISSUE_ID>.md`）の生成を試みる。
* **状態の確定**: レポート作成に成功した場合は最終状態を `ESCALATED_NEEDS_REVISION` とし、失敗時は防御的に `FAILED_B7` または `FAILED_SYSTEM` にフォールバックする。

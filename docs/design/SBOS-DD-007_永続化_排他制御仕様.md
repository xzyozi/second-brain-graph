# 詳細設計書（永続化・排他制御仕様）

| 項目 | 内容 |
| --- | --- |
| 文書名 | Second Brain OS - メタデータ永続化および排他制御仕様 |
| 版数 | Rev.1.0 |
| 改訂日 | 2026年8月8日 |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（オーケストレーター統合設計） |
| 対象コンポーネント | `state.json`、`execution_history.json`、`ProjectLockManager` |
| 役割 | プロジェクト台帳・メタデータのディレクトリ構成、データフォーマット、永続化（fsync＋原子置換）の契約、およびプロジェクトロックの制御 |

---

## 1. 概要と基本方針

本仕様は、母艦（Second Brain OS）が管理するメタデータディレクトリの構造と、オーケストレーターの実行状態や履歴を安全に永続化する仕組み、および並行実行時のプロジェクトロック（排他制御）の契約について定義する。

## 2. ディレクトリ構成とメタデータ形式

### 2.1 ディレクトリ構成

母艦のメタデータ（Metadata Store）と衛星リポジトリは物理的に分離される。

```text
metadata/
├── .project-registry.json                 # 全衛星プロジェクトの台帳
└── projects/<PROJECT_KEY>/
    ├── project.json                       # 当該衛星の構成・ブランチ設定
    ├── tasks.md                           # 人間向けのタスク一覧
    ├── issues/<ISSUE_ID>.md               # 各 Issue の詳細・Target Files・DoD
    ├── state.json                         # Issue 終端状態の SSOT
    ├── .lock                              # プロジェクト実行時の排他ロックファイル
    └── events/                            # ロック競合などの個別イベントログ
```

### 2.2 メタデータ形式

| ファイル | 主な項目 | 使用箇所 |
| :--- | :--- | :--- |
| `.project-registry.json` | `projects.<key>.dir`、`meta` | 衛星ディレクトリとメタデータディレクトリの紐付け解決。 |
| `project.json` | `key`、`base_branch`、`work_branch_prefix`、`target_files`、`exclude_files` | 文脈・ブランチプレフィックス・対象ファイルの解決。 |
| `issues/<ISSUE_ID>.md` | Target Files、制約、Non-goals、DoD | Aider への指示（instruction）構築と対象 Python ファイルの優先解決。 |
| `state.json` | Issue ID ごとの `status`、`review_round`、`max_round`、`error_category`、`updated_at` | 終端状態の SSOT。 |

## 3. 永続化（データの保存契約）

オーケストレーターの状態は、LangGraph の実行中ではなく、フローが終端状態に達した後に一括して安全に保存される。

### 3.1 state.json の更新
`update_task_state()` は `state.json` の対象 Issue エントリのみを更新する。
* **フェイルセーフ**: 旧フラット形式のデータを検出した場合は、Issue ID をキーとする新しいネスト形式へ自動移行する。
* **原子性の担保**: 書き込みは、一時ファイルへの JSON 出力、`os.fsync` によるディスク書き込みの強制、`os.replace` による既存ファイルとの原子置換の順で行い、データ破損を防ぐ。

### 3.2 実行履歴 (execution_history.json)
`record_execution_history()` は `tools/.cache/execution_history.json` の `records` 配列へ追記する。
* **独立した保護**: 履歴専用の `FileLock` と一時ファイル置換を使用する。
* **安全なフォールバック**: 履歴保存処理が例外を投げた場合でも `safe_record_execution_history()` がこれを吸収し、すでに確定・保存された `state.json` の結果を巻き戻したり上書きしたりしない。

## 4. プロジェクトの排他制御（ロック機構）

`ProjectLockManager` は、複数のプロセスが同一プロジェクト（衛星リポジトリ）を同時編集することを防ぐ。

* **ロック取得**: プロジェクトディレクトリ内の `.lock` ファイルを `FileLock(timeout=0)` で取得する。
* **競合時の挙動**: 取得不能（既に別のプロセスが実行中）な場合は、待機やキューイングを行わず、即座に `SKIPPED_LOCKED` としてステータスを確定する。
* **イベントの記録**: ロック競合が発生した場合は、`events/event_<execution_id>_<timestamp>.json` を作成して記録する。通常の遷移をイベントとして保存する機能は持たない。

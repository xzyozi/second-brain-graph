# 詳細設計書（永続化・排他制御仕様）

| 項目 | 内容 |
| --- | --- |
| 文書名 | Second Brain OS - メタデータ永続化および排他制御仕様 |
| 版数 | Rev.2.0（サテライト仕様帰属化・ランタイムデータ完全隔離版） |
| 改訂日 | 2026年9月20日 |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（オーケストレーター統合設計）、SBOS-MULTI-001（複数リポジトリ設計書） |
| 対象コンポーネント | `state.json`、`execution_history.json`、`ProjectLockManager`、`write_event` |
| 役割 | サテライト仕様・タスク資産の帰属、ランタイム動的データの隔離、永続化（fsync＋原子置換）の契約、および排他制御 |

---

## 1. 概要と基本方針

本仕様は、オーケストレーター母艦（Second Brain OS）の純化とサテライトリポジトリへの仕様・タスク帰属化（Issue #45）に伴い、
1. サテライトプロジェクト資産（仕様・タスク一覧・構成定義）の正本管理
2. 実行時動的データ（排他ロック・実行ステータス・時系列ログ）の Git 完全隔離（`tools/.cache/`）
3. 並行実行時の排他制御（プロジェクトロック）および永続化契約
について定義する。

## 2. ディレクトリ構成とデータ配置

### 2.1 ディレクトリ構成（3層分離アーキテクチャ）

母艦リポジトリの Git 汚染を物理的に防ぎ、かつサテライト単体でのポータビリティを確保するため、以下の3層分離を行う。

```text
[サテライト側] projects/<name>/
└── docs/
    ├── project.json                       # 【正本】当該衛星の構成・ブランチ設定
    ├── tasks.md                           # 【正本】人間向けのタスク一覧・インデックス
    └── issues/<ISSUE_ID>.md               # 【正本】各 Issue の詳細・Target Files・DoD

[母艦エンジン] second-brain-graph/
├── metadata/
│   ├── .project-registry.json             # 全衛星プロジェクトの中央台帳
│   └── projects/<PROJECT_KEY>/            # （後方互換・旧環境用フォールバック）
└── tools/.cache/                          # 【Git完全隔離領域】ランタイム動的データ
    └── projects/<PROJECT_KEY>/
        ├── .lock                          # プロジェクト実行時の排他ロックファイル
        ├── state.json                     # Issue 実行ステータスの SSOT
        └── events/                        # ロック競合・実行イベントログ (*.json)
```

### 2.2 データ形式と解決優先順位

| ファイル | 主な項目 | 配置場所 | 解決優先順位 |
| :--- | :--- | :--- | :--- |
| `.project-registry.json` | `projects.<key>.dir`、`meta` | 母艦 `metadata/` | 母艦中央台帳（SSOT） |
| `project.json` | `key`、`base_branch`、`work_branch_prefix`、`target_files`、`exclude_files` | サテライト `docs/` | **1. サテライト docs/** → 2. 母艦 metadata/ |
| `tasks.md` | Issue ID・タイトル・優先度・依存関係（blockedby） | サテライト `docs/` | **1. サテライト docs/** → 2. 母艦 metadata/ |
| `issues/<ISSUE_ID>.md` | Target Files、制約、Non-goals、DoD | サテライト `docs/issues/` | **1. サテライト docs/** → 2. 母艦 metadata/ |
| `state.json` | Issue ID ごとの `status`、`review_round`、`max_round`、`error_category`、`updated_at` | 母艦 `tools/.cache/` | ランタイムキャッシュ（Git隔離） |
| `.lock` | プロセス排他ロック | 母艦 `tools/.cache/` | ランタイムキャッシュ（Git隔離） |
| `events/*.json` | `execution_id`、イベント種別、タイムスタンプ | 母艦 `tools/.cache/` | ランタイムキャッシュ（Git隔離） |

## 3. 永続化（データの保存契約）

オーケストレーターの状態は、LangGraph の実行中ではなく、フローが終端状態に達した後に一括して安全に保存される。

### 3.1 state.json の更新
`update_task_state()` は `tools/.cache/projects/<PROJECT_KEY>/state.json` を対象に、指定 Issue エントリのみをアトミックに更新する。
* **動的データ隔離**: デフォルトの出力先は `tools/.cache/projects/<PROJECT_KEY>/state.json` とし、母艦の Git 差分を発生させない。
* **フォールバック**: 新パスに `state.json` が存在せず、旧パス（`metadata/projects/<KEY>/state.json`）が存在する場合は、初回移行として旧パスの内容を読み込んで新パスへ引き継ぐ。
* **テスト後方互換**: 引数で `metadata_dir`（非標準ディレクトリ）や `state_file` が明示された場合は、指定先へ保存する。
* **原子性の担保**: 一時ファイルへの JSON 出力、`os.fsync` によるディスク書き込み強制、`os.replace` による原子置換の順で行い、データ破損を防ぐ。

### 3.2 実行履歴 (execution_history.json)
`record_execution_history()` は `tools/.cache/execution_history.json` の `records` 配列へ追記する。
* **独立した保護**: 履歴専用の `FileLock` と一時ファイル置換を使用する。
* **安全なフォールバック**: 履歴保存処理が例外を投げた場合でも `safe_record_execution_history()` がこれを吸収し、すでに確定・保存された `state.json` の結果を巻き戻したり上書きしたりしない。
* **機密情報サニタイズ**: トークン、APIキー、認証情報、パスワードを `[REDACTED]` に自動マスクして永続化する。

## 4. プロジェクトの排他制御（ロック機構）

`ProjectLockManager` は、複数のプロセスが同一プロジェクト（衛星リポジトリ）を同時編集することを防ぐ。

* **ロック取得**: デフォルトで `tools/.cache/projects/<PROJECT_KEY>/.lock` を `FileLock(timeout=0)` で取得する。母艦メタデータ領域に `.lock` を残さない。
* **競合時の挙動**: 取得不能（既に別のプロセスが実行中）な場合は、待機やキューイングを行わず、即座に `SKIPPED_LOCKED` としてステータスを確定する。
* **イベントの記録**: ロック競合が発生した場合は、`tools/.cache/projects/<PROJECT_KEY>/events/event_<execution_id>_<timestamp>.json` を作成して記録する。通常の遷移をイベントとして保存する機能は持たない。


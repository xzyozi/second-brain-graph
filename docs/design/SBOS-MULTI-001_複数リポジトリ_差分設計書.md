# 複数リポジトリ管理および差分検証・スコアリング設計書 Rev.4.0
**「第二の脳」母艦 × 衛星アーキテクチャ 拡張仕様**

| 項目     | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-MULTI-001                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 版数     | Rev.4.0（Epic #179: GitHub Issues SSOT 化に伴う `tasks.md` / `docs/issues/` 廃止、多言語・CI監視設定、JEV Submodule 例外方針を反映）                                                                                                                                                                                                                                                                                                                                                                                              |
| 改訂日   | 2026年11月27日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 作成日   | 2026年6月26日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、[SBOS-DD-004](SBOS-DD-004_Aider%E7%B5%B1%E5%90%88%E4%BB%95%E6%A7%98.md)、[SBOS-DD-005](SBOS-DD-005_Backend_GPU%E3%83%AA%E3%83%BC%E3%82%B9%E4%BB%95%E6%A7%98.md)、[SBOS-DD-006](SBOS-DD-006_%E5%93%81%E8%B3%AA%E3%82%B2%E3%83%BC%E3%83%88_%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC%E4%BB%95%E6%A7%98.md)、[SBOS-DD-007](SBOS-DD-007_%E6%B0%B8%E7%B6%9A%E5%8C%96_%E6%8E%92%E4%BB%96%E5%88%B6%E5%BE%A1%E4%BB%95%E6%A7%98.md)、SBOS-OP-001（運用詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. アーキテクチャ設計方針
本システムでは **サテライトプロダクトの管理に Git Submodule を一切使用しない**。自律コーディング中にサブモジュールのポインタ更新や Detached HEAD を誤操作するリスクを防ぐためである（※例外として、母艦側の基盤ライブラリ `submodules/jev-localsystem` のみ JEV 推論エンジン用 Git Submodule として読み取り専用で組み込んでいる）。
代わりに **「母艦の `.gitignore` による完全遮断 × 衛星本体への構成帰属 (`projects/<name>/docs/project.json`) × GitHub Issues SSOT × 中央台帳 (`metadata/.project-registry.json`) × ランタイム動的データの完全隔離 (`tools/.cache/`)」** を採用する。

* **母艦 (`second-brain-graph/`)**：システムOS・自律オーケストレーターエンジン。ルール・プロンプト・自動化ツール・中央台帳を管理し、Git 履歴をサテライトの進捗 ToDo で汚染させない（母艦の純化）。
* **衛星 (`projects/<name>/`)**：独立したプロダクト。各自が独立した `.git` を持ち、プロダクトコード（`src/`, `tests/`）およびプロジェクト構成定義（`docs/project.json`）を保持する。タスク一覧・詳細仕様・進捗ステータスは **GitHub Issues（`stage:*` ラベル）** に一元化する（Epic #179 により旧 `docs/tasks.md` および `docs/issues/*.md` は廃止済み）。
* **ランタイム動的データ (`tools/.cache/projects/<KEY>/`)**：排他ロック（`.lock`）、実行ステータス（`state.json`）、時系列イベント（`events/`）は母艦の `.gitignore` で完全遮断されたキャッシュ領域へ隔離する。

> **（Issue #45 → Epic #179 アーキテクチャ進化）** Issue #45 で確立したサテライト構成帰属とランタイム隔離の 3 層分離を基盤とし、さらに Epic #179 によってローカルの `docs/tasks.md` / `docs/issues/*.md` の二元同期を廃止して GitHub Issues を唯一の正本（SSOT）とする構成へ移行した。

---

## 2. コア仕様の4大変更点

### ① 母艦側 `.gitignore` による完全 Git スコープ遮断 (PM-027)
`~/second-brain/.gitignore` に以下を規定する。
```text
/projects/*
/projects/.*
!.gitignore
```

これにより、衛星リポジトリ (`projects/<name>/`) の Git ツリー・コミット履歴・差分は母艦側から完全に分断遮断される。

> **補足：** `tools/score_issues.py` や `tools/core/orchestrator_graph.py` が `metadata/.project-registry.json` や `projects/<name>/docs/project.json` を読み書きする処理は Python の通常のファイル I/O で行われる。`.gitignore` は母艦の Git トラッキング対象を制御するのみであり、スクリプトのファイルアクセスには影響しない。

### ② Issue ID スキーマ拡張仕様（4桁連番・サブタスク A〜Z・名前空間制）

全プロジェクト間でのID衝突防止および複雑なタスクの階層管理のため、以下の Issue ID スキーマを正本として規定する。

#### 1. ID 構文仕様
* **親タスク**: `[PROJECT_KEY]-[4桁連番]` （例: `EC-0001`, `MOB-0042`）
* **サブタスク**: `[PROJECT_KEY]-[4桁連番]-[サブタスクID]` （例: `EC-0001-A`, `EC-0001-B`）

#### 2. 各フィールドの規定
- **`PROJECT_KEY` (プレフィックス):**
  各衛星プロジェクトを識別する英大文字 2〜5 桁の識別子。`project.json` の `"key"` フィールドで定義する（例: `EC`, `MOB`, `SBOS`）。
- **`4桁連番`:**
  `0001` から `9999` までの4桁ゼロパディング数値。
- **`サブタスクID` (アルファベット A〜Z):**
  親タスクに属するサブタスクを英大文字 `A` から `Z` の一文字でハイフン接続表記する（例: `EC-0001-A`）。

#### 3. サブタスク分解・運用原則
* **上限と切り分け基準:**
  1つの親タスクに紐づくサブタスクの上限は `A` 〜 `Z` (最大26個) とする。
* **オーバーフロー時のタスク分解ルール:**
  `Z` を超えるような複雑かつ肥大化したタスクは、無制限に階層を深めるのではなく、要件定義・分解フェーズの段階で複数の独立した親タスクへ分割するか、先行実装部分などを切り離して新規親タスク（例: `EC-0002`）として追加定義する。

#### 4. メタデータ配置階層 (Issue #45 / Epic #179 確定仕様)
サテライト固有の構成定義は衛星本体の `docs/project.json` に帰属させ、タスク仕様・進捗状態は **GitHub Issues（SSOT）** に一元化し、実行時動的データは母艦の `tools/.cache/` 配下に完全隔離する。

```text
[GitHub Issues (SSOT)]
└── {PROJECT_KEY}-{issue_number:04d} の仕様本文（0〜8章）および stage:* ラベル

[サテライト側] projects/ec-site/
└── docs/
    └── project.json   # 【正本】プロジェクト固有の設定（base_branch, language, test_command, watch_ci 等）

[母艦エンジン] second-brain-graph/
├── metadata/
│   ├── .project-registry.json  # 全衛星プロジェクトの中央台帳 (dir, meta, github_repo)
│   └── projects/EC/            # FAILURE_REPORT 出力先 / 旧環境フォールバック
└── tools/.cache/               # 【Git完全隔離領域】
    └── projects/EC/
        ├── .lock               # プロジェクト排他ロック
        ├── state.json          # 各タスクの機械状態（status, round等）
        └── events/             # ロック競合・実行イベントログ
```

`projects/<name>/docs/project.json`:
```json
{
  "name": "自社ECサイトリニューアル",
  "key": "EC",
  "base_branch": "develop",
  "language": "python",
  "test_command": "",
  "watch_ci": false,
  "github_repo": "owner/ec-site",
  "allowed_new_file_globs": ["tests/**"],
  "created_at": "2026-06-26"
}
```

> **(PM-036 / Issue #168, #170, #171 仕様追加)**: `base_branch` はエージェントが作業ブランチ (`sbos/<Issue-ID>`) を派生させる元のブランチかつ PR ターゲットブランチとなる（デフォルト `develop` 推奨）。また `language`（`python`, `typescript`, `rust`, `javascript`）、`test_command`、`watch_ci` により多言語検証と PR 後 CI 監視を制御できる。

### ③ スラッシュコマンドの動的ディレクトリ移管ロジック

#### `/work <ISSUE_ID>` （例: `/work EC-0001`）

1. プレフィックス `EC` および Issue 番号を抽出。
2. 母艦の `metadata/.project-registry.json` を引き、キー `EC` に対応するソースフォルダ（`projects/ec-site/`）と `github_repo` を特定。
3. **エージェントの作業カレントディレクトリを `projects/ec-site/` へ動的に切り替えてから**オーケストレーターを実行する。
4. 進捗・完了状態は母艦の隔離領域 `tools/.cache/projects/EC/state.json` および GitHub Issues の `stage:*` ラベルへ記録する。

### ④ スコアリング (`tools/score_issues.py`) の全横断スキャン化

定期バッチおよび手動実行されるスコアリングスクリプトは、母艦の中央台帳 `metadata/.project-registry.json` の `github_repo` を参照し、共通取得層 `tools/workspace/github_issues.py` 経由で全衛星の GitHub Issues（Open/Closed）を取得して `stage:ready` かつ未完了ブロッカーのない Issue を 4 軸スコアリングする（Epic #179 により旧 `tasks.md` 走査は廃止）。

| 処理ステップ | 仕様 |
| :--- | :--- |
| 1. 台帳読込 | `metadata/.project-registry.json` の `projects` から各 `project_key` の `dir`・`github_repo` を取得 |
| 2. Issue 取得 | `fetch_remote_issues(github_repo, state="all")` で GitHub Issues（テスト時は `SBOS_GITHUB_ISSUES_FIXTURE`）を取得 |
| 3. ステージ・依存除外 | 完了済み・`on_hold`・`stage:ideation` / `draft` / `stage:in-progress` および未完了の `blockedby` を持つ Issue を除外 |
| 4. 出力 | 4 軸スコア降順で `tools/.cache/priority-cache.json` に保存 |

> **注意：** `projects/<name>/` に `project.json` を配置しただけでは、このスクリプトはそのプロジェクトを検出しない。`.project-registry.json` への登録（`github_repo` 含む）が別途必要（§5 参照）。

生成されるキャッシュ例（**E3修正：フィールド名を実物実装と統一**）：

```json
{
  "issues": [
    { "id": "EC-0012", "issue_number": 12, "project_key": "EC", "project_dir": "projects/ec-site", "score": 94.2, "title": "決済バグ修正" },
    { "id": "MOB-0003", "issue_number": 3, "project_key": "MOB", "project_dir": "projects/mobile-app", "score": 88.0, "title": "プッシュ通知実装" }
  ]
}
```

`project_key`はIssue IDのプレフィックス（`EC`等）、`project_dir`は`projects/`配下のフォルダ名（`ec-site`等）を表す。両者は別概念であり、`.project-registry.json`の`{key: フォルダパス}`マッピングから両方を導出する。

---

## 3. 人間側のエディタ運用メリット

普段人間がコードを書く際は、ターミナルから `code ~/second-brain/projects/ec-site` と**個別の衛星だけをVSCode等で開く**。これにより、母艦の存在を一切意識することなく完全に普段通りのシングルリポジトリ開発を行うことができる。

---

## 4. `metadata/.project-registry.json` のスキーマ

```json
{
  "version": "1.0",
  "projects": {
    "EC": {
      "name": "自社ECサイトリニューアル",
      "dir": "projects/ec-site",
      "meta": "metadata/projects/EC"
    },
    "MOB": {
      "name": "モバイルアプリ開発",
      "dir": "projects/mobile-app",
      "meta": "metadata/projects/MOB"
    }
  }
}
```

キーがIssue IDのプレフィックス（`project.json`内の`key`と一致させる）、`dir` がソースコードパス、`meta` がメタデータ格納パスである。

---

## 5. 新規衛星プロジェクトの登録手順（`tools/add_project.py`）

新しい衛星を追加してスコアリング・Issue実行の対象にするには、`tools/add_project.py` を使用する。

```bash
uv run python tools/add_project.py https://github.com/owner/new-service --key NEW
# または owner/new-service --key NEW
```

- **登録内容**:
  1. 未クローン時は `projects/<repo_name>/` へ `git clone` を実行し、サテライトの `docs/project.json` のみを配置する（Epic #179 により `tasks.md` および `docs/issues/_template.md` は生成しない）。
  2. `.github/workflows/issue-auto-tag.yml` が未存在時は自動生成・配置する（PM-057）。
  3. 母艦の `metadata/.project-registry.json` に `dir` / `meta` / `github_repo` を登録する。
  4. GitHub リポジトリに標準ラベル（`stage:*`, `theme:*`）を自動作成する（PM-058、`--no-setup-labels` で抑止可能）。
- **登録確認・診断・スコアリング**:
  ```bash
  uv run python tools/doctor.py NEW
  uv run python tools/score_issues.py
  ```
- テストは `tests/test_add_project.py` を参照。

# 複数リポジトリ管理および差分検証・スコアリング設計書 Rev.3.0
**「第二の脳」母艦 × 衛星アーキテクチャ 拡張仕様**

| 項目     | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-MULTI-001                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| 版数     | Rev.3.0（サテライト仕様帰属化・母艦純化・ランタイムデータ完全隔離版）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 改訂日   | 2026年9月20日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 作成日   | 2026年6月26日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、[SBOS-DD-004](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-004_Aider%E7%B5%B1%E5%90%88%E4%BB%95%E6%A7%98.md)、[SBOS-DD-005](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-005_Backend_GPU%E3%83%AA%E3%83%BC%E3%82%B9%E4%BB%95%E6%A7%98.md)、[SBOS-DD-006](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-006_%E5%93%81%E8%B3%AA%E3%82%B2%E3%83%BC%E3%83%88_%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC%E4%BB%95%E6%A7%98.md)、[SBOS-DD-007](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-007_%E6%B0%B8%E7%B6%9A%E5%8C%96_%E6%8E%92%E4%BB%96%E5%88%B6%E5%8BEA%E4%BB%95%E6%A7%98.md)、SBOS-OP-001（運用詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. アーキテクチャ設計方針
本システムでは **Git Submodule を一切使用しない**。LLMはサブモジュールのポインタ更新やDetached HEADの概念を正確に扱えず、リポジトリを破壊するためである。
代わりに **「母艦の `.gitignore` による完全遮断 × 衛星本体への仕様帰属 (`projects/<name>/docs/`) × 中央台帳 (`metadata/.project-registry.json`) × ランタイム動的データの完全隔離 (`tools/.cache/`)」** を採用する。

* **母艦 (`second-brain-graph/`)**：システムOS・自律オーケストレーターエンジン。ルール・プロンプト・自動化ツール・中央台帳を管理し、Git 履歴をサテライトの進捗 ToDo で汚染させない（母艦の純化）。
* **衛星 (`projects/<name>/`)**：独立したプロダクト。各自が独立した `.git` を持ち、プロダクトコード（`src/`, `tests/`）に加えて、自律運用に必要なタスク一覧（`docs/tasks.md`）、詳細仕様（`docs/issues/*.md`）、プロジェクト構成（`docs/project.json`）を自前で正本保持する。
* **ランタイム動的データ (`tools/.cache/projects/<KEY>/`)**：排他ロック（`.lock`）、実行ステータス（`state.json`）、時系列イベント（`events/`）は母艦の `.gitignore` で完全遮断されたキャッシュ領域へ隔離する。

> **（Issue #45 アーキテクチャ進化）** 初期の消極的隔離（PM-026: サテライト汚染防止のための母艦一括集約）から、ステージング境界ガード（`target_files` のみコミット）の完成を経て、**「サテライト本体への仕様・タスク資産帰属」** と **「母艦ランタイム動的データの完全物理隔離」** による3層分離アーキテクチャへと刷新した。これにより、サテライト単体のポータビリティを確保しつつ、母艦の Git 履歴汚染を根本解消した。

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

> **補足：** `tools/score-issues.py`や`tools/orchestrator.py`が`metadata/projects/<key>/project.json`や`metadata/projects/<key>/tasks.md`を読み書きする処理は、Pythonの通常のファイルI/Oで行われる。`.gitignore`は母艦の Git トラッキング対象を制御するのみであり、スクリプトのファイルアクセスには影響しない。

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

#### 4. メタデータ配置階層 (Issue #45 確定仕様)
サテライトプロジェクト固有の仕様・タスク資産は衛星本体の `docs/` 配下に正本（SSOT）として帰属させ、実行時動的データは母艦の `tools/.cache/` 配下に完全隔離する。

```text
[サテライト側] projects/ec-site/
└── docs/
    ├── project.json   # 【正本】プロジェクト固有の設定（base_branch等）
    ├── tasks.md       # 【正本】人間向けのタスク説明・インデックス一覧
    └── issues/        # 【正本】Issue ID 単位の詳細仕様マークダウン格納ディレクトリ
        ├── EC-0001.md # 各 Issue の背景、仕様、除外条件、DoD
        └── _template.md

[母艦エンジン] second-brain-graph/
├── metadata/
│   ├── .project-registry.json  # 全衛星プロジェクトの中央台帳
│   └── projects/EC/            # （後方互換・旧環境用フォールバック）
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
  "created_at": "2026-06-26"
}
```

> **(PM-036 仕様追加)**: `base_branch` はエージェントが作業ブランチ (`sbos/<Issue-ID>`) を派生させる元のブランチであり、かつ作業完了後の PR ターゲットブランチとなります。デフォルトは `develop` を推奨します。

> **（レビュー工程統合済みの場合）** SBOS-PM-001 Rev.2.0で追加した`default_models` / `max_review_rounds`フィールドも、レビューループを導入する場合はここに追記する。

### ③ スラッシュコマンドの動的ディレクトリ移管ロジック

#### `/work <ISSUE_ID>` （例: `/work EC-0001`）

1. `sisyphus` がプレフィックス `EC` を抽出。
2. 母艦の `metadata/.project-registry.json` を引き、キー `EC` に対応するソースフォルダ（`projects/ec-site/`）を特定。
3. **エージェントの作業カレントディレクトリを `projects/ec-site/` へ動的に切り替えてから** `executor` および `coder` を起動する。
4. 進捗・完了状態は母艦の隔離領域 `tools/.cache/projects/EC/state.json` へ記録し、自動処理で `tasks.md` は書き換えない。

### ④ スコアリング (`score-issues.py`) の全横断スキャン化

日次バッチが叩くスコアリングスクリプトは、母艦の中央台帳 `metadata/.project-registry.json` を参照し、各サテライトの `docs/tasks.md`（フォールバックで母艦側）を探索・走査する。

```python
# score-issues.py 概念ロジック（実物実装と整合させたもの。詳細はSBOS-OP-001 §5.1を正とする）
import os, json


def load_registry(root_dir: str) -> dict:
    """metadata/.project-registry.json を読み込む。"""
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
    if not os.path.exists(reg_path):
        return {}
    with open(reg_path, encoding="utf-8") as f:
        data = json.load(f)
        return data.get("projects", {})


all_issues = []
projects = load_registry(root_dir=".")
for project_key, info in projects.items():
    project_dir = info.get("dir", f"projects/{project_key}")
    meta_dir = info.get("meta", os.path.join("metadata", "projects", project_key))
    # サテライト側 docs/tasks.md を最優先、なければ母艦フォールバック
    sat_tasks = os.path.join(root_dir, project_dir, "docs", "tasks.md")
    host_tasks = os.path.join(root_dir, meta_dir, "tasks.md")
    tasks_path = sat_tasks if os.path.exists(sat_tasks) else host_tasks
    if not os.path.exists(tasks_path):
        continue
    issues = parse_tasks_md(tasks_path, project_key=project_key)
    all_issues.extend(issues)

# 全プロジェクト横断の優先度Top10を算出しキャッシュ保存
top_issues = calculate_4axis_score(all_issues)
save_to_cache(top_issues, root_dir=".")
```

> **注意：** `projects/<name>/`に`project.json`を配置しただけでは、このスクリプトはそのプロジェクトを検出しない。`.project-registry.json`への登録が別途必要（§5参照）。

生成されるキャッシュ例（**E3修正：フィールド名を実物実装と統一**）：

```json
{
  "issues": [
    { "id": "EC-012", "project_key": "EC", "project_dir": "ec-site", "score": 94.2, "title": "決済バグ修正" },
    { "id": "MOB-003", "project_key": "MOB", "project_dir": "mobile-app", "score": 88.0, "title": "プッシュ通知実装" }
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

## 5. 新規衛星プロジェクトの登録手順（⭐E4：新設）

新しい衛星を追加してスコアリング・Issue実行の対象にするには、以下の手順を実施する。

```bash
cd ~/second-brain

# 1. 衛星ソースコードツリーの作成 (または git clone)
mkdir -p projects/new-service

# 2. 母艦側にメタデータフォルダを作成し project.json と tasks.md を配置
mkdir -p metadata/projects/NEW
cat > metadata/projects/NEW/project.json << 'EOF'
{
  "name": "新規サービス",
  "key": "NEW",
  "base_branch": "develop",
  "created_at": "2026-07-29"
}
EOF

echo "# タスク一覧" > metadata/projects/NEW/tasks.md

# 3. metadata/.project-registry.json に登録
python3 -c "
import json
reg_path = 'metadata/.project-registry.json'
with open(reg_path) as f:
    registry = json.load(f)
registry.setdefault('projects', {})['NEW'] = {
    'name': '新規サービス',
    'dir': 'projects/new-service',
    'meta': 'projects/new-service/docs'
}
with open(reg_path, 'w', encoding='utf-8') as f:
    json.dump(registry, f, indent=2, ensure_ascii=False)
"

# 4. 登録確認
python3 -c "import json; print(json.load(open('metadata/.project-registry.json')))"

# 5. スコアリングを手動実行し、新規衛星が検出されることを確認
uv run python tools/score_issues.py
cat tools/.cache/priority-cache.json | python3 -m json.tool | grep NEW
```

> **補足（実装済み・PM-056）：** 上記の新規衛星登録は `tools/add_project.py` として正式にスクリプト化・実装済みである。サテライト本体の `projects/<name>/docs/` 配下に `project.json`, `tasks.md`, `issues/` を初期配置し、母艦の `metadata/.project-registry.json` にのみ登録する（母艦純化仕様）。通常運用では `uv run python tools/add_project.py --key NEW --name "新規サービス" --dir projects/new-service` を利用すること。テストは `tests/test_add_project.py` を参照。

# 複数リポジトリ管理および差分検証・スコアリング設計書 Rev.2.7
**「第二の脳」母艦 × 衛星アーキテクチャ 拡張仕様**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-MULTI-001 |
| 版数 | Rev.2.7（PM-036 project.json base_branch追加方針反映） |
| 改訂日 | 2026年7月29日 |
| 作成日 | 2026年6月26日 |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、SBOS-OP-001（運用詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. アーキテクチャ設計方針
本システムでは **Git Submodule を一切使用しない**。LLMはサブモジュールのポインタ更新やDetached HEADの概念を正確に扱えず、リポジトリを破壊するためである。
代わりに **「母艦の `.gitignore` による完全遮断 × メタデータ階層分離 (`metadata/projects/`) × 中央台帳 (`metadata/.project-registry.json`)」** を採用する。

* **母艦 (`~/second-brain/`)**：システムOS。ルール・プロンプト・自動化ツール・衛星メタデータを管理する。
* **衛星 (`projects/<name>/`)**：独立したプロダクト。各自が独立した `.git` を持つ通常のリポジトリ（ソースコード専用）。
* **衛星メタデータ (`metadata/projects/<project-key>/`)**：母艦側で管理する各衛星の定義 (`project.json`) およびタスク定義 (`tasks.md`)。

> **（PM-026/PM-027 設計決定）** 衛星ソースコードツリーの汚染を防止するため、`project.json` や `tasks.md` は衛星配下ではなく母艦側 `metadata/projects/<project-key>/` に一括保存する。また、衛星発見は中央台帳 **`metadata/.project-registry.json`** を正とする。

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

#### 4. メタデータ配置階層 (PM-026 確定仕様)
各衛星のメタデータ (`project.json`) およびタスク定義 (`tasks.md`) は、衛星ソースツリー汚染防止のため、母艦側の **`metadata/projects/<PROJECT_KEY>/`** 階層に一括配置する。

```text
metadata/projects/EC/
├── project.json      # プロジェクト固有の設定（base_branch等）
├── tasks.md          # 人間向けのタスク説明・インデックス一覧（HTML状態埋め込みは廃止）
├── state.json        # 【正本】各タスクの機械状態（status, round等）
└── issues/           # 【詳細要件】Issue ID 単位の詳細仕様マークダウン格納ディレクトリ
    ├── EC-0001.md    # 各 Issue の背景、仕様、除外条件、DoD
    └── _template.md  # 統一記述テンプレート
```

`metadata/projects/<PROJECT_KEY>/project.json`:
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
2. 母艦の `metadata/.project-registry.json` を引き、キー `EC` に対応するソースフォルダ（`projects/ec-site/`）およびメタデータフォルダ（`metadata/projects/EC/`）を特定。
3. **エージェントの作業カレントディレクトリを `~/second-brain/projects/ec-site/` へ動的に切り替えてから** `executor` および `coder` を起動する。
4. 進捗・完了状態は母艦側の `metadata/projects/EC/state.json` へ記録し、自動処理で `tasks.md` は書き換えない。

### ④ スコアリング (`score-issues.py`) の全横断スキャン化

日次バッチが叩くスコアリングスクリプトは、母艦の中央台帳 `metadata/.project-registry.json` を参照し全衛星のメタデータを舐めるロジックへ改修する。

```python
# score-issues.py 概念ロジック（実物実装と整合させたもの。詳細はSBOS-OP-001 §5.1を正とする）
import os, json

def load_registry(root_dir: str) -> dict:
    """metadata/.project-registry.json を読み込む。
    形式: {"version": "1.0", "projects": {"EC": {"dir": "projects/ec-site", "meta": "metadata/projects/EC"}}}"""
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
    if not os.path.exists(reg_path):
        return {}
    with open(reg_path, encoding="utf-8") as f:
        data = json.load(f)
        return data.get("projects", {})

all_issues = []
projects = load_registry(root_dir=".")
for project_key, info in projects.items():
    meta_dir = info.get("meta", os.path.join("metadata", "projects", project_key))
    tasks_path = os.path.join(meta_dir, "tasks.md")
    if not os.path.exists(tasks_path):
        continue
    # tasks.md をパースし、各Issueに project_key を付与してスコアリング
    issues = parse_tasks(tasks_path, project_key=project_key)
    all_issues.extend(issues)

# 全プロジェクト横断の優先度Top10を算出
top_issues = calculate_4axis_score(all_issues)
save_to_cache("tools/.cache/priority-cache.json", top_issues)
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
    'meta': 'metadata/projects/NEW'
}
with open(reg_path, 'w', encoding='utf-8') as f:
    json.dump(registry, f, indent=2, ensure_ascii=False)
"

# 4. 登録確認
python3 -c "import json; print(json.load(open('metadata/.project-registry.json')))"

# 5. スコアリングを手動実行し、新規衛星が検出されることを確認
uv run python tools/score-issues.py
cat tools/.cache/priority-cache.json | python3 -m json.tool | grep NEW
```

> **今後の課題：** 上記ワンライナーを`tools/add-project.py`として正式なスクリプト化することを推奨する（現状は本書のコマンド例を都度手打ちする運用となっている）。`tools/add-project.py`は未実装であり、本書の対象範囲外（別途詳細設計が必要）。

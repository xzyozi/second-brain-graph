# 差分設計書 (複数リポジトリ対応モデル) Rev.2.1
**「第二の脳」母艦 × 衛星アーキテクチャ 拡張仕様**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-MULTI-001 |
| 版数 | Rev.2.2（EC-001正本統一・全仕様書整合版） |
| 改訂日 | 2026年7月29日 |
| 作成日 | 2026年6月26日 |
| 関連文書 | SBOS-BD-002（基本設計書 Rev.4.4）、SBOS-OP-001（運用詳細設計書 Rev.4.2）、SBOS-PM-005（課題一覧 Rev.1.9） |

---

## 0. Rev.2.0からの修正差分一覧

| # | 箇所 | Rev.2.0の問題 | Rev.2.1での修正 |
| --- | --- | --- | --- |
| E1 | §3③ / §4④ | プロジェクトキー→フォルダの解決方法が同一文書内で2通り（中央台帳方式 / glob分散スキャン方式）定義され、決着していなかった | **中央台帳方式（`.project-registry.json`）に一本化**。実物`tools/score-issues.py`（SBOS-OP-001 §5.1で確定）と一致させた |
| E2 | §4 | `score-issues.py`概念ロジックがglob方式で書かれており、確定済み実装と食い違っていた | `.project-registry.json`を読む実装に書き換え |
| E3 | §4 出力例 | キャッシュ例のフィールド名`"project"`（フォルダ名）が実物の`"project_key"`（プロジェクトキー）と不一致 | `"project_key"`に統一。フォルダ名が必要な場面のために`"project_dir"`も併記する形に変更 |
| E4 | 文書全体 | 新規衛星を`.project-registry.json`に登録する手順が未定義 | §5「新規衛星プロジェクトの登録手順」を新設 |

---

## 1. アーキテクチャ設計方針
本システムでは **Git Submodule を一切使用しない**。LLMはサブモジュールのポインタ更新やDetached HEADの概念を正確に扱えず、リポジトリを破壊するためである。
代わりに **「母艦の `.gitignore` による完全遮断 × 台帳インデックスによる動的パス探索」** を採用する。

* **母艦 (`~/second-brain/`)**：システムOS。ルール・プロンプト・自動化ツールのみを管理する。
* **衛星 (`projects/<name>/`)**：独立したプロダクト。各自が独立した `.git` を持つ通常のリポジトリ。

> **（E1関連の設計上の注意）** 衛星の発見方法は、後述の通り**`.project-registry.json`という中央台帳を正**とする。「`project.json`さえ配置すれば自動的にスコアリング対象になる」という誤解が生じやすいため、§5の登録手順を必ず併読すること。

---

## 2. コア仕様の4大変更点

### ① 母艦側 `.gitignore` によるGitスコープ分断
`~/second-brain/.gitignore` に以下を規定する。
```text
/projects/*
!/projects/.project-registry.json
```

これにより、AIエージェントが `projects/project-a/` の内部で `git commit` を実行しても、母艦側のGitツリーにはいかなる差分も検知されない。

> **補足：** `tools/score-issues.py`や`tools/orchestrator.py`が`projects/*/project.json`や`projects/*/tasks.md`を読み書きする処理は、Pythonの通常のファイルI/O（`open()` / `glob`）で行われており、`.gitignore`の影響を受けない。`.gitignore`はあくまで**母艦側のgit管理対象**を制御するものであり、Pythonスクリプトのファイルアクセス可否とは無関係である。

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

各プロジェクト直下には必ず識別メタデータ `project.json` を配置する。

```json
{
  "name": "自社ECサイトリニューアル",
  "key": "EC",
  "created_at": "2026-06-26"
}
```

> **（レビュー工程統合済みの場合）** SBOS-PM-001 Rev.2.0で追加した`default_models` / `max_review_rounds`フィールドも、レビューループを導入する場合はここに追記する。

### ③ スラッシュコマンドの動的ディレクトリ移管ロジック

#### `/work <ISSUE_ID>` （例: `/work EC-004`）

1. `sisyphus` がプレフィックス `EC` を抽出。
2. 母艦の `projects/.project-registry.json` を引き、キー `EC` に対応するフォルダ（`projects/ec-site/`）を特定。
3. **エージェントの作業カレントディレクトリを `~/second-brain/projects/ec-site/` へ動的に切り替えてから** `executor` および `coder` を起動する。

> **（E1修正の確認）** この「`.project-registry.json`を引く」という解決方法が、本書全体を通じて唯一の正式な方式である。④のスコアリングスクリプトも同じ方式に統一した。

### ④ スコアリング (`score-issues.py`) の全横断スキャン化

日次バッチが叩くスコアリングスクリプトは、母艦から全衛星を動的に舐めるロジックへ改修する。

**（E2修正：glob方式ではなく`.project-registry.json`を読む方式に統一。実物実装（SBOS-OP-001 §5.1）と一致させた）**

```python
# score-issues.py 概念ロジック（実物実装と整合させたもの。詳細はSBOS-OP-001 §5.1を正とする）
import os, json

def load_registry(root_dir: str) -> dict:
    """projects/.project-registry.json を読み込む。
    形式: {"EC": "projects/ec-site", "MOB": "projects/mobile-app", ...}"""
    reg_path = os.path.join(root_dir, "projects", ".project-registry.json")
    if not os.path.exists(reg_path):
        return {}
    with open(reg_path, encoding="utf-8") as f:
        return json.load(f)

all_issues = []
registry = load_registry(root_dir=".")
for project_key, rel_path in registry.items():
    tasks_path = os.path.join(rel_path, "tasks.md")
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

## 4. `.project-registry.json` のスキーマ

```json
{
  "EC": "projects/ec-site",
  "MOB": "projects/mobile-app",
  "FX": "projects/fx-backtest"
}
```

キーがIssue IDのプレフィックス（`project.json`内の`key`と一致させること）、値が母艦ルートから見た相対パス。

---

## 5. 新規衛星プロジェクトの登録手順（⭐E4：新設）

新しい衛星を追加してスコアリング・Issue実行の対象にするには、以下の手順を**必ず**実施する。`project.json`の配置だけでは不十分である点に注意。

```bash
cd ~/second-brain

# 1. 衛星ディレクトリを作成し project.json を配置
mkdir -p projects/new-service
cat > projects/new-service/project.json << 'EOF'
{
  "name": "新規サービス",
  "key": "NEW",
  "created_at": "2026-07-28"
}
EOF

# 2. tasks.md の雛形を配置
echo "# タスク一覧" > projects/new-service/tasks.md

# 3. .project-registry.json にキーを登録（手動編集、または以下のワンライナー）
python3 -c "
import json
reg_path = 'projects/.project-registry.json'
with open(reg_path) as f:
    registry = json.load(f)
registry['NEW'] = 'projects/new-service'
with open(reg_path, 'w') as f:
    json.dump(registry, f, indent=2, ensure_ascii=False)
"

# 4. 登録確認
python3 -c "import json; print(json.load(open('projects/.project-registry.json')))"

# 5. スコアリングを手動実行し、新規衛星が検出されることを確認
uv run python tools/score-issues.py
cat tools/.cache/priority-cache.json | python3 -m json.tool | grep NEW
```

> **今後の課題：** 上記ワンライナーを`tools/add-project.py`として正式なスクリプト化することを推奨する（現状は本書のコマンド例を都度手打ちする運用となっている）。`tools/add-project.py`は未実装であり、本書の対象範囲外（別途詳細設計が必要）。

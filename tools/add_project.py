"""CLI Tool for adding a new satellite project to Second Brain OS.

SBOS-MULTI-001 Rev.3.0 compliant (Host Purification & Satellite Docs Ownership).
Initializes metadata files (project.json, tasks.md, issues/) directly inside the satellite's
docs/ directory (projects/<name>/docs/) and registers the project into metadata/.project-registry.json.
The host repository's metadata/ directory remains pure and unpolluted.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_master_issue_template(root_dir: str = ".", key: str = "KEY") -> str:
    """母艦の metadata/templates/issue_template.md を読み込み、プロジェクトキーを置換して返す.
    存在しない場合は標準の0〜8章テンプレートにフォールバックする。
    """
    master_path = os.path.join(root_dir, "metadata", "templates", "issue_template.md")
    if os.path.exists(master_path):
        try:
            with open(master_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content.replace("{key}", key)
        except Exception as e:
            logger.warning(f"Failed to read master template from {master_path}: {e}")

    # フォールバック用標準テンプレート (0〜8章完全準拠)
    return f"""# [{key}-XXXX] タスクタイトル

## 0. メタ情報 (Scope & Impact)
- **影響範囲**: サンドボックス限定 / 本番影響あり（要レビュー） のいずれかを明記
- **既存コードへの依存**: なし（新規ファイルのみ） / あり（既存関数を変更）
- **関連Issue**: なし / #XXXX の後続タスク

## 1. 概要・背景
（タスクの背景や目的、解決すべき課題を記述します。オーケストレーターがPR本文サマリーとしても抽出します）

## 2. 仕様および要求事項
<!-- ※起票時は修正方針の選択肢（案1, 案2）を提示。方針決定時に採用案を下の [ ] チェックリストに展開する -->

### 検討中の修正方針 (Proposed Approaches):
<!-- ※運用方針: 基本は「案 1 (推奨)」を採用して確定タスクへ展開します。不都合や別方針の希望がある場合のみ案2の選択または再壁打ちを行います -->
<!-- ※採用する方針のチェックボックスをオン [x] にしてください（またはコメントで指定） -->
- [ ] **案 1 (推奨)**: [最小限・安全な改修アプローチ。理由: 互換性が高く影響が最小]
- [ ] **案 2**: [代替アプローチ。理由: より堅牢だが影響範囲や前提条件に注意が必要]

### 確定実装タスク (Task Checklist):
<!-- ※方針選択完了時（stage:ready 昇格時）に、選ばれた案に基づいて確定チェックボックスが配置されます -->
- [ ] （方針決定後に確定タスクが展開されます）

## 3. 段階的実装手順 (Step-by-step Execution)
- **Phase 1 (Core Implementation)**: まず本体モジュール・主要ロジック・例外クラスのみを最小変更で優先実装すること。
- **Phase 2 (Test Implementation & Refinement)**: 本体実装完了後、テストコード・検証スクリプトを作成・修正し、動作確認を行うこと。

## 4. 編集対象ファイル (Target Files)
- `path/to/file.py`（新規作成 / 既存編集）
- `tests/path/to/test_file.py`

## 5. ドメイン知識・技術上の落とし穴 (Domain Knowledge & Technical Pitfalls)
- 使用ライブラリ・仕様
- 典型的な落とし穴 (Pitfalls)
- 推奨実装パターン (Recommended Patterns)
- **検証用データ・環境の準備方針**:
  - テスト用フィクスチャや実機環境（踏み台接続、環境変数等）の前提条件を明記。

## 6. 設計制約・アンチパターンの禁止 (Architecture Constraints & Forbidden Actions)
安定した品質を維持するため、以下のアーキテクチャ原則を厳守すること：
- **単一責任と一方向のデータフロー**: 関数やクラス間で「相互呼び出し（循環依存・無限再帰）」となる設計を絶対に行わないこと。
- **ハック的なフロー制御の禁止**: ループや再帰の停止条件として不自然なフラグ変数や場当たり的な実装を用いないこと。
- **堅牢な解析ロジック**: 外部データやファイル構造のパース処理において、脆弱なハードコーディングを行わないこと。
- **既存の破壊禁止**: 無関係な設定ファイルや既存の公開 API シグネチャを破壊しないこと。

## 7. 対象外 (Non-Goals)
- 本Issueでは〇〇の実装は行わない（別Issueで対応予定）

## 8. 完了定義 (Definition of Done)
- [ ] すべての要求仕様（セクション2）が実装され、責務が適切に分離されたクリーンな設計になっていること。
- [ ] 動作確認・検証手順（テストまたはスクリプト実行）を実施し、正常終了すること。
- [ ] 意図しない既存機能の破壊や、不要なコード（YAGNI違反）が含まれていないこと。

### 【CI・自動検査に関する運用指針】
- **CI / 静的解析が未整備のプロジェクト**:
  - 自動検査ツール（Ruff等）の実行は強制せず、ローカルでの動作確認コマンドや手動検証スクリプトの正常終了をもって完了とする。
- **CI / 静的解析が整備済みのプロジェクト**:
  - プロジェクト側の CI 設定（GitHub Actions / `pyproject.toml` 等）に準拠し、以下の項目を完了条件として適用する：
    - - [ ] 単体テスト / 回帰テストがすべて通過すること（`pytest` 等）。
    - - [ ] プロジェクト規定の静的解析（Linter / 型検査）エラーが 0 件であること。
    - - [ ] GitHub Actions CI チェックが All Green であること。
"""


ISSUE_AUTO_TAG_WORKFLOW = """name: Auto Label Issues

on:
  issues:
    types: [opened]

permissions:
  issues: write

jobs:
  auto-label:
    runs-on: ubuntu-latest
    steps:
      - name: Add stage:ideation label
        uses: actions/github-script@v7
        with:
          script: |
            const issue = context.payload.issue;
            const title = (issue.title || '').toLowerCase();
            const labelsToAdd = ['stage:ideation'];

            if (title.includes('[feat]') || title.includes('feat:')) {
              labelsToAdd.push('enhancement');
            } else if (title.includes('[fix]') || title.includes('fix:')) {
              labelsToAdd.push('bug');
            } else if (title.includes('[docs]') || title.includes('docs:')) {
              labelsToAdd.push('documentation');
            }

            await github.rest.issues.addLabels({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: issue.number,
              labels: labelsToAdd
            });
"""

STANDARD_STAGE_LABELS = [
    ("stage:ideation", "cfd3d7", "構想・壁打ち中（実装対象外）"),
    ("stage:ready", "0e8a16", "仕様確定・着手可能（tasks.md対象）"),
    ("stage:in-progress", "fbca04", "エージェント実装・作業中"),
    ("stage:done", "1d76db", "完了・マージ済み"),
    ("theme:security", "d93f0b", "セキュリティ脆弱性・安全対策"),
    ("theme:edge_cases", "e99695", "エッジケース・異常系堅牢化"),
    ("theme:architecture", "bfd4f2", "関心事の分離・構造改善"),
]


def extract_github_repo(url: Optional[str]) -> Optional[str]:
    """Extract owner/repo from GitHub URL or git remote string."""
    if not url:
        return None
    url = url.strip()
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", url):
        return url
    return None


def get_git_remote_url(repo_dir: str) -> Optional[str]:
    """Get remote origin URL of a git directory if present."""
    if not os.path.exists(os.path.join(repo_dir, ".git")):
        return None
    try:
        res = subprocess.run(
            ["git", "-C", repo_dir, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return None


def setup_satellite_workflow(sat_path: str) -> str:
    """Ensure .github/workflows/issue-auto-tag.yml exists in the satellite repository."""
    wf_dir = os.path.join(sat_path, ".github", "workflows")
    os.makedirs(wf_dir, exist_ok=True)
    wf_file = os.path.join(wf_dir, "issue-auto-tag.yml")
    if not os.path.exists(wf_file):
        with open(wf_file, "w", encoding="utf-8") as f:
            f.write(ISSUE_AUTO_TAG_WORKFLOW)
        logger.info(f"Initialized satellite auto-tag workflow at {wf_file}")
    else:
        logger.info(f"Satellite auto-tag workflow already exists at {wf_file}")
    return wf_file


def setup_github_labels(github_repo: str) -> None:
    """Create standard stage labels on the satellite GitHub repository if gh CLI is available."""
    for name, color, desc in STANDARD_STAGE_LABELS:
        try:
            subprocess.run(
                [
                    "gh",
                    "label",
                    "create",
                    name,
                    "--color",
                    color,
                    "--description",
                    desc,
                    "--repo",
                    github_repo,
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Ensured label '{name}' in {github_repo}")
        except Exception as e:
            logger.debug(f"Could not setup label '{name}' in {github_repo}: {e}")


def register_project(
    key: str,
    name: str,
    directory: str = "",
    base_branch: str = "develop",
    description: str = "",
    repo_url: Optional[str] = None,
    github_repo: Optional[str] = None,
    setup_labels: bool = True,
    root_dir: str = ".",
) -> Dict[str, Any]:
    """Register a new satellite project into Second Brain OS."""
    key = key.strip().upper()
    name = name.strip()
    if not key or not name:
        raise ValueError("Project key and name must not be empty.")

    if not directory:
        directory = f"projects/{key.lower()}"

    sat_path = os.path.join(root_dir, directory)

    # 1. Clone repository if repo_url provided and directory does not exist
    if repo_url and not os.path.exists(sat_path):
        logger.info(f"Cloning repository {repo_url} into {sat_path}...")
        try:
            subprocess.run(["git", "clone", repo_url, sat_path], check=True)
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            raise

    # Determine github_repo from parameter, repo_url, or satellite git remote
    resolved_github_repo = github_repo or extract_github_repo(repo_url)
    if not resolved_github_repo and os.path.exists(sat_path):
        remote_url = get_git_remote_url(sat_path)
        resolved_github_repo = extract_github_repo(remote_url)

    # 2. Ensure satellite root and docs directory exist
    docs_path = os.path.join(sat_path, "docs")
    os.makedirs(docs_path, exist_ok=True)
    logger.info(f"Ensured satellite docs directory: {docs_path}")

    # 3. Create satellite docs/project.json (SSOT)
    proj_json_path = os.path.join(docs_path, "project.json")
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    proj_data: Dict[str, Any] = {}
    if os.path.exists(proj_json_path):
        try:
            with open(proj_json_path, "r", encoding="utf-8") as f:
                proj_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load existing project.json: {e}")

    proj_data["key"] = key
    proj_data["name"] = name
    proj_data["base_branch"] = proj_data.get("base_branch", base_branch)
    proj_data["created_at"] = proj_data.get("created_at", now_date)
    proj_data["description"] = description or proj_data.get(
        "description", f"{name} satellite project"
    )
    if resolved_github_repo:
        proj_data["github_repo"] = resolved_github_repo

    with open(proj_json_path, "w", encoding="utf-8") as f:
        json.dump(proj_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Updated satellite project config at {proj_json_path}")

    # 4. Create satellite docs/tasks.md if not present
    tasks_md_path = os.path.join(docs_path, "tasks.md")
    if not os.path.exists(tasks_md_path):
        with open(tasks_md_path, "w", encoding="utf-8") as f:
            f.write("# Tasks\n\n")
        logger.info(f"Initialized tasks.md at {tasks_md_path}")
    else:
        logger.info(f"Satellite tasks.md already exists at {tasks_md_path}")

    # 5. Create satellite docs/issues/ and _template.md
    issues_dir = os.path.join(docs_path, "issues")
    os.makedirs(issues_dir, exist_ok=True)
    template_path = os.path.join(issues_dir, "_template.md")
    if not os.path.exists(template_path):
        template_content = load_master_issue_template(root_dir=root_dir, key=key)
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(template_content)
        logger.info(f"Initialized issue template at {template_path}")

    # 6. Ensure satellite has issue auto-tagging workflow (.github/workflows/issue-auto-tag.yml)
    setup_satellite_workflow(sat_path)

    # 7. Optionally setup standard GitHub labels on satellite repository
    if setup_labels and resolved_github_repo:
        setup_github_labels(resolved_github_repo)

    # 8. Update host metadata/.project-registry.json
    reg_path = os.path.join(root_dir, "metadata", ".project-registry.json")
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    registry: Dict[str, Any] = {"version": "1.0", "projects": {}}
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception as e:
            logger.warning(f"Could not parse existing registry, starting fresh: {e}")

    registry.setdefault("projects", {})
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Save relative posix-style paths for directory
    rel_dir = os.path.normpath(directory).replace("\\", "/")
    meta_rel = f"{rel_dir}/docs"

    entry: Dict[str, Any] = {
        "name": name,
        "dir": rel_dir,
        "meta": meta_rel,
        "registered_at": now_iso,
    }
    if resolved_github_repo:
        entry["github_repo"] = resolved_github_repo

    registry["projects"][key] = entry

    tmp_reg = reg_path + ".tmp"
    with open(tmp_reg, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    os.replace(tmp_reg, reg_path)
    logger.info(f"Successfully registered '{key}' into {reg_path}")

    return registry["projects"][key]


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Add a new satellite project to Second Brain OS (Satellite Docs Ownership)."
    )
    parser.add_argument(
        "--key", "-k", required=True, help="Project ID key prefix (e.g. EC, MOB, NEW)"
    )
    parser.add_argument("--name", "-n", required=True, help="Human-readable project name")
    parser.add_argument(
        "--dir", "-d", default="", help="Satellite directory path (e.g. projects/new-service)"
    )
    parser.add_argument(
        "--base-branch", "-b", default="develop", help="Base branch name (default: develop)"
    )
    parser.add_argument("--desc", default="", help="Project description")
    parser.add_argument("--repo", default=None, help="Git repository URL to clone if not present")
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository name in 'owner/repo' format (auto-inferred from --repo if omitted)",
    )
    parser.add_argument(
        "--setup-labels",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Setup standard stage and theme labels on the satellite GitHub repository via gh CLI (default: True)",
    )

    args = parser.parse_args()

    try:
        entry = register_project(
            key=args.key,
            name=args.name,
            directory=args.dir,
            base_branch=args.base_branch,
            description=args.desc,
            repo_url=args.repo,
            github_repo=args.github_repo,
            setup_labels=args.setup_labels,
            root_dir=".",
        )
        print(
            f"Project '{args.key}' successfully registered: {json.dumps(entry, ensure_ascii=False)}"
        )
    except Exception as e:
        logger.error(f"Failed to register project: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

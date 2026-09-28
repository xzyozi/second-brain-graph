"""promote_issue.py - Issue 壁打ち完了・stage:ready 昇格ツール.

起票された stage:ideation の Issue に対し、選定された修正方針（案1/案2）を確定タスクへ展開し、
非採用案を Non-Goals に退避した上で stage:ready に昇格させ、サテライトの tasks.md に同期する。
"""

import argparse
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("promote_issue")


def load_project_registry(root_dir: Path) -> Dict[str, Any]:
    """metadata/.project-registry.json を読み込む."""
    reg_path = root_dir / "metadata" / ".project-registry.json"
    if not reg_path.exists():
        logger.warning(f"プロジェクトレジストリが見つかりません: {reg_path}")
        return {}
    try:
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("projects", {})
    except Exception as e:
        logger.error(f"レジストリの読み込みに失敗しました: {e}")
        return {}


def resolve_project_info(
    root_dir: Path, project_name_or_repo: str
) -> Tuple[Optional[str], Optional[Path], Optional[str]]:
    """プロジェクト名または owner/repo から (project_key, project_dir, github_repo) を解決する."""
    registry = load_project_registry(root_dir)

    # 1. key 直接一致
    if project_name_or_repo in registry:
        info = registry[project_name_or_repo]
        return (
            project_name_or_repo,
            root_dir / info["dir"],
            info.get("github_repo"),
        )

    # 2. name または github_repo 一致
    for key, info in registry.items():
        if (
            info.get("name") == project_name_or_repo
            or info.get("github_repo") == project_name_or_repo
        ):
            return key, root_dir / info["dir"], info.get("github_repo")

    # 3. 未登録だが projects/<name> が存在する場合
    candidate_dir = root_dir / "projects" / project_name_or_repo
    if candidate_dir.exists():
        return None, candidate_dir, project_name_or_repo

    return None, None, project_name_or_repo


def fetch_issue(repo: str, issue_num: int) -> Dict[str, Any]:
    """GitHub CLI で Issue 情報を取得する."""
    cmd = [
        "gh",
        "issue",
        "view",
        str(issue_num),
        "--repo",
        repo,
        "--json",
        "number,title,body,labels",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def parse_approaches(body: str) -> Dict[int, Dict[str, Any]]:
    """Issue 本文から案1、案2のテキストとチェック状態をパースする."""
    approaches: Dict[int, Dict[str, Any]] = {}
    lines = body.splitlines()
    cur_app = None

    for line in lines:
        m = re.match(r"^-\s*\[(?P<chk>[ xX])\]\s*\*\*案\s*(?P<num>[12])(?P<rest>.*)$", line)
        if m:
            num = int(m.group("num"))
            chk = m.group("chk").strip().lower() == "x"
            rest = m.group("rest")
            cleaned_title = re.sub(r"^\s*\([^)]+\)", "", rest).strip()
            cleaned_title = cleaned_title.strip("*: ").strip()
            approaches[num] = {
                "checked": chk,
                "title": cleaned_title,
                "detail": [],
            }
            cur_app = num
        elif cur_app and re.match(r"^\s+-\s+", line):
            approaches[cur_app]["detail"].append(line.strip())
        elif cur_app and line.strip() == "":
            pass
        elif cur_app and not line.startswith(" "):
            cur_app = None

    for num in approaches:
        if approaches[num]["detail"]:
            approaches[num]["detail"] = "\n".join("  " + d for d in approaches[num]["detail"])
        else:
            approaches[num]["detail"] = ""

    return approaches


def extract_priority_and_theme(body: str, labels: List[Dict[str, str]]) -> Tuple[str, str]:
    """重要度とテーマを本文およびラベルから抽出する."""
    priority = "medium"
    theme = "general"

    # 重要度抽出
    m_sev = re.search(r"-\s*\*\*重要度\*\*:\s*([A-Za-z]+)", body)
    if m_sev:
        sev = m_sev.group(1).lower()
        if sev in ["high", "medium", "low"]:
            priority = sev

    # テーマ抽出
    for lbl in labels:
        name = lbl.get("name", "")
        if name.startswith("theme:"):
            theme = name.split(":", 1)[1]
            break

    return priority, theme


def generate_promoted_body(
    body: str,
    selected_approach: int,
    approaches: Dict[int, Dict[str, Any]],
    concrete_tasks: Optional[List[str]] = None,
) -> str:
    """採用案を展開し、非採用案を退避した stage:ready 用の Issue 本文を生成する."""
    sel = approaches.get(selected_approach)
    if not sel:
        raise ValueError(f"アプローチ 案{selected_approach} の情報が見つかりません。")

    rejected_approach = 2 if selected_approach == 1 else 1
    rej = approaches.get(rejected_approach)

    # 1. 起票ステータス更新
    body_updated = re.sub(
        r"-\s*\*\*起票ステータス\*\*:\s*.*",
        "- **起票ステータス**: `stage:ready` (方針確定・実装準備完了)",
        body,
    )

    # 2. セクション2の修正方針・タスクリストの置換
    tasks_md = ""
    if concrete_tasks:
        for t in concrete_tasks:
            tasks_md += f"- [ ] {t}\n"
    else:
        # デフォルトは選ばれた案に基づく基本チェック項目
        tasks_md = (
            f"- [ ] 選定方針（案 {selected_approach}: {sel['title']}）に基づくモジュール実装\n"
        )
        tasks_md += "- [ ] 単体テスト・検証手順の作成および実行確認\n"

    sel_text = f"""### 採用された修正方針:
- **案 {selected_approach}{" (推奨)" if selected_approach == 1 else ""}: {sel["title"]}**
{sel["detail"]}

### 確定実装タスク (Task Checklist):
{tasks_md.rstrip()}"""

    # 既存の ## 2. 仕様および要求事項 から ## 3. までのブロックを置換
    sec2_pattern = re.compile(
        r"(## 2\. 仕様および要求事項.*?\n)(?=## 3\. 段階的実装手順)",
        re.DOTALL,
    )
    if sec2_pattern.search(body_updated):
        body_updated = sec2_pattern.sub(f"## 2. 仕様および要求事項\n\n{sel_text}\n\n", body_updated)

    # 3. セクション7（対象外）に不採用案を退避
    non_goal_entry = ""
    if rej:
        non_goal_entry = f"- **案 {rejected_approach} ({rej['title']})**: 案{selected_approach}を採用したため今回はスコープ外。"

    sec7_pattern = re.compile(
        r"(## 7\. 対象外 \(Non-Goals\).*?\n)(?=## 8\. 完了定義)",
        re.DOTALL,
    )
    if sec7_pattern.search(body_updated):
        cur_sec7 = sec7_pattern.search(body_updated).group(1)
        # プレースホルダーの削除
        cleaned_sec7 = re.sub(
            r"- （※壁打ちで採用されなかった代替アプローチはここに記録してスコープ外を明確化）\n?",
            "",
            cur_sec7,
        )
        if non_goal_entry and non_goal_entry not in cleaned_sec7:
            cleaned_sec7 = cleaned_sec7.rstrip() + f"\n{non_goal_entry}\n\n"
        body_updated = sec7_pattern.sub(cleaned_sec7, body_updated)

    # 4. フッターの更新
    footer_pattern = re.compile(r"---*\s*\n\*※ 本 Issue は.*?\*\s*$", re.DOTALL)
    new_footer = f"---\n*※ 本 Issue は壁打ちにより案{selected_approach}が採用され、stage:ready（実装可能）に昇格しました。*"
    if footer_pattern.search(body_updated):
        body_updated = footer_pattern.sub(new_footer, body_updated)
    else:
        body_updated = body_updated.rstrip() + f"\n\n{new_footer}\n"

    return body_updated


def sync_to_tasks_md(
    tasks_path: Path, project_key: str, issue_num: int, title: str, priority: str
) -> bool:
    """サテライトの tasks.md に新しいタスク行を追記する."""
    if not tasks_path.exists():
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        tasks_path.write_text("# Tasks\n\n", encoding="utf-8")

    content = tasks_path.read_text(encoding="utf-8")

    # 既存登録チェック
    issue_tag = f"issue:#{issue_num}"
    if issue_tag in content:
        logger.info(f"tasks.md には既に Issue #{issue_num} が登録されています。")
        return False

    # 最大タスク番号の検出
    existing_nums = [int(m.group(1)) for m in re.finditer(rf"\[{project_key}-(\d{{4}})\]", content)]
    next_num = max(existing_nums, default=0) + 1
    task_id = f"{project_key}-{next_num:04d}"

    new_line = f"- [ ] [{task_id}] {title} <!-- priority:{priority} {issue_tag} -->\n"

    if content.endswith("\n"):
        updated_content = content + new_line
    else:
        updated_content = content + "\n" + new_line

    tasks_path.write_text(updated_content, encoding="utf-8")
    logger.info(f"tasks.md に追加しました: [{task_id}] {title}")
    return True


def promote_issue(
    root_dir: Path,
    target_project: str,
    issue_num: int,
    approach: Optional[int] = None,
    concrete_tasks: Optional[List[str]] = None,
    dry_run: bool = False,
) -> bool:
    """Issue を stage:ready へ昇格するメイン関数."""
    project_key, project_dir, repo = resolve_project_info(root_dir, target_project)
    if not repo:
        logger.error(f"対象リポジトリを解決できませんでした: {target_project}")
        return False

    logger.info(f"Issue #{issue_num} (リポジトリ: {repo}) を取得中...")
    issue_data = fetch_issue(repo, issue_num)
    body = issue_data.get("body", "")
    title = issue_data.get("title", "")
    labels = issue_data.get("labels", [])

    # 既存ラベル確認
    label_names = [lbl.get("name", "") for lbl in labels]
    if "stage:ready" in label_names:
        logger.warning(f"Issue #{issue_num} は既に stage:ready です。")

    # アプローチのパース
    approaches = parse_approaches(body)
    if not approaches:
        logger.error("Issue 本文から修正方針（案1/案2）をパースできませんでした。")
        return False

    # 選択されたアプローチの決定
    selected_approach = approach
    if selected_approach is None:
        # [x] チェックボックスの自動検出
        for num, app in approaches.items():
            if app["checked"]:
                selected_approach = num
                logger.info(f"チェックボックスから 案{num} の選択を自動検出しました。")
                break

    if selected_approach is None:
        # デフォルト推進ポリシー: 基本は案1
        logger.info(
            "アプローチが指定されていないため、デフォルト推進ポリシーに従い 案1 (推奨) を採用します。"
        )
        selected_approach = 1

    logger.info(f"採用アプローチ: 案{selected_approach}")
    new_body = generate_promoted_body(body, selected_approach, approaches, concrete_tasks)
    priority, theme = extract_priority_and_theme(body, labels)

    if dry_run:
        print("=" * 60)
        print(f"[DRY-RUN] Promoted Body for Issue #{issue_num} (Approach {selected_approach}):")
        print("=" * 60)
        print(new_body)
        print("=" * 60)
        logger.info(f"[DRY-RUN] tasks.md 追記プレビュー: priority={priority}, theme={theme}")
        return True

    # 1. GitHub Issue の更新
    tmp_path = root_dir / f"tmp_promote_{issue_num}.md"
    try:
        tmp_path.write_text(new_body, encoding="utf-8")
        cmd = [
            "gh",
            "issue",
            "edit",
            str(issue_num),
            "--repo",
            repo,
            "--body-file",
            str(tmp_path),
            "--remove-label",
            "stage:ideation",
            "--add-label",
            "stage:ready",
        ]
        subprocess.run(cmd, check=True)
        logger.info(f"GitHub Issue #{issue_num} を stage:ready へ昇格しました。")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # 2. サテライトの tasks.md への同期
    if project_dir and project_key:
        tasks_path = project_dir / "docs" / "tasks.md"
        sync_to_tasks_md(tasks_path, project_key, issue_num, title, priority)
    else:
        logger.warning(
            "サテライトディレクトリまたはプロジェクトキーが解決できなかったため、tasks.md 同期をスキップしました。"
        )

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue 壁打ち完了・stage:ready 昇格ツール")
    parser.add_argument(
        "--project",
        "-p",
        required=True,
        help="対象プロジェクト名または github_repo（例: env_builder, xzyozi/env_builder）",
    )
    parser.add_argument("--issue", "-i", type=int, required=True, help="対象 Issue 番号")
    parser.add_argument(
        "--approach",
        "-a",
        type=int,
        choices=[1, 2],
        help="採用するアプローチ番号（1 または 2）。省略時はチェックボックス検出またはデフォルト案1",
    )
    parser.add_argument(
        "--task",
        "-t",
        action="append",
        help="確定実装タスク（複数指定可能）。省略時はデフォルトタスクを生成",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="実際の更新を行わずプレビューを表示する"
    )

    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parent.parent

    success = promote_issue(
        root_dir=root_dir,
        target_project=args.project,
        issue_num=args.issue,
        approach=args.approach,
        concrete_tasks=args.task,
        dry_run=args.dry_run,
    )
    if not success:
        exit(1)


if __name__ == "__main__":
    main()

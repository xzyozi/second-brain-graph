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

from tools.issue_spec_manager import fetch_remote_issue, sync_spec_for_task

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
    """GitHub CLI で Issue 情報を取得する（issue_spec_manager に処理を集約）."""
    data = fetch_remote_issue(repo, issue_num, fields=["number", "title", "body", "labels"])
    if data is None:
        raise RuntimeError(f"Issue #{issue_num} の取得に失敗しました ({repo})")
    return data


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


def update_target_files_section(body: str, target_files: List[str]) -> str:
    """## 4. 編集対象ファイル (Target Files) セクションを指定された target_files で置換・更新する."""
    new_files_block = "\n".join(f"- `{tf.strip('` ')}`" for tf in target_files)
    new_sec4 = f"## 4. 編集対象ファイル (Target Files)\n{new_files_block}\n\n"

    sec4_pattern = re.compile(
        r"(## 4\. 編集対象ファイル\s*\(Target Files\).*?\n)(?=## [5-8]\.|\Z)",
        re.DOTALL,
    )
    if sec4_pattern.search(body):
        return sec4_pattern.sub(new_sec4, body)
    else:
        sec5_pattern = re.compile(r"(?=## 5\.)")
        if sec5_pattern.search(body):
            return sec5_pattern.sub(new_sec4, body)
        return body.rstrip() + f"\n\n{new_sec4}"


def update_execution_steps_section(body: str, concrete_tasks: List[str]) -> str:
    """## 3. 段階的実装手順 (Step-by-step Execution) セクションに確定タスクを展開・更新する."""
    tasks_lines: List[str] = []
    for t in concrete_tasks:
        cleaned = re.sub(r"^\s*-\s*(\[[ xX]\]\s*)?", "", t).strip()
        if cleaned:
            tasks_lines.append(f"- [ ] {cleaned}")
    if not tasks_lines:
        return body

    tasks_block = "\n".join(tasks_lines)
    new_sec3 = f"## 3. 段階的実装手順 (Step-by-step Execution)\n{tasks_block}\n\n"

    sec3_pattern = re.compile(
        r"(## 3\. 段階的実装手順\s*\(Step-by-step Execution\).*?\n)(?=## [4-8]\.|\Z)",
        re.DOTALL,
    )
    if sec3_pattern.search(body):
        return sec3_pattern.sub(new_sec3, body)
    else:
        sec4_pattern = re.compile(r"(?=## 4\.)")
        if sec4_pattern.search(body):
            return sec4_pattern.sub(new_sec3, body)
        return body.rstrip() + f"\n\n{new_sec3}"


def generate_promoted_body(
    body: str,
    selected_approach: int,
    approaches: Dict[int, Dict[str, Any]],
    concrete_tasks: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
) -> str:
    """採用案を [x] にし、非採用案を退避し、確定タスク・Target Files を反映した stage:ready 用の Issue 本文を生成する."""
    sel = approaches.get(selected_approach)
    if not sel:
        raise ValueError(f"アプローチ 案{selected_approach} の情報が見つかりません。")

    rejected_approach = 2 if selected_approach == 1 else 1
    rej = approaches.get(rejected_approach)

    # 1. 起票ステータス更新
    body_updated = re.sub(
        r"-\s*\*\*起票ステータス\*\*:\s*.*",
        "- **起票ステータス**: `stage:ready` (方針確定・tasks.md 登録完了)",
        body,
    )

    # 2. セクション2のチェックボックス更新（採用案を [x] に置換）
    for num in [1, 2]:
        chk_char = "x" if num == selected_approach else " "
        body_updated = re.sub(
            rf"^-\s*\[[ xX]\]\s*(\*\*案\s*{num}.*)$",
            rf"- [{chk_char}] \1",
            body_updated,
            flags=re.MULTILINE,
        )

    # 3. 確定実装タスクの反映 (Step-by-step Execution への展開)
    if concrete_tasks:
        body_updated = update_execution_steps_section(body_updated, concrete_tasks)

    # 4. 編集対象ファイル (Target Files) の更新
    if target_files:
        body_updated = update_target_files_section(body_updated, target_files)

    # 5. 確定実装タスク枠（旧フォーマット）が存在する場合は削除（tasks.md に一元化）
    body_updated = re.sub(
        r"\n*### 確定実装タスク \(Task Checklist\):.*?(?=\n## 3|\Z)",
        "",
        body_updated,
        flags=re.DOTALL,
    )

    # 4. セクション7（対象外）に不採用案を退避
    if rej:
        non_goal_entry = f"- **案 {rejected_approach} ({rej['title']})**: 案{selected_approach}を採用したため今回はスコープ外。"
        sec7_pattern = re.compile(
            r"(## 7\. 対象外 \(Non-Goals\).*?\n)(?=## 8\. 完了定義)",
            re.DOTALL,
        )
        sec7_match = sec7_pattern.search(body_updated)
        if sec7_match:
            cur_sec7 = sec7_match.group(1)
            cleaned_sec7 = re.sub(
                r"- （※壁打ちで採用されなかった代替アプローチはここに記録してスコープ外を明確化）\n?",
                "",
                cur_sec7,
            )
            if non_goal_entry not in cleaned_sec7:
                cleaned_sec7 = cleaned_sec7.rstrip() + f"\n{non_goal_entry}\n\n"
            body_updated = sec7_pattern.sub(cleaned_sec7, body_updated)

    # 5. フッターの更新
    footer_pattern = re.compile(r"---*\s*\n\*※ 本 Issue は.*?\*\s*$", re.DOTALL)
    new_footer = f"---\n*※ 本 Issue は壁打ちにより案{selected_approach}が採用され、tasks.md に登録されて stage:ready に昇格しました。*"
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
    issue_tag = f"issue:#{issue_num}"

    # 既存登録チェック & 昇格
    if issue_tag in content:
        lines = content.splitlines()
        updated_lines: list[str] = []
        promoted = False
        for line in lines:
            if issue_tag in line:
                if "stage:ideation" in line:
                    line = line.replace("stage:ideation", "stage:ready")
                    promoted = True
                elif "stage:ready" not in line:
                    line = re.sub(r"(-->|\Z)", "stage:ready \\1", line)
                    promoted = True
            updated_lines.append(line)

        if promoted:
            updated_content = "\n".join(updated_lines) + "\n"
            tasks_path.write_text(updated_content, encoding="utf-8")
            logger.info(f"tasks.md の既存タスクを stage:ready に昇格しました: Issue #{issue_num}")
            return True

        logger.info(
            f"tasks.md には既に Issue #{issue_num} が登録されており、既に stage:ready です。"
        )
        return False

    # 最大タスク番号の検出
    existing_nums = [int(m.group(1)) for m in re.finditer(rf"\[{project_key}-(\d{{4}})\]", content)]
    next_num = max(existing_nums, default=0) + 1
    task_id = f"{project_key}-{next_num:04d}"

    new_line = f"- [ ] [{task_id}] {title} <!-- priority:{priority} {issue_tag} stage:ready -->\n"

    if content.endswith("\n"):
        updated_content = content + new_line
    else:
        updated_content = content + "\n" + new_line

    tasks_path.write_text(updated_content, encoding="utf-8")
    logger.info(f"tasks.md に追加しました (stage:ready): [{task_id}] {title}")
    return True


def promote_issue(
    root_dir: Path,
    target_project: str,
    issue_num: int,
    approach: Optional[int] = None,
    concrete_tasks: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
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
    new_body = generate_promoted_body(
        body,
        selected_approach,
        approaches,
        concrete_tasks=concrete_tasks,
        target_files=target_files,
    )
    priority, theme = extract_priority_and_theme(body, labels)

    if dry_run:
        print("=" * 60)
        print(f"[DRY-RUN] Promoted Body for Issue #{issue_num} (Approach {selected_approach}):")
        print("=" * 60)
        print(new_body)
        print("=" * 60)
        logger.info(f"[DRY-RUN] tasks.md 追記プレビュー: priority={priority}, theme={theme}")
        if project_dir and project_key:
            sync_spec_for_task(
                project_dir=project_dir,
                issue_num=issue_num,
                title=title,
                body=new_body,
                task_id=f"{project_key}-XXXX",
                overwrite=True,
                dry_run=True,
            )
        return True

    # 1. GitHub Issue の更新
    tmp_path = root_dir / f"tmp_promote_{issue_num}.md"
    try:
        tmp_path.write_text(new_body, encoding="utf-8")
        remove_labels = [
            lbl
            for lbl in ["stage:ideation", "stage:done", "stage:in-progress"]
            if lbl in label_names
        ]
        if not remove_labels:
            remove_labels = ["stage:ideation"]

        cmd = [
            "gh",
            "issue",
            "edit",
            str(issue_num),
            "--repo",
            repo,
            "--body-file",
            str(tmp_path),
        ]
        for rl in remove_labels:
            cmd.extend(["--remove-label", rl])
        cmd.extend(["--add-label", "stage:ready"])

        subprocess.run(cmd, check=True)
        logger.info(f"GitHub Issue #{issue_num} を stage:ready へ昇格しました。")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # 2. サテライトの tasks.md への同期および docs/issues/<TASK_ID>.md の生成・更新
    if project_dir and project_key:
        tasks_path = project_dir / "docs" / "tasks.md"
        sync_to_tasks_md(tasks_path, project_key, issue_num, title, priority)
        spec_path = sync_spec_for_task(
            project_dir=project_dir,
            issue_num=issue_num,
            title=title,
            body=new_body,
            overwrite=True,
        )
        if spec_path:
            logger.info(f"仕様書を自動同期しました: docs/issues/{spec_path.name}")
    else:
        logger.warning(
            "サテライトディレクトリまたはプロジェクトキーが解決できなかったため、tasks.md 同期および仕様書生成をスキップしました。"
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
        "--target-file",
        "-f",
        action="append",
        help="編集対象ファイル（複数指定可能）。省略時は Issue 本文の既存リストを維持",
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
        target_files=args.target_file,
        dry_run=args.dry_run,
    )
    if not success:
        exit(1)


if __name__ == "__main__":
    main()

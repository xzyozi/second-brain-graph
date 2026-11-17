"""promote_issue.py - Issue 壁打ち完了・stage:ready 昇格ツール.

起票された stage:ideation の Issue に対し、選定された修正方針（案1/案2）を確定タスクへ展開し、
非採用案を Non-Goals に退避した上で GitHub Issue を更新し stage:ready に昇格させる。
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.backends.jev_adapter import verify_plan_conformance
from tools.workspace.github_issues import fetch_remote_issue
from tools.workspace.metadata_store import resolve_target_spec

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("promote_issue")

MOTHER_PROJECT_KEY = "SBOS"
MOTHER_GITHUB_REPO = "xzyozi/second-brain-graph"
_MOTHER_ALIASES = frozenset(
    {
        "sbos",
        "second-brain-graph",
        "xzyozi/second-brain-graph",
        "mother",
    }
)
_REQUIRED_SECTIONS = (1, 2, 3, 4, 8)
_TEMPLATE_PLACEHOLDERS = (
    "path/to/file.py",
    "〇〇",
    "[最小限・安全な改修アプローチ",
    "[代替アプローチ",
)


def _is_mother_cwd(cwd: Path, root_dir: Path) -> bool:
    """CWD が母艦配下であり、かつ projects/<satellite> 配下でない場合に True を返す."""
    try:
        resolved_cwd = cwd.resolve()
        resolved_root = root_dir.resolve()
    except OSError:
        return False

    if not resolved_cwd.is_relative_to(resolved_root):
        return False
    projects_dir = resolved_root / "projects"
    if resolved_cwd.is_relative_to(projects_dir):
        return False
    return True


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
    # 母艦エイリアス解決は metadata_store を汚さず promote_issue 内に閉じる
    if project_name_or_repo.strip().lower() in _MOTHER_ALIASES:
        return MOTHER_PROJECT_KEY, root_dir, MOTHER_GITHUB_REPO

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
    """GitHub CLI で Issue 情報を取得する（github_issues に処理を集約）."""
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
        "- **起票ステータス**: `stage:ready` (方針確定済み)",
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
    new_footer = f"---\n*※ 本 Issue は壁打ちにより案{selected_approach}が採用され、stage:ready に昇格しました。*"
    if footer_pattern.search(body_updated):
        body_updated = footer_pattern.sub(new_footer, body_updated)
    else:
        body_updated = body_updated.rstrip() + f"\n\n{new_footer}\n"

    return body_updated


def _extract_section(body: str, section_num: int) -> Tuple[bool, str]:
    """指定番号セクションの有無と本文（見出し行を除く）を抽出する."""
    header_match = re.search(
        rf"^##\s*{section_num}(?:\.|\s|$).*$",
        body,
        flags=re.MULTILINE,
    )
    if not header_match:
        return False, ""

    after_header = body[header_match.end() :]
    next_match = re.search(
        r"^(?:##\s*\d+(?:\.|\s|$)|---\s*\n\*※)",
        after_header,
        flags=re.MULTILINE,
    )
    section_body = after_header[: next_match.start()] if next_match else after_header
    return True, section_body.strip()


def _extract_target_files_from_body(body: str) -> List[str]:
    """## 4. 編集対象ファイル セクションから対象ファイルパス一覧を抽出する."""
    has_sec4, sec4_body = _extract_section(body, 4)
    if not has_sec4 or not sec4_body:
        return []

    files: List[str] = []
    for raw_line in sec4_body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        item_match = re.match(r"^[-*]\s+(.+)$", line)
        if not item_match:
            continue
        content = item_match.group(1).strip()
        tick_match = re.search(r"`([^`]+)`", content)
        if tick_match:
            candidate = tick_match.group(1).strip()
        else:
            candidate = re.sub(r"[（(][^）)]*[）)]\s*$", "", content).strip()
        if candidate and candidate not in files:
            files.append(candidate)
    return files


def _extract_selected_approach_text(sec2_body: str, selected_approach: int) -> str:
    """## 2. から採用されたアプローチ（案1 または 案2）の記述のみを抽出する."""
    lines = sec2_body.splitlines()
    captured: List[str] = []
    in_selected = False

    for line in lines:
        if re.match(rf"^-\s*\[[ xX]\]\s*\*\*案\s*{selected_approach}\b", line):
            in_selected = True
            captured.append(line.strip())
            continue
        if in_selected:
            if re.match(r"^-\s*\[[ xX]\]\s*\*\*案\s*[12]\b", line) or (
                line.strip() and not line.startswith((" ", "\t"))
            ):
                break
            if line.strip():
                captured.append(line.strip())

    return "\n".join(captured).strip()


def validate_promoted_structure(body: str) -> List[str]:
    """昇格前 Issue 本文の最小限構造チェックを行い、不備メッセージ一覧を返す."""
    errors: List[str] = []
    for sec_num in _REQUIRED_SECTIONS:
        found, _ = _extract_section(body, sec_num)
        if not found:
            errors.append(f"必須セクション ## {sec_num}. が見つかりません。")

    extracted_files = _extract_target_files_from_body(body)
    if not extracted_files:
        errors.append("## 4. 編集対象ファイル (Target Files) に有効なパスがありません。")

    for placeholder in _TEMPLATE_PLACEHOLDERS:
        if placeholder in body:
            errors.append(f"テンプレート初期値 '{placeholder}' が未置換のまま残っています。")

    return errors


def _format_gate_issue_id(project_key: Optional[str], repo: str, issue_num: int) -> str:
    """JEV 検問ログ用の Issue 識別子を組み立てる."""
    if project_key == MOTHER_PROJECT_KEY or repo.lower() == MOTHER_GITHUB_REPO:
        return f"second-brain-graph#{issue_num}"
    if project_key:
        return f"{project_key}-{issue_num:04d}"
    return f"{repo}#{issue_num}"


def run_jev_exit_gate(
    gate_issue_id: str,
    promoted_body: str,
    selected_approach: int,
    pipeline: Optional[Any] = None,
) -> Tuple[bool, str]:
    """昇格直前の確定本文に対して JEV 計画適合性検問を実施する."""
    _, sec1_body = _extract_section(promoted_body, 1)
    _, sec2_body = _extract_section(promoted_body, 2)
    _, sec3_body = _extract_section(promoted_body, 3)
    _, sec8_body = _extract_section(promoted_body, 8)

    selected_text = _extract_selected_approach_text(sec2_body, selected_approach)
    instruction_parts = [p for p in (sec1_body, selected_text) if p]
    instruction = "\n\n".join(instruction_parts)

    plan_parts = []
    if sec3_body:
        plan_parts.append(f"## 3. 段階的実装手順\n{sec3_body}")
    if sec8_body:
        plan_parts.append(f"## 8. 完了定義\n{sec8_body}")
    impl_plan = "\n\n".join(plan_parts)

    target_files = _extract_target_files_from_body(promoted_body)
    is_valid, _confidence, detail = verify_plan_conformance(
        issue_id=gate_issue_id,
        instruction=instruction,
        impl_plan=impl_plan,
        target_files=target_files,
        pipeline=pipeline,
    )
    if not is_valid:
        preview = sec3_body[:200].replace("\n", " ") if sec3_body else "(手順なし)"
        logger.error(
            f"[JEV EXIT GATE REJECTED] ({gate_issue_id}) {detail}\n"
            f"  - 抽出 Target Files: {target_files}\n"
            f"  - 抽出実装手順概要: {preview}\n"
            "  - 誤検知であり昇格を続行する場合は '--skip-jev' オプションを指定して再実行してください。"
        )
        return False, detail

    logger.info(f"[JEV EXIT GATE] ({gate_issue_id}) {detail}")
    return True, detail


def promote_issue(
    root_dir: Path,
    target_project: str,
    issue_num: int,
    approach: Optional[int] = None,
    concrete_tasks: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
    dry_run: bool = False,
    skip_jev: bool = False,
) -> bool:
    """Issue を stage:ready へ昇格するメイン関数."""
    project_key, _project_dir, repo = resolve_project_info(root_dir, target_project)
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

    # 構造チェック (Python 決定論的検査)
    structure_errors = validate_promoted_structure(new_body)
    if structure_errors:
        for err in structure_errors:
            logger.error(f"[STRUCTURE CHECK FAILED] {err}")
        return False

    # JEV 出口検問 (--dry-run 時も判定結果確認のため実行)
    gate_issue_id = _format_gate_issue_id(project_key, repo, issue_num)
    if skip_jev:
        jev_summary = "skipped (--skip-jev)"
        logger.info(f"[JEV EXIT GATE] ({gate_issue_id}) {jev_summary}")
    else:
        jev_passed, jev_summary = run_jev_exit_gate(gate_issue_id, new_body, selected_approach)
        if not jev_passed:
            return False

    if dry_run:
        print("=" * 60)
        print(f"[DRY-RUN] Promoted Body for Issue #{issue_num} (Approach {selected_approach}):")
        print(f"[DRY-RUN] JEV Exit Gate: {jev_summary}")
        print("=" * 60)
        print(new_body)
        print("=" * 60)
        logger.info(
            f"[DRY-RUN] GitHub Issue #{issue_num} を stage:ready に昇格予定 (repo={repo}, title={title})"
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

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue 壁打ち完了・stage:ready 昇格ツール（URL、タスクID、番号、CWD判定対応）"
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="対象 Issue URL、タスクID（例: TFG-0005）、または Issue 番号（位置引数指定可能）",
    )
    parser.add_argument(
        "--project",
        "-p",
        required=False,
        help="対象プロジェクト名または github_repo（例: env_builder, xzyozi/env_builder）。URLやサテライトCWDから自動判定可能",
    )
    parser.add_argument(
        "--issue",
        "-i",
        type=int,
        required=False,
        help="対象 Issue 番号（位置引数 target または URL/タスクID から自動判定可能）",
    )
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
    parser.add_argument(
        "--skip-jev",
        action="store_true",
        help="JEV 出口検問（計画適合性チェック）をスキップして昇格する",
    )

    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parent.parent

    target_input = args.target or (str(args.issue) if args.issue is not None else None)
    if not target_input:
        parser.error(
            "対象が指定されていません。位置引数に Issue URL、タスクID、または --issue を指定してください。"
        )

    cwd = Path.cwd()
    resolved = resolve_target_spec(
        target_input,
        project_hint=args.project,
        cwd=cwd,
        project_root=root_dir,
    )

    target_project = args.project or resolved.get("github_repo") or resolved.get("project_key")
    issue_num = args.issue or resolved.get("issue_number")

    if not target_project and issue_num and _is_mother_cwd(cwd, root_dir):
        target_project = MOTHER_GITHUB_REPO

    if not target_project:
        logger.error(
            f"プロジェクトを特定できませんでした。'--project' を指定するか、レジストリに登録された URL/サテライトディレクトリから実行してください。(target: {target_input})"
        )
        sys.exit(1)

    if not issue_num:
        logger.error(
            f"Issue 番号を特定できませんでした。'--issue' を指定するか、URL またはタスクID を指定してください。(target: {target_input})"
        )
        sys.exit(1)

    success = promote_issue(
        root_dir=root_dir,
        target_project=target_project,
        issue_num=issue_num,
        approach=args.approach,
        concrete_tasks=args.task,
        target_files=args.target_file,
        dry_run=args.dry_run,
        skip_jev=args.skip_jev,
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

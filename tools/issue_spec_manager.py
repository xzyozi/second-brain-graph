"""issue_spec_manager.py - サテライトタスク仕様書 (docs/issues/<TASK_ID>.md) のライフサイクル管理モジュール.

【責務と設計原則】
1. GitHub Issue の起票・昇格・定周期同期時に docs/issues/<TASK_ID>.md を生成・更新・自己修復する。
2. サテライトの Git 履歴およびローカル作業ツリーにおいて、常に tasks.md と 1:1 で整合した仕様書を維持する。
3. 単一責任の原則に基づき、独立した再利用可能ヘルパー関数を提供する。
4. 標準出力を汚染しないよう、ロギングは sys.stderr に集約する。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ロガー設定: 標準出力を汚さないよう sys.stderr に出力（ユーザーグローバルルール準拠）
logger = logging.getLogger("issue_spec_manager")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# tasks.md のメタデータ抽出用正規表現（SSOT）
RE_TASK_ID = re.compile(r"-\s*\[[ xX/]?\]\s*\[([A-Za-z0-9_-]+)\]")
RE_ISSUE_NUM = re.compile(r"issue:#(\d+)")


@dataclass
class IssueSpecData:
    """Issue仕様書生成に必要なDTO."""

    task_id: str
    title: str
    body: str


def parse_task_line_metadata(line: str) -> tuple[str, int] | tuple[None, None]:
    """tasks.md の1行から (task_id, issue_num) を抽出する."""
    m_task = RE_TASK_ID.search(line)
    m_issue = RE_ISSUE_NUM.search(line)
    if m_task and m_issue:
        return m_task.group(1), int(m_issue.group(1))
    return None, None


def format_issue_spec_content(task_id: str, title: str, body: str) -> str:
    """Issue 本文から仕様書 Markdown を整形する.

    先頭に `# [{task_id}] {title}` を適切に配置・補正する。
    """
    clean_body = body.strip()
    tag_prefix = f"[{task_id}]"

    # 先頭がレベル1見出し (# 見出し) で始まっている場合
    if re.match(r"^#\s+[^#]", clean_body):
        first_line, _, rest = clean_body.partition("\n")
        h_text = re.sub(r"^#\s+", "", first_line).strip()
        if tag_prefix not in h_text:
            h_text = f"{tag_prefix} {h_text}".strip()
        new_first_line = f"# {h_text}"
        rest_stripped = rest.strip()
        if rest_stripped:
            return f"{new_first_line}\n\n{rest_stripped}\n"
        return f"{new_first_line}\n"

    # 先頭がレベル1見出しでない場合（## から始まる場合、または見出しなし）
    clean_title = title.strip()
    if tag_prefix not in clean_title:
        clean_title = f"{tag_prefix} {clean_title}".strip()
    if clean_body:
        return f"# {clean_title}\n\n{clean_body}\n"
    return f"# {clean_title}\n"


def write_issue_spec(
    project_dir: Path,
    task_id: str | None = None,
    title: str | None = None,
    body: str | None = None,
    spec: IssueSpecData | None = None,
    overwrite: bool = True,
    dry_run: bool = False,
) -> Path:
    """サテライトの docs/issues/<TASK_ID>.md を生成または更新する."""
    if spec is None:
        if task_id is None or title is None or body is None:
            raise ValueError("spec または (task_id, title, body) のいずれかを指定してください。")
        spec = IssueSpecData(task_id=task_id, title=title, body=body)

    issues_dir = project_dir / "docs" / "issues"
    spec_path = issues_dir / f"{spec.task_id}.md"

    if spec_path.exists() and not overwrite:
        logger.debug(f"仕様書は既に存在します (上書きスキップ): {spec_path}")
        return spec_path

    content = format_issue_spec_content(spec.task_id, spec.title, spec.body)

    if dry_run:
        logger.info(f"[DRY-RUN] 仕様書作成予定: {spec_path}")
        return spec_path

    issues_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(content, encoding="utf-8")
    logger.info(f"仕様書を保存しました: {spec_path.name}")
    return spec_path


def get_task_id_from_tasks_md(tasks_path: Path, issue_num: int) -> str | None:
    """tasks.md から指定 Issue 番号に対応する task_id を取得する."""
    if not tasks_path.is_file():
        return None

    try:
        content = tasks_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if f"issue:#{issue_num}" in line:
                t_id, num = parse_task_line_metadata(line)
                if t_id and num == issue_num:
                    return t_id
    except Exception as e:
        logger.warning(f"tasks.md 解析失敗 ({tasks_path}): {e}")

    return None


def fetch_remote_issue(
    repo: str, issue_num: int, fields: list[str] | None = None
) -> dict[str, Any] | None:
    """GitHub CLI で Issue の詳細を取得する."""
    if fields is None:
        fields = ["number", "title", "body", "labels", "state"]
    cmd = [
        "gh",
        "issue",
        "view",
        str(issue_num),
        "--repo",
        repo,
        "--json",
        ",".join(fields),
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return json.loads(res.stdout)
    except Exception as e:
        logger.warning(f"Issue #{issue_num} の取得に失敗しました ({repo}): {e}")
        return None


# 互換用エイリアス
fetch_remote_issue_body = fetch_remote_issue


def sync_spec_for_task(
    project_dir: Path,
    issue_num: int,
    title: str,
    body: str,
    task_id: str | None = None,
    overwrite: bool = True,
    dry_run: bool = False,
) -> Path | None:
    """プロジェクト内の tasks.md と整合を取りながら docs/issues/<TASK_ID>.md を安全に自動生成・更新する高水準ファサード.

    task_id が未指定の場合は tasks.md から issue_num を元に自動解決する。
    解決できない場合は安全に warning を出して None を返却する。
    """
    if not task_id:
        tasks_path = project_dir / "docs" / "tasks.md"
        task_id = get_task_id_from_tasks_md(tasks_path, issue_num)

    if not task_id:
        logger.warning(
            f"task_id を特定できなかったため仕様書同期をスキップしました: Issue #{issue_num} ({project_dir.name})"
        )
        return None

    spec = IssueSpecData(task_id=task_id, title=title, body=body)
    return write_issue_spec(
        project_dir=project_dir,
        spec=spec,
        overwrite=overwrite,
        dry_run=dry_run,
    )


def self_heal_missing_specs(
    project_dir: Path,
    repo: str,
    issues: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> list[str]:
    """サテライトの tasks.md を走査し、欠落している docs/issues/<TASK_ID>.md を自動自己修復する.

    Returns:
        修復（生成）された task_id の一覧
    """
    tasks_path = project_dir / "docs" / "tasks.md"
    if not tasks_path.is_file():
        return []

    issues_dir = project_dir / "docs" / "issues"
    content = tasks_path.read_text(encoding="utf-8")

    # Issue 番号から Issue 情報を引くためのマップを準備
    issue_map: dict[int, dict[str, Any]] = {}
    if issues:
        for iss in issues:
            if "number" in iss:
                issue_map[iss["number"]] = iss

    healed_tasks: list[str] = []

    for line in content.splitlines():
        task_id, issue_num = parse_task_line_metadata(line)
        if not task_id or not issue_num:
            continue

        spec_file = issues_dir / f"{task_id}.md"
        if spec_file.exists():
            continue

        # 欠落を検知 -> GitHub から取得
        logger.info(f"仕様書欠落を検知: {task_id} (Issue #{issue_num}) - 自動修復を開始します")
        iss_data = issue_map.get(issue_num)
        if not iss_data:
            iss_data = fetch_remote_issue_body(repo, issue_num)
            if iss_data:
                issue_map[issue_num] = iss_data

        if not iss_data:
            logger.warning(
                f"Issue #{issue_num} の情報を取得できなかったため、{task_id} の自己修復をスキップします"
            )
            continue

        title = iss_data.get("title", f"Task {task_id}")
        body = iss_data.get("body", "")

        spec = IssueSpecData(task_id=task_id, title=title, body=body)
        write_issue_spec(
            project_dir=project_dir,
            spec=spec,
            overwrite=True,
            dry_run=dry_run,
        )
        healed_tasks.append(task_id)

    if healed_tasks:
        logger.info(
            f"自己修復完了: 合計 {len(healed_tasks)} 件の仕様書を配置しました: {healed_tasks}"
        )

    return healed_tasks

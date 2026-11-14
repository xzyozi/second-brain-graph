"""github_issues.py - GitHub Issues 取得・正規化・モックテスト共通基盤.

【責務と設計原則】
1. 各ツールに分散していた `gh issue view` / `gh issue list` 呼び出しを集約し、
   GitHub Issues を唯一の正本（SSOT）として参照するための単一窓口を提供する。
2. `normalize_issue_record` により取得データを正規化し、`{PROJECT_KEY}-{NUM:04d}` の
   決定論的 `task_id` や `stage:*` ラベル抽出を統一する。
3. オフライン単体・結合テスト向けに、環境変数 (`SBOS_GITHUB_ISSUES_FIXTURE`) および
   インメモリコンテキスト (`use_issue_fixture` / `set_issue_fixture_data`) による
   モック差し替え経路を提供する。
4. 標準出力を汚染しないよう、ロギングは sys.stderr に集約する。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from tools.workspace.metadata_store import format_task_id

logger = logging.getLogger("github_issues")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

FIXTURE_ENV_VAR = "SBOS_GITHUB_ISSUES_FIXTURE"
DEFAULT_ISSUE_FIELDS: tuple[str, ...] = (
    "number",
    "title",
    "body",
    "labels",
    "state",
    "url",
    "createdAt",
    "updatedAt",
)

FixturePayload = list[dict[str, Any]] | dict[str, list[dict[str, Any]]] | None
_IN_MEMORY_FIXTURE: FixturePayload = None


def set_issue_fixture_data(fixture: FixturePayload) -> None:
    """テスト・ドライラン用のインメモリ GitHub Issue フィクスチャを設定する."""
    global _IN_MEMORY_FIXTURE
    _IN_MEMORY_FIXTURE = deepcopy(fixture) if fixture is not None else None


@contextmanager
def use_issue_fixture(
    fixture: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
) -> Iterator[None]:
    """指定ブロック内だけインメモリ Issue フィクスチャを有効化するコンテキストマネージャ."""
    global _IN_MEMORY_FIXTURE
    previous = _IN_MEMORY_FIXTURE
    _IN_MEMORY_FIXTURE = deepcopy(fixture)
    try:
        yield
    finally:
        _IN_MEMORY_FIXTURE = previous


def _select_repo_issues_from_payload(payload: Any, repo: str) -> list[dict[str, Any]]:
    """フィクスチャペイロード (list または repo->list dict) から対象 repo の Issue 配列を取り出す."""
    if isinstance(payload, list):
        return [deepcopy(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if repo in payload and isinstance(payload[repo], list):
            return [deepcopy(item) for item in payload[repo] if isinstance(item, dict)]
        if "*" in payload and isinstance(payload["*"], list):
            return [deepcopy(item) for item in payload["*"] if isinstance(item, dict)]
        return []
    return []


def _load_fixture_issues(repo: str) -> list[dict[str, Any]] | None:
    """フィクスチャモードが有効な場合は Issue 配列を返し、通常モードでは None を返す."""
    if _IN_MEMORY_FIXTURE is not None:
        return _select_repo_issues_from_payload(_IN_MEMORY_FIXTURE, repo)

    fixture_path_str = os.environ.get(FIXTURE_ENV_VAR, "").strip()
    if not fixture_path_str:
        return None

    fixture_path = Path(fixture_path_str)
    if not fixture_path.is_file():
        logger.warning(f"フィクスチャファイルが見つかりません ({FIXTURE_ENV_VAR}={fixture_path})")
        return []

    try:
        raw_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        return _select_repo_issues_from_payload(raw_payload, repo)
    except Exception as exc:
        logger.warning(f"フィクスチャ JSON の読み込みに失敗しました ({fixture_path}): {exc}")
        return []


def extract_label_names(issue: dict[str, Any]) -> list[str]:
    """GitHub Issue レコードからラベル名のリストを抽出する."""
    raw_labels = issue.get("labels")
    if not isinstance(raw_labels, list):
        raw_names = issue.get("label_names")
        if isinstance(raw_names, list):
            return [str(name) for name in raw_names if isinstance(name, str)]
        return []

    names: list[str] = []
    for item in raw_labels:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        elif isinstance(item, str) and item:
            names.append(item)
    return names


def extract_stage_label(issue: dict[str, Any]) -> str | None:
    """Issue のラベルから `stage:*` プレフィックスのラベルを抽出する."""
    for name in extract_label_names(issue):
        if name.startswith("stage:"):
            return name
    return None


def normalize_issue_record(
    raw: dict[str, Any],
    project_key: str | None = None,
) -> dict[str, Any]:
    """GitHub Issue の生 JSON を正規化し、共通メタデータ (`label_names`, `stage`, `task_id`) を補完する."""
    normalized = dict(raw)
    raw_num = raw.get("number")
    issue_num: int | None = None
    if isinstance(raw_num, int) and not isinstance(raw_num, bool) and raw_num > 0:
        issue_num = raw_num
    elif isinstance(raw_num, str) and raw_num.isdigit():
        parsed_num = int(raw_num)
        if parsed_num > 0:
            issue_num = parsed_num

    if issue_num is not None:
        normalized["number"] = issue_num

    normalized["title"] = str(raw.get("title") or "")
    normalized["body"] = str(raw.get("body") or "")
    normalized["state"] = str(raw.get("state") or "OPEN").upper()
    normalized["url"] = str(raw.get("url") or "")

    label_names = extract_label_names(raw)
    normalized["label_names"] = label_names
    if "labels" not in normalized or not isinstance(normalized["labels"], list):
        normalized["labels"] = [{"name": name} for name in label_names]

    normalized["stage"] = extract_stage_label(normalized)

    if project_key and issue_num is not None:
        try:
            normalized["task_id"] = format_task_id(project_key, issue_num)
        except ValueError:
            normalized["task_id"] = raw.get("task_id")
    else:
        normalized["task_id"] = raw.get("task_id")

    return normalized


_PRIORITY_VALUES = frozenset({"critical", "urgent", "high", "medium", "low"})


def _normalize_blocker_ref(token: str, project_key: str | None) -> str | None:
    """ブロッカー指定トークン (#123, 123, TFG-0001) を正規化する."""
    cleaned = token.strip().strip(",.;:)>")
    if not cleaned:
        return None
    if re.fullmatch(r"#?\d+", cleaned):
        num = int(cleaned.lstrip("#"))
        if num > 0 and project_key:
            try:
                return format_task_id(project_key, num)
            except ValueError:
                return f"#{num}"
        return f"#{num}" if num > 0 else None
    if re.fullmatch(r"[A-Za-z0-9_]+-\d+(?:-[A-Za-z])?", cleaned):
        parts = cleaned.split("-")
        parts[0] = parts[0].upper()
        if len(parts) == 2 and parts[1].isdigit():
            return f"{parts[0]}-{int(parts[1]):04d}"
        return "-".join(parts)
    return cleaned


def extract_issue_scoring_metadata(
    issue: dict[str, Any],
    project_key: str | None = None,
) -> dict[str, Any]:
    """GitHub Issue のラベル・本文・作成日時から優先度評価メタデータを抽出する."""
    label_names = extract_label_names(issue)
    body = str(issue.get("body") or "")

    # 1. priority (ラベル優先 -> 本文コメント/記述 -> デフォルト medium)
    priority = "medium"
    found_priority = False
    for lbl in label_names:
        low = lbl.strip().lower()
        if low.startswith("priority:"):
            val = low.split(":", 1)[1].strip()
            if val in _PRIORITY_VALUES:
                priority = val
                found_priority = True
                break
        elif low in _PRIORITY_VALUES:
            priority = low
            found_priority = True
            break

    if not found_priority:
        m_prio = re.search(
            r"(?:priority|優先度)\s*[:：]\s*(critical|urgent|high|medium|low)\b",
            body,
            re.IGNORECASE,
        )
        if m_prio:
            priority = m_prio.group(1).lower()

    # 2. estimate (ラベル優先 -> 本文コメント)
    estimate: str | None = None
    for lbl in label_names:
        low = lbl.strip().lower()
        if low.startswith("estimate:"):
            est_val = lbl.split(":", 1)[1].strip()
            if est_val:
                estimate = est_val
                break
    if estimate is None:
        m_est = re.search(r"\bestimate\s*:\s*([A-Za-z0-9_.]+)", body, re.IGNORECASE)
        if m_est:
            estimate = m_est.group(1).strip()

    # 3. added (本文コメント -> createdAt/created_at 先頭 YYYY-MM-DD)
    added: str | None = None
    m_added = re.search(r"\badded\s*:\s*(\d{4}-\d{2}-\d{2})\b", body, re.IGNORECASE)
    if m_added:
        added = m_added.group(1)
    else:
        created_raw = str(issue.get("createdAt") or issue.get("created_at") or "").strip()
        m_created = re.match(r"^(\d{4}-\d{2}-\d{2})", created_raw)
        if m_created:
            added = m_created.group(1)

    # 4. blockedby (blockedby:... コメントおよび Depends on / Blocked by 行)
    blockedby: list[str] = []
    seen_blockers: set[str] = set()

    def _add_blocker(tok: str) -> None:
        norm = _normalize_blocker_ref(tok, project_key)
        if norm and norm not in seen_blockers:
            seen_blockers.add(norm)
            blockedby.append(norm)

    for m_blk in re.finditer(r"\bblockedby\s*:\s*([^\s>]+)", body, re.IGNORECASE):
        raw_list = m_blk.group(1).replace("-->", "")
        for part in raw_list.split(","):
            _add_blocker(part)

    for line in body.splitlines():
        m_dep = re.match(
            r"^\s*(?:Depends\s+on|Blocked\s+by|依存)\s*[:：]\s*(.+)$",
            line,
            re.IGNORECASE,
        )
        if not m_dep:
            continue
        dep_text = m_dep.group(1)
        for m_ref in re.finditer(r"([A-Za-z0-9_]+-\d+(?:-[A-Za-z])?|#\d+)", dep_text):
            _add_blocker(m_ref.group(1))

    # 5. stage / completed
    stage = extract_stage_label(issue)
    if stage is None:
        m_stage = re.search(r"\bstage\s*:\s*([A-Za-z0-9:_-]+)", body, re.IGNORECASE)
        if m_stage:
            raw_stage = m_stage.group(1).strip().lower()
            stage = raw_stage if raw_stage.startswith("stage:") else f"stage:{raw_stage}"
        elif re.search(r"\bstage\s*:\s*draft\b", body, re.IGNORECASE):
            stage = "draft"

    state_str = str(issue.get("state") or "OPEN").upper()
    completed = state_str == "CLOSED" or (stage is not None and stage.lower() == "stage:done")
    on_hold = any(lbl.strip().lower() == "on-hold" for lbl in label_names)

    return {
        "priority": priority,
        "estimate": estimate,
        "added": added,
        "blockedby": blockedby,
        "stage": stage,
        "completed": completed,
        "on_hold": on_hold,
    }


def _finalize_issue(
    raw: dict[str, Any],
    *,
    project_key: str | None,
    normalize: bool,
) -> dict[str, Any]:
    """呼び出しオプションに応じて生辞書または正規化済み辞書を返す."""
    if normalize or project_key is not None:
        return normalize_issue_record(raw, project_key=project_key)
    return raw


def _run_gh_json(cmd: list[str], context_desc: str) -> Any:
    """`gh` CLI を実行して JSON をパースする."""
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        timeout=30,
    )
    if not res.stdout.strip():
        raise ValueError(f"Empty JSON output from gh CLI ({context_desc})")
    return json.loads(res.stdout)


def fetch_remote_issue(
    repo: str,
    issue_num: int,
    fields: list[str] | None = None,
    *,
    project_key: str | None = None,
    normalize: bool = False,
) -> dict[str, Any] | None:
    """GitHub CLI (またはフィクスチャ) から単一 Issue の詳細を取得する."""
    fixture_issues = _load_fixture_issues(repo)
    if fixture_issues is not None:
        for item in fixture_issues:
            if item.get("number") == issue_num:
                return _finalize_issue(item, project_key=project_key, normalize=normalize)
        return None

    target_fields = fields if fields is not None else list(DEFAULT_ISSUE_FIELDS)
    cmd = [
        "gh",
        "issue",
        "view",
        str(issue_num),
        "--repo",
        repo,
        "--json",
        ",".join(target_fields),
    ]
    try:
        data = _run_gh_json(cmd, f"{repo}#{issue_num}")
        if not isinstance(data, dict):
            logger.warning(f"Issue #{issue_num} の応答形式が不正です ({repo})")
            return None
        return _finalize_issue(data, project_key=project_key, normalize=normalize)
    except Exception as exc:
        logger.warning(f"Issue #{issue_num} の取得に失敗しました ({repo}): {exc}")
        return None


def fetch_remote_issues(
    repo: str,
    *,
    state: str = "all",
    limit: int = 200,
    labels: list[str] | None = None,
    fields: list[str] | None = None,
    project_key: str | None = None,
    normalize: bool = False,
) -> list[dict[str, Any]]:
    """GitHub CLI (またはフィクスチャ) から Issue 一覧を取得する."""
    fixture_issues = _load_fixture_issues(repo)
    if fixture_issues is not None:
        state_norm = (state or "all").strip().lower()
        required_labels = [lbl.lower() for lbl in (labels or []) if lbl]

        matched: list[dict[str, Any]] = []
        for item in fixture_issues:
            item_state = str(item.get("state") or "OPEN").strip().lower()
            if state_norm != "all" and item_state != state_norm:
                continue

            if required_labels:
                item_labels = {lbl.lower() for lbl in extract_label_names(item)}
                if not all(req in item_labels for req in required_labels):
                    continue

            matched.append(_finalize_issue(item, project_key=project_key, normalize=normalize))
            if limit > 0 and len(matched) >= limit:
                break
        return matched

    target_fields = fields if fields is not None else list(DEFAULT_ISSUE_FIELDS)
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        ",".join(target_fields),
    ]
    for lbl in labels or []:
        if lbl:
            cmd.extend(["--label", lbl])

    try:
        data = _run_gh_json(cmd, f"{repo} list")
        if not isinstance(data, list):
            logger.warning(f"GitHub Issues 一覧の応答形式が不正です ({repo})")
            return []
        return [
            _finalize_issue(item, project_key=project_key, normalize=normalize)
            for item in data
            if isinstance(item, dict)
        ]
    except Exception as exc:
        logger.warning(f"GitHub Issues 取得失敗 ({repo}): {exc}")
        return []

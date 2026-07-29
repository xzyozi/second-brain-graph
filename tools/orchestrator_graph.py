#!/usr/bin/env python3
"""tools/orchestrator_graph.py - LangGraph ベースの自律自己修復オーケストレーター.

正本設計書 (SBOS-BD-002 Rev.4.6, SBOS-DD-003 Rev.4.8, SBOS-PM-005 Rev.2.7) 準拠。
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

from langgraph.graph import END, StateGraph

from tools.aider_runner import get_git_diff, run_aider
from tools.llm_client import call_llm

logger = logging.getLogger("orchestrator_graph")


class OrchestratorState(TypedDict):
    """状態管理データ構造 (DD-003 §2)."""

    issue_id: str
    project_path: str  # projects/<name> の絶対パスまたは相対パス
    title: str
    description: str
    priority: str

    impl_plan: str  # Executor (plan_node) が生成した実装指示書
    aider_message: str  # code_node で Aider に渡す追加指示 (lint/test/review 指摘の蓄積)

    lint_result: Dict[str, Any]  # {"passed": bool, "issues": [...]}
    test_result: Dict[str, Any]  # {"passed": bool, "log": str}
    review_verdict: Literal["LGTM", "changes_requested", ""]
    review_comments: List[Dict[str, Any]]  # rdjson 準拠のコメント配列

    # PM-005: エラー分類器およびリトライ制御フィールド
    error_category: Optional[
        Literal["LINT_ERROR", "TEST_ERROR", "REVIEW_REJECTED", "LLM_TIMEOUT", "SYSTEM_ERROR"]
    ]
    last_error_message: Optional[str]

    round: int  # レビュー試行ラウンド数
    lint_round: int  # lint リトライ数
    test_round: int  # test リトライ数
    max_round: int  # タスクごとの最大試行許容数 (デフォルト 3)
    history: List[Dict[str, Any]]  # 各ノードの実行履歴


# ---------------------------------------------------------------------------
# 補助関数: メタデータ更新・履歴記録
# ---------------------------------------------------------------------------


def update_task_metadata(
    project_path: Union[str, Path],
    issue_id: str,
    round_num: int,
    status: str = "FAILED_B7",
    max_round: Optional[int] = None,
) -> None:
    """指定された Issue ID の直下に <!-- round:N max_round:M status:STATUS --> タグを更新・挿入する."""
    project_dir = Path(project_path)
    tasks_file = project_dir / "tasks.md"
    if not tasks_file.exists():
        logger.warning(f"tasks.md が見つかりません: {tasks_file}")
        return

    content = tasks_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    i = 0
    issue_pattern = re.compile(rf"^\s*-\s*\[([ xX])\]\s*({re.escape(issue_id)}):?(.*)$")

    while i < len(lines):
        line = lines[i]
        match = issue_pattern.match(line)
        if match:
            # タスク完了時のチェックボックス更新
            if status == "COMPLETED":
                line = f"- [x] {issue_id}:{match.group(3)}"
            new_lines.append(line)

            # 次の行が既存のコメントタグか確認
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("<!-- round:"):
                tag_line = lines[i + 1].strip()
                # max_round 保持
                m_match = re.search(r"max_round:(\d+)", tag_line)
                m_val = max_round if max_round is not None else (int(m_match.group(1)) if m_match else 3)
                new_tag = f"  <!-- round:{round_num} max_round:{m_val} status:{status} -->"
                new_lines.append(new_tag)
                i += 2  # 既存タグを置き換えたので2行進める
                continue
            else:
                m_val = max_round if max_round is not None else 3
                new_tag = f"  <!-- round:{round_num} max_round:{m_val} status:{status} -->"
                new_lines.append(new_tag)
                i += 1
                continue

        new_lines.append(line)
        i += 1

    tasks_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def record_execution_history(
    state: OrchestratorState,
    final_status: str,
    actual_round: int,
) -> None:
    """tools/.cache/execution_history.json へ実行完了・エスカレーション結果をアトミックに追記保存する."""
    cache_dir = Path("tools/.cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    history_file = cache_dir / "execution_history.json"

    data: Dict[str, Any] = {"records": []}
    if history_file.exists():
        try:
            data = json.loads(history_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"execution_history.json の読み込みに失敗しました: {e}")

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue_id": state.get("issue_id", ""),
        "project_path": state.get("project_path", ""),
        "final_status": final_status,
        "actual_round": actual_round,
        "max_round": state.get("max_round", 3),
        "lint_round": state.get("lint_round", 0),
        "test_round": state.get("test_round", 0),
        "review_round": state.get("round", 0),
        "error_category": state.get("error_category"),
        "history_summary": {
            "lint_passed": state.get("lint_result", {}).get("passed", False),
            "test_passed": state.get("test_result", {}).get("passed", False),
            "review_verdict": state.get("review_verdict", ""),
        },
    }

    if "records" not in data or not isinstance(data["records"], list):
        data["records"] = []
    data["records"].append(record)

    # アトミック書き込み
    tmp_file = history_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(history_file)


def _pipe_to_reviewdog(project_path: str, comments: List[Dict[str, Any]]) -> None:
    """Reviewdog 形式 (rdjson) の指摘を safely パイプ出力する."""
    if not comments:
        return
    rdjson = {
        "source": {"name": "reviewer-agent", "url": ""},
        "diagnostics": comments,
    }
    rdjson_str = json.dumps(rdjson)
    try:
        proc = subprocess.run(
            ["reviewdog", "-f=rdjson", "-diff=git diff HEAD"],
            input=rdjson_str,
            text=True,
            cwd=project_path,
            capture_output=True,
        )
        if proc.stdout:
            logger.info(f"[Reviewdog] Output: {proc.stdout}")
    except Exception as e:
        logger.debug(f"[Reviewdog] Execution skipped or unavailable: {e}")


def load_template(template_name: str) -> str:
    """tools/templates/<template_name>.md を読み込む. 不在時は標準フォールバック."""
    tmpl_path = Path("tools/templates") / f"{template_name}.md"
    if tmpl_path.exists():
        return tmpl_path.read_text(encoding="utf-8")

    defaults = {
        "planner": (
            "あなたは熟練のソフトウェアアーキテクトです。"
            "与えられた要件と課題に基づき、詳細な実装指示書を作成してください。"
        ),
        "reviewer": (
            "あなたは厳格なコードレビュアーです。"
            "実装指示書と diff を照らし合わせ、LGTM または changes_requested の判定と具体的な指摘を行ってください。"
        ),
    }
    return defaults.get(template_name, "")


# ---------------------------------------------------------------------------
# LangGraph ノード定義 (DD-003 §4)
# ---------------------------------------------------------------------------


def plan_node(state: OrchestratorState) -> OrchestratorState:
    """要件立案ノード: LiteLLM 経由で Planner に実装指示書を生成させる."""
    system_prompt = load_template("planner")
    user_prompt = (
        f"Issue ID: {state.get('issue_id')}\n"
        f"タイトル: {state.get('title')}\n"
        f"説明: {state.get('description')}\n"
        "上記を満たす実装指示書（実装手順、編集対象ファイル、考慮事項）を作成してください。"
    )
    res = call_llm("planner", system_prompt, user_prompt, expect_json=False)
    state["impl_plan"] = res.get("raw", "")
    return state


def code_node(state: OrchestratorState) -> OrchestratorState:
    """Aider 編集ノード: Aider CLI を呼び出して衛星コードを編集する."""
    instruction = f"## 実装指示書\n{state.get('impl_plan', '')}"
    if state.get("aider_message"):
        instruction += f"\n\n## 修正フィードバック\n{state['aider_message']}"

    project_dir = Path(state["project_path"])
    target_files: List[str] = []
    if project_dir.exists():
        for root, _, files in os.walk(project_dir):
            for f in files:
                if f.endswith((".py", ".json", ".md", ".toml")):
                    rel_path = os.path.relpath(os.path.join(root, f), state["project_path"])
                    target_files.append(rel_path)

    if not target_files:
        target_files = ["."]

    success = run_aider(
        instruction=instruction,
        target_files=target_files[:10],
        cwd=state["project_path"],
    )

    if not success:
        logger.warning(f"Aider の実行が不完全でした ({state['issue_id']})")
    return state


def lint_node(state: OrchestratorState) -> OrchestratorState:
    """Ruff 静的解析ノード: 失敗時は lint_round をインクリメントしフィードバックを蓄積."""
    result = subprocess.run(
        ["ruff", "check", "--output-format=json", "."],
        cwd=state["project_path"],
        capture_output=True,
        text=True,
    )
    issues = json.loads(result.stdout) if result.stdout.strip() else []
    passed = len(issues) == 0

    if not passed:
        state["lint_round"] = state.get("lint_round", 0) + 1
        state["error_category"] = "LINT_ERROR"
        issues_str = json.dumps(issues, ensure_ascii=False)
        state["aider_message"] = (
            state.get("aider_message", "") + "\n\n## Ruff静的解析指摘事項:\n" + issues_str
        ).strip()

    state["lint_result"] = {"passed": passed, "issues": issues}
    return state


def test_node(state: OrchestratorState) -> OrchestratorState:
    """pytest テストノード: 失敗時は test_round をインクリメントしフィードバックを蓄積."""
    report_path = Path(state["project_path"]) / ".pytest_report.json"
    subprocess.run(
        ["pytest", "--json-report", f"--json-report-file={report_path}"],
        cwd=state["project_path"],
        capture_output=True,
        text=True,
    )
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            passed = report.get("exitcode", 1) == 0
            log = json.dumps(report.get("tests", []))
        except Exception as e:
            passed = False
            log = f"pytestレポート読み込み失敗: {e}"
    else:
        passed = False
        log = "pytestレポートが生成されませんでした"

    if not passed:
        state["test_round"] = state.get("test_round", 0) + 1
        state["error_category"] = "TEST_ERROR"
        state["aider_message"] = (
            state.get("aider_message", "") + "\n\n## pytest失敗ログ:\n" + log
        ).strip()

    state["test_result"] = {"passed": passed, "log": log}
    return state


test_node.__test__ = False  # type: ignore[attr-defined]


def review_node(state: OrchestratorState) -> OrchestratorState:
    """レビューノード: Reviewer LLM による監査および Reviewdog へのパイプ."""
    diff = get_git_diff(state["project_path"])
    system_prompt = load_template("reviewer")
    user_prompt = (
        f"## 実装指示書\n{state.get('impl_plan', '')}\n\n"
        f"## 差分\n```diff\n{diff}\n```\n\n"
        '出力はJSON形式のみ: {"verdict": "LGTM または changes_requested", "comments": [...]}'
    )
    result = call_llm("reviewer", system_prompt, user_prompt, expect_json=True)
    verdict = result.get("verdict", "changes_requested")
    comments = result.get("comments", [])

    state["review_verdict"] = verdict
    state["review_comments"] = comments

    if verdict != "LGTM":
        state["round"] = state.get("round", 0) + 1
        state["error_category"] = "REVIEW_REJECTED"
        comment_text = json.dumps(comments, ensure_ascii=False)
        state["aider_message"] = (
            state.get("aider_message", "") + "\n\n## レビュー指摘事項 (差し戻し):\n" + comment_text
        ).strip()

    _pipe_to_reviewdog(state["project_path"], state["review_comments"])
    return state


def done_node(state: OrchestratorState) -> OrchestratorState:
    """完了ノード: tasks.md 完了更新および履歴出力."""
    actual_round = max(
        state.get("round", 0),
        state.get("lint_round", 0),
        state.get("test_round", 0),
    )
    logger.info(f"Issue {state['issue_id']} が正常完了しました。")
    update_task_metadata(
        state["project_path"],
        state["issue_id"],
        round_num=actual_round,
        status="COMPLETED",
    )
    record_execution_history(state, final_status="COMPLETED", actual_round=actual_round)
    return state


def escalate_node(state: OrchestratorState) -> OrchestratorState:
    """エスカレーションノード: B7 ブロッカーとして tasks.md を更新し安全停止."""
    actual_round = max(
        state.get("round", 0),
        state.get("lint_round", 0),
        state.get("test_round", 0),
    )
    logger.error(
        f"Issue {state['issue_id']} がリトライ上限 ({actual_round}/{state.get('max_round', 3)}) "
        "に達しました。B7ブロッカー化します。"
    )
    update_task_metadata(
        state["project_path"],
        state["issue_id"],
        round_num=actual_round,
        status="FAILED_B7",
        max_round=state.get("max_round", 3),
    )
    record_execution_history(state, final_status="FAILED_B7", actual_round=actual_round)
    return state


# ---------------------------------------------------------------------------
# 条件付きエッジルーティング関数 (DD-003 §4)
# ---------------------------------------------------------------------------


def route_after_lint(s: OrchestratorState) -> str:
    """Ruff チェック後の遷移先判定."""
    if s.get("lint_result", {}).get("passed", False):
        return "test"
    return "escalate" if s.get("lint_round", 0) >= s.get("max_round", 3) else "code"


def route_after_test(s: OrchestratorState) -> str:
    """Pytest 実行後の遷移先判定."""
    if s.get("test_result", {}).get("passed", False):
        return "review"
    return "escalate" if s.get("test_round", 0) >= s.get("max_round", 3) else "code"


route_after_test.__test__ = False  # type: ignore[attr-defined]


def route_after_review(s: OrchestratorState) -> str:
    """レビュー結果判定後の遷移先判定."""
    if s.get("review_verdict") == "LGTM":
        return "done"
    return "escalate" if s.get("round", 0) >= s.get("max_round", 3) else "code"


# ---------------------------------------------------------------------------
# LangGraph グラフ構築 (DD-003 §4)
# ---------------------------------------------------------------------------


def build_graph():
    """LangGraph StateGraph を組み立てコンパイルして返却する."""
    g = StateGraph(OrchestratorState)
    g.add_node("plan", plan_node)
    g.add_node("code", code_node)
    g.add_node("lint", lint_node)
    g.add_node("test", test_node)
    g.add_node("review", review_node)
    g.add_node("done", done_node)
    g.add_node("escalate", escalate_node)

    g.set_entry_point("plan")
    g.add_edge("plan", "code")
    g.add_edge("code", "lint")

    g.add_conditional_edges(
        "lint",
        route_after_lint,
        {"test": "test", "code": "code", "escalate": "escalate"},
    )
    g.add_conditional_edges(
        "test",
        route_after_test,
        {"review": "review", "code": "code", "escalate": "escalate"},
    )
    g.add_conditional_edges(
        "review",
        route_after_review,
        {"done": "done", "escalate": "escalate", "code": "code"},
    )

    g.add_edge("done", END)
    g.add_edge("escalate", END)
    return g.compile()


# ---------------------------------------------------------------------------
# 状態初期構築
# ---------------------------------------------------------------------------


def build_initial_state(issue_id: str) -> OrchestratorState:
    """tasks.md および project 設定から OrchestratorState を初期生成する."""
    project_path = "projects/default"
    title = f"Issue {issue_id}"
    description = ""
    priority = "NORMAL"

    projects_dir = Path("projects")
    if projects_dir.exists():
        for p in projects_dir.iterdir():
            if p.is_dir():
                t_file = p / "tasks.md"
                if t_file.exists():
                    t_content = t_file.read_text(encoding="utf-8")
                    if issue_id in t_content:
                        project_path = str(p)
                        for line in t_content.splitlines():
                            if issue_id in line:
                                title = line.strip()
                                break
                        break

    return {
        "issue_id": issue_id,
        "project_path": project_path,
        "title": title,
        "description": description,
        "priority": priority,
        "impl_plan": "",
        "aider_message": "",
        "lint_result": {},
        "test_result": {},
        "review_verdict": "",
        "review_comments": [],
        "error_category": None,
        "last_error_message": None,
        "round": 0,
        "lint_round": 0,
        "test_round": 0,
        "max_round": 3,
        "history": [],
    }


# ---------------------------------------------------------------------------
# CLI エントリポイント (DD-003 §5)
# ---------------------------------------------------------------------------


def cmd_orchestrate(args: argparse.Namespace) -> None:
    """優先度キャッシュ priority-cache.json から対話的に上位3件を提示する."""
    cache_path = Path("tools/.cache/priority-cache.json")
    if not cache_path.exists():
        print("エラー: 優先度キャッシュが存在しません。score-issues.py を実行してください。")
        return
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        issues = data.get("issues", [])[:3]
        print("【本日の実行計画 (推奨上位3件)】")
        for idx, item in enumerate(issues, 1):
            print(f"{idx}位: [{item.get('id')}]「{item.get('title')}」（スコア: {item.get('score')}）")
        if issues:
            top_id = issues[0].get("id")
            print(f"\n実行するには: uv run python tools/orchestrator_graph.py execute --issue-id {top_id}")
    except Exception as e:
        print(f"キャッシュファイルの読み込みエラー: {e}")


def cmd_execute(args: argparse.Namespace) -> None:
    """指定された issue_id に対して LangGraph グラフを組み立てて実行する."""
    issue_id = args.issue_id
    graph = build_graph()
    initial_state = build_initial_state(issue_id)
    final_state = graph.invoke(initial_state)
    print(
        f"Issue {issue_id} の実行が完了しました "
        f"(最終状態: {final_state.get('review_verdict', 'COMPLETED')})"
    )


def main() -> None:
    """CLI メイン関数."""
    parser = argparse.ArgumentParser(description="Second Brain OS Orchestrator CLI (LangGraph)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # orchestrate サブコマンド
    p_orch = subparsers.add_parser("orchestrate", help="本日の優先度推奨タスク提示")
    p_orch.set_defaults(func=cmd_orchestrate)

    # execute サブコマンド
    p_exec = subparsers.add_parser("execute", help="指定 Issue の自律グラフ実行")
    p_exec.add_argument("--issue-id", required=True, help="対象 Issue ID (例: EC-012)")
    p_exec.set_defaults(func=cmd_execute)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

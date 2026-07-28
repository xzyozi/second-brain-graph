# 詳細設計書（コンポーネント詳細・データフロー・実装仕様）
**LangGraph / LiteLLM / Aider / Ruff / Reviewdog 統合実装仕様**

| 項目     | 内容                                                           |
| :------- | :--------------------------------------------------------------- |
| 文書番号 | SBOS-DD-003                                                      |
| 版数     | Rev.4.4（CLIエントリポイント仕様明記・完全整合版） |
| 改訂日   | 2026年7月28日                                                     |
| 作成日   | 2026年7月28日                                                     |
| 関連文書 | SBOS-BD-002（基本設計書 Rev.4.3）、SBOS-MULTI-001 Rev.2.1、SBOS-OP-001 Rev.4.1、SBOS-OSS-001/002 |
| 対象読者 | 実装担当エンジニア / アーキテクト / テストエンジニア             |

---

## 1. 依存パッケージおよび環境構築

```bash
# パッケージマネージャー uv による導入（Linux / macOS / Windows Native 共通）
uv pip install langgraph litellm aider-chat ruff pytest pytest-json-report

# Reviewdog（Windows Native の場合は executable を PATH に配置）
reviewdog -version
```

---

## 2. 状態管理データ構造 (`OrchestratorState`)

```python
# tools/orchestrator_graph.py
from typing import TypedDict, Literal, List, Dict, Any
from pathlib import Path
from langgraph.graph import StateGraph, END

class OrchestratorState(TypedDict):
    issue_id: str
    project_path: str            # projects/<name> の絶対パス
    title: str
    description: str
    priority: str

    impl_plan: str                # Executor（plan_node）が生成した実装指示書
    aider_message: str            # code_nodeでAiderに渡す追加指示（lint/test/review指摘の蓄積）

    lint_result: Dict[str, Any]   # {"passed": bool, "issues": [...]}
    test_result: Dict[str, Any]   # {"passed": bool, "log": str}
    review_verdict: Literal["LGTM", "changes_requested", ""]
    review_comments: List[Dict[str, Any]]  # rdjson準拠のコメント配列

    round: int                    # レビュー試行ラウンド数
    lint_round: int               # ⭐NEW: lint リトライ数 (F3対応)
    test_round: int               # ⭐NEW: test リトライ数 (F3対応)
    max_round: int                # タスクごとの最大試行許容数
    history: List[Dict[str, Any]]  # 各ノードの実行履歴
```

---

## 3. モジュール設計

### 3.1 `tools/llm_client.py` (LiteLLM ラッパー)

```python
#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM経由でのLLM呼び出し"""
import json, re, logging, litellm
from typing import Optional

logger = logging.getLogger("llm_client")
# [MODEL_MAP明記] ENV-001 と完全整合させるため coder キーを明記
MODEL_MAP = {
    "planner": "ollama/qwen2.5-coder:14b",
    "coder": "ollama/qwen2.5-coder:7b-16k",
    "reviewer": "ollama/qwen3:32b",
}

def call_llm(role: str, system_prompt: str, user_prompt: str, expect_json: bool = False, timeout: int = 300) -> dict:
    model = MODEL_MAP.get(role, "ollama/qwen2.5-coder:7b-16k")
    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            timeout=timeout, api_base="http://localhost:11434"
        )
    except Exception as e:
        logger.error(f"LiteLLM Error ({role}): {e}")
        raise

    raw_output = response.choices[0].message.content
    if not expect_json:
        return {"raw": raw_output}

    json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not json_match:
        return {"verdict": "changes_requested", "comment": "JSON抽出失敗", "raw": raw_output}
    try:
        return json.loads(json_match.group(0))
    except Exception as e:
        return {"verdict": "changes_requested", "comment": f"JSONパースエラー: {e}", "raw": raw_output}
```

### 3.2 `tools/aider_runner.py` (Aider サブプロセス制御)

```python
#!/usr/bin/env python3
"""tools/aider_runner.py - Aiderサブプロセス起動 (F1修正済み)"""
import os, subprocess, logging
from pathlib import Path

def run_aider(project_path: Path, message: str, model: str = "ollama/qwen2.5-coder:7b-16k", timeout: int = 600) -> str:
    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = "http://localhost:11434"
    # [F1修正] 正しい Aider CLI フラグは --no-auto-commits (複数形)
    cmd = ["aider", "--message", message, "--model", model, "--no-auto-commits", "--yes-always", "--no-stream"]
    res = subprocess.run(cmd, cwd=str(project_path), env=env, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"Aider failed: {res.stderr}")
    return get_git_diff(project_path)

def get_git_diff(project_path: Path) -> str:
    return subprocess.run(["git", "diff", "HEAD"], cwd=str(project_path), capture_output=True, text=True).stdout
```

---

## 4. LangGraph グラフ構築と条件分岐ロジック (リトライ回路統合)

```python
def lint_node(state: OrchestratorState) -> OrchestratorState:
    """Ruffを実行し、JSON形式の指摘一覧を取得する。失敗時はノード内でlint_roundをインクリメントし、Aider用フィードバックを蓄積する。"""
    import subprocess, json
    result = subprocess.run(
        ["ruff", "check", "--output-format=json", "."],
        cwd=state["project_path"], capture_output=True, text=True,
    )
    issues = json.loads(result.stdout) if result.stdout.strip() else []
    passed = len(issues) == 0
    if not passed:
        state["lint_round"] = state.get("lint_round", 0) + 1
        # [III.1修正] Aiderへ修正指示を渡すため aider_message にログを蓄積
        state["aider_message"] = (state.get("aider_message", "") + "\n\n## Ruff指摘事項:\n" + json.dumps(issues, ensure_ascii=False)).strip()
    state["lint_result"] = {"passed": passed, "issues": issues}
    return state

def test_node(state: OrchestratorState) -> OrchestratorState:
    """pytestを実行し、JSON形式のレポートを取得する。失敗時はノード内でtest_roundをインクリメントし、Aider用フィードバックを蓄積する。"""
    import subprocess, json
    report_path = Path(state["project_path"]) / ".pytest_report.json"
    subprocess.run(
        ["pytest", "--json-report", f"--json-report-file={report_path}"],
        cwd=state["project_path"], capture_output=True, text=True,
    )
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        passed = report.get("exitcode", 1) == 0
        log = json.dumps(report.get("tests", []))
    else:
        passed = False
        log = "pytestレポートが生成されませんでした"
    if not passed:
        state["test_round"] = state.get("test_round", 0) + 1
        # [III.1修正] Aiderへ修正指示を渡すため aider_message にログを蓄積
        state["aider_message"] = (state.get("aider_message", "") + "\n\n## pytest失敗ログ:\n" + log).strip()
    state["test_result"] = {"passed": passed, "log": log}
    return state

def review_node(state: OrchestratorState) -> OrchestratorState:
    """レビューLLMを呼び出し、結果をrdjsonでReviewdogへパイプする。"""
    from tools.llm_client import call_llm
    from tools.aider_runner import get_git_diff
    diff = get_git_diff(Path(state["project_path"]))
    system_prompt = load_template("reviewer")
    user_prompt = f"## 実装指示書\n{state['impl_plan']}\n\n## 差分\n```diff\n{diff}\n```\n\n出力はJSON形式のみ: {{\"verdict\": \"LGTM または changes_requested\", \"comments\": [...]}}"
    result = call_llm("reviewer", system_prompt, user_prompt, expect_json=True)
    verdict = result.get("verdict", "changes_requested")
    state["review_verdict"] = verdict
    state["review_comments"] = result.get("comments", [])
    if verdict != "LGTM":
        # [2.1修正] review_roundのインクリメントもノード内で処理
        state["round"] = state.get("round", 0) + 1
    _pipe_to_reviewdog(state["project_path"], state["review_comments"])
    return state

def build_graph():
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

    # [2.1修正] ルーティング関数は純粋関数（読み取り専用）。インクリメントはノード側で実施済み
    def route_after_lint(s: OrchestratorState) -> str:
        if s["lint_result"]["passed"]:
            return "test"
        return "escalate" if s.get("lint_round", 0) >= s["max_round"] else "code"

    g.add_conditional_edges("lint", route_after_lint, {"test": "test", "code": "code", "escalate": "escalate"})

    def route_after_test(s: OrchestratorState) -> str:
        if s["test_result"]["passed"]:
            return "review"
        return "escalate" if s.get("test_round", 0) >= s["max_round"] else "code"

    g.add_conditional_edges("test", route_after_test, {"review": "review", "code": "code", "escalate": "escalate"})

    def route_after_review(s: OrchestratorState) -> str:
        if s["review_verdict"] == "LGTM":
            return "done"
        return "escalate" if s.get("round", 0) >= s["max_round"] else "code"

    g.add_conditional_edges("review", route_after_review, {"done": "done", "escalate": "escalate", "code": "code"})
    g.add_edge("done", END)
    g.add_edge("escalate", END)
    return g.compile()
```

### 4.1 B7 ブロッカー判定と `escalate_node` (F2 / III.2 統合修正)
`escalate_node` はレビュー、lint、または test の試行回数が `max_round` に達した際に呼ばれる。
固定値の `round:3` ではなく、**`actual_round = max(state["round"], state["lint_round"], state["test_round"])` の実測値** を動的に `tasks.md` 内のメタデータへ書き込む。

> **B7 ブロッカー検知のシングルソース・オブ・トゥルース (SSOT):**
> 日次バッチ `check-blockers.py` は **`tasks.md` 内の `round >= max_round` を正の判定基準** とする。`execution_history.json` 側の `review.total_rounds` は副次的な監査ログとして位置づけ、両者の整合性を維持する。

```python
def escalate_node(state: OrchestratorState) -> OrchestratorState:
    """レビュー/テスト/lint の試行回数上限到達時に tasks.md を動的更新し、B7 ブロッカー化させる"""
    actual_round = max(state.get("round", 0), state.get("lint_round", 0), state.get("test_round", 0))
    logger.error(f"Issue {state['issue_id']} がリトライ上限 ({actual_round}/{state['max_round']}) に達しました。B7ブロッカー化します。")
    # [F2/III.2修正] tasks.md 内の round メタデータを動的更新し、B7 判定を成立させる
    update_task_metadata(state["project_path"], state["issue_id"], round_num=actual_round)
    record_execution_history(state, final_status="FAILED_B7", actual_round=actual_round)
    return state
```

---

## 5. CLI エントリポイント仕様 (`tools/orchestrator_graph.py`)

OP-001 §1.2 で規定される運用コマンド（`orchestrate` および `execute`）を処理する CLI インターフェースの仕様を定義する。

```python
import argparse
import json
from pathlib import Path

def cmd_orchestrate(args):
    """優先度キャッシュ priority-cache.json から対話的に上位3件を提示する"""
    cache_path = Path("tools/.cache/priority-cache.json")
    if not cache_path.exists():
        print("エラー: 優先度キャッシュが存在しません。score-issues.py を実行してください。")
        return
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    issues = data.get("issues", [])[:3]
    print("【本日の実行計画 (推奨上位3件)】")
    for idx, item in enumerate(issues, 1):
        print(f"{idx}位: [{item['id']}]「{item['title']}」（スコア: {item['score']}）")
    if issues:
        top_id = issues[0]["id"]
        print(f"\n実行するには: uv run python tools/orchestrator_graph.py execute --issue-id {top_id}")

def cmd_execute(args):
    """指定された issue_id に対して LangGraph グラフを組み立てて実行する"""
    issue_id = args.issue_id
    graph = build_graph()
    initial_state = build_initial_state(issue_id)  # tasks.md / project.json から構築
    final_state = graph.invoke(initial_state)
    print(f"Issue {issue_id} の実行が完了しました (最終状態: {final_state.get('review_verdict', 'FAILED')})")

def main():
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
```

---

## 6. テスト・検証設計

1. **`test_orchestrator_graph.py`**: LangGraph の各状態遷移経路（`done`/`escalate`）テスト。`lint_round`/`test_round` 超過時の `escalate` 経路テストを含む。
2. **`test_orchestrator_graph.py` ルーティング純粋関数テスト**: ルーティング関数 `route_after_lint`, `route_after_test`, `route_after_review` を複数回連続で呼び出しても State のカウンタが二重インクリメントされないことを検証。
3. **`test_orchestrator_graph_cli.py`**: CLI エントリポイントの `orchestrate`（キャッシュ読み込み表示）および `execute --issue-id`（引数パース・グラフ呼出）の挙動検証。
4. **`test_llm_client.py`**: LiteLLM 呼び出しおよび壊れた JSON レスポンス時の安全フォールバックテスト。
5. **`test_aider_runner.py`**: `--no-auto-commits` （複数形）が常に付加されること、タイムアウト時に `AiderRunError` を送出することの検証。
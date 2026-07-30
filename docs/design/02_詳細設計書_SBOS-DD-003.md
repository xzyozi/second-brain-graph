# 詳細設計書（コンポーネント詳細・データフロー・実装仕様）
**LangGraph / LiteLLM / Aider / Ruff / Reviewdog 統合実装仕様**

| 項目     | 内容                                                           |
| :------- | :--------------------------------------------------------------- |
| 文書番号 | SBOS-DD-003                                                      |
| 版数     | Rev.4.9（PM-036 ブランチ・PR自動化方針反映） |
| 改訂日   | 2026年7月29日                                                     |
| 作成日   | 2026年7月28日                                                     |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-MULTI-001（差分設計書）、SBOS-OP-001（運用詳細設計書）、SBOS-ENV-001（環境構築仕様書）、SBOS-PM-005（課題一覧） |
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
from typing import TypedDict, Literal, List, Dict, Any, Optional
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

    # PM-005: エラー分類器およびリトライ制御フィールド
    error_category: Optional[Literal["LINT_ERROR", "TEST_ERROR", "REVIEW_REJECTED", "LLM_TIMEOUT", "SYSTEM_ERROR"]]
    last_error_message: Optional[str]

    round: int                    # レビュー試行ラウンド数
    lint_round: int               # lint リトライ数
    test_round: int               # test リトライ数
    max_round: int                # タスクごとの最大試行許容数 (デフォルト 3)
    history: List[Dict[str, Any]]  # 各ノードの実行履歴
```

### 2.1 エラー分類マッピング仕様 (PM-005 統合設計)
旧 ORCH-001 のエラー分類ロジックを、LangGraph ノードの実行結果に応じて以下のように `error_category` へアトミックにマッピングする。

| 発生ノード | 検知条件 | `error_category` 値 | 遷移先 (上限未達時) | 上限超過時 (`round >= max_round`) |
| :--- | :--- | :--- | :--- | :--- |
| `lint_node` | Ruff 静的解析エラーあり | `"LINT_ERROR"` | `code_node` (`lint_round` + 1) | `escalate_node` (B7ブロッカー: `FAILED_B7`) |
| `test_node` | Pytest 単体テスト失敗 | `"TEST_ERROR"` | `code_node` (`test_round` + 1) | `escalate_node` (B7ブロッカー: `FAILED_B7`) |
| `review_node` | Reviewer 指摘あり (`changes_requested`) | `"REVIEW_REJECTED"` | `code_node` (`round` + 1) | `escalate_node` (B7ブロッカー: `FAILED_B7`) |
| 全ノード | LiteLLM タイムアウト | `"LLM_TIMEOUT"` | 1回だけ再試行 | `escalate_node` (システム例外: `FAILED_SYSTEM`) |
| 全ノード | その他システム例外 | `"SYSTEM_ERROR"` | (再試行なし) | `escalate_node` (システム例外: `FAILED_SYSTEM`) |
| `plan_node` 前 | ロック取得失敗 | `"LOCKED"` | (待機・キューなし) | 即時スキップ: `SKIPPED_LOCKED` |
| 完了後 | PR作成失敗 | `"PR_ERROR"` | - | 作業ブランチ保持・停止: `PR_FAILED` |
| 完了後 | PR作成成功 | `"PR_SUCCESS"` | - | 完了記録: `COMPLETED` |

---

## 3. モジュール設計

### 3.1 `tools/llm_client.py` (LiteLLM ラッパー)

```python
#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM経由での動的LLM呼び出し (PM-007, PM-011対応)"""
import json, re, logging, litellm
from typing import Optional, Dict, Any
from tools.config_loader import get_model_params, load_model_config

logger = logging.getLogger("llm_client")

def call_llm(role: str, system_prompt: str, user_prompt: str, expect_json: bool = False, timeout: int = 300, **kwargs: Any) -> dict:
    config = load_model_config()
    api_base = config.get("api_base", "http://localhost:11434")
    
    # [PM-007/PM-011修正] config/models.json から動的にパラメータ(model_name, temperature, max_tokens: 35000等)を取得
    role_params = get_model_params(role)
    model_name = role_params.get("model_name", "gemma-4-12B-it-qat-UD-Q4_K_XL")
    temperature = kwargs.get("temperature", role_params.get("temperature", 0.1))
    max_tokens = kwargs.get("max_tokens", role_params.get("max_tokens", 35000))

    try:
        response = litellm.completion(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            api_base=api_base,
            **{k: v for k, v in kwargs.items() if k not in ("temperature", "max_tokens")}
        )
    except Exception as e:
        logger.error(f"LiteLLM Error ({role} / {model_name}): {e}")
        raise

    raw_output = response.choices[0].message.content or ""
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
"""tools/aider_runner.py - Aider CLI サブプロセス制御エンジン (実物整合)"""
import os, subprocess, logging
from typing import List, Optional
from tools.config_loader import get_model_name, load_model_config

logger = logging.getLogger("aider_runner")

def run_aider(
    instruction: str,
    target_files: List[str],
    model: Optional[str] = None,
    cwd: Optional[str] = None,
) -> bool:
    """Aider CLI を非対話バッチモードで起動し指定ファイルへ差分編集を非破壊適用する"""
    config = load_model_config()
    aider_cfg = config.get("aider", {})
    target_model = model or get_model_name("aider")
    no_auto_commits = aider_cfg.get("no_auto_commits", True)

    cmd = ["aider", "--model", target_model, "--yes-always"]
    if no_auto_commits:
        cmd.append("--no-auto-commits")
    cmd.extend(["--message", instruction])
    cmd.extend(target_files)

    env = os.environ.copy()
    api_base = config.get("api_base", "http://localhost:11434")
    env["OLLAMA_API_BASE"] = api_base

    try:
        res = subprocess.run(cmd, cwd=cwd, env=env, check=True)
        return res.returncode == 0
    except Exception as e:
        logger.error(f"[AiderRunner] Aider execution failed: {e}")
        return False

def get_git_diff(cwd: Optional[str] = None) -> str:
    """指定された衛星リポジトリカレントディレクトリの未コミット git diff を取得する"""
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout
    except Exception as e:
        logger.error(f"[AiderRunner] Failed to fetch git diff: {e}")
        return ""
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

def done_node(state: OrchestratorState) -> OrchestratorState:
    """レビューを通過しLGTMとなった後、自動で PR (Pull Request) を作成する"""
    import subprocess
    # PR作成（ベースブランチは project.json の base_branch または develop）
    base_branch = state.get("base_branch", "develop")
    head_branch = f"sbos/{state['issue_id']}"
    subprocess.run(
        ["gh", "pr", "create", "--base", base_branch, "--head", head_branch, "--title", f"[{state['issue_id']}] 自動実装完了", "--body", "Agentによって自動生成されたPRです。"],
        cwd=state["project_path"], check=True
    )
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

    # [PM-005対応] ルーティング関数は OrchestratorState の error_category およびリトライ回数で判定
    def route_after_lint(s: OrchestratorState) -> str:
        if s["lint_result"].get("passed", False):
            return "test"
        # エラーカテゴリ分類: LINT_ERROR
        return "escalate" if s.get("lint_round", 0) >= s.get("max_round", 3) else "code"

    g.add_conditional_edges("lint", route_after_lint, {"test": "test", "code": "code", "escalate": "escalate"})

    def route_after_test(s: OrchestratorState) -> str:
        if s["test_result"].get("passed", False):
            return "review"
        # エラーカテゴリ分類: TEST_ERROR
        return "escalate" if s.get("test_round", 0) >= s.get("max_round", 3) else "code"

    g.add_conditional_edges("test", route_after_test, {"review": "review", "code": "code", "escalate": "escalate"})

    def route_after_review(s: OrchestratorState) -> str:
        if s.get("review_verdict") == "LGTM":
            return "done"
        # エラーカテゴリ分類: REVIEW_REJECTED
        return "escalate" if s.get("round", 0) >= s.get("max_round", 3) else "code"

    g.add_conditional_edges("review", route_after_review, {"done": "done", "escalate": "escalate", "code": "code"})
    g.add_edge("done", END)
    g.add_edge("escalate", END)
    return g.compile()
```

### 4.1 B7 ブロッカー判定と `escalate_node` (F2 / III.2 統合修正)
`escalate_node` はレビュー、lint、または test の試行回数が `max_round` に達した際、およびシステム例外時に呼ばれる。

> **B7 ブロッカー検知のシングルソース・オブ・トゥルース (SSOT):**
> 日次バッチ `check-blockers.py` は、Issue単位の `metadata/projects/<PROJECT_KEY>/state.json` において **`status == "FAILED_B7"` の場合のみ**、B7ブロッカーとして扱う。
> `tasks.md` 内のHTMLコメントによる状態管理は廃止する。

```python
def escalate_node(state: OrchestratorState) -> OrchestratorState:
    """
    上限到達またはシステム例外発生時に呼ばれ、state.json を動的更新しブロッカー化・安全停止させる。
    B7、システム失敗、PR失敗時に、自動処理は作業ブランチおよび未コミット差分を保持したまま停止する。
    差分の破棄またはブランチ削除は、人間が内容を確認した後にのみ実施する。
    """
    actual_round = max(state.get("round", 0), state.get("lint_round", 0), state.get("test_round", 0))
    final_status = "FAILED_B7" if actual_round >= state["max_round"] else "FAILED_SYSTEM"
    
    logger.error(f"Issue {state['issue_id']} 実行停止: {final_status} (round: {actual_round}/{state['max_round']})")
    logger.info("安全のため作業ブランチおよび未コミット差分を保持して停止します。")
    
    update_task_state(state["project_path"], state["issue_id"], round_num=actual_round, status=final_status)
    record_execution_history(state, final_status=final_status, actual_round=actual_round)
    return state
```

### 4.1.1 補助関数契約および履歴スキーマ仕様 (PM-038 / PM-042)

#### 1. `state.json` メタデータ正本書式
`metadata/projects/<PROJECT_KEY>/state.json` に Issue ID をキーとした以下の最小状態項目のみを保持する。
```json
{
  "EC-012": {
    "status": "FAILED_B7",
    "round": 3,
    "max_round": 3
  }
}
```

#### 2. `update_task_state()` 関数の契約
```python
def update_task_state(
    project_path: Union[str, Path],
    issue_id: str,
    round_num: int,
    status: str = "FAILED_B7",
    max_round: Optional[int] = None
) -> None:
    """
    metadata/projects/<PROJECT_KEY>/state.json 内の該当 issue_id の状態項目をアトミックに更新する。
    tasks.md (人間向けのタスク説明) への書き込みは行わない。
    """
```

#### 3. `record_execution_history()` 関数と `history_path` スキーマ
* **保存パス (`history_path`)**: `tools/.cache/execution_history.json`
* **フィールドマッピング注記**: `OrchestratorState` のレビュー試行カウンタ `state["round"]` は、履歴 JSON スキーマ上の `"review_round"` フィールドへそのままマッピング保存される。

```python
def record_execution_history(
    state: OrchestratorState,
    final_status: str,
    actual_round: int
) -> None:
    """
    tools/.cache/execution_history.json へ実行完了・エスカレーション結果をアトミックに追記保存する。
    """
```

**`execution_history.json` スキーマ仕様:**
```json
{
  "records": [
    {
      "timestamp": "2026-07-29T15:00:00Z",
      "issue_id": "EC-0001",
      "project_path": "projects/ec-site",
      "final_status": "FAILED_B7",
      "actual_round": 3,
      "max_round": 3,
      "lint_round": 3,
      "test_round": 1,
      "review_round": 2,
      "review_rounds": [
        {
          "round": 1,
          "verdict": "changes_requested",
          "comments": [{"file": "main.py", "line": 15, "message": "型アノテーション不足"}]
        },
        {
          "round": 2,
          "verdict": "changes_requested",
          "comments": [{"file": "main.py", "line": 20, "message": "例外処理ハンドラ未考慮"}]
        }
      ],
      "history_summary": {
        "lint_passed": false,
        "test_passed": true,
        "review_verdict": "changes_requested"
      }
    }
  ]
}
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
    import subprocess
    issue_id = args.issue_id
    graph = build_graph()
    initial_state = build_initial_state(issue_id)  # tasks.md / project.json から構築
    
    # グラフ実行前処理: base_branch を最新化し、作業ブランチを切る (PM-036)
    base_branch = initial_state.get("base_branch", "develop")
    head_branch = f"sbos/{issue_id}"
    proj_path = initial_state["project_path"]
    subprocess.run(["git", "checkout", base_branch], cwd=proj_path, check=True)
    subprocess.run(["git", "pull", "origin", base_branch], cwd=proj_path, check=True)
    subprocess.run(["git", "checkout", "-b", head_branch, base_branch], cwd=proj_path, check=True)

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
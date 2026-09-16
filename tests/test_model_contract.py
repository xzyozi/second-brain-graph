"""モデル担保テスト (Live model contract tests).

実際のローカルモデル (Ollama / llama-server) を起動して call_llm を呼び出し、
「出力が期待する契約 (スキーマ・制約) を満たすか」を検証する。

- 値の完全一致ではなく契約ベースで判定するため、モデル差や温度揺れに耐える。
- 実 GPU / 実プロセスを消費するため integration マーカーを付与し、
  通常の単体テスト実行 (`-m "not integration"`) からは除外する。
- Ollama 管理エンドポイントへ疎通できない環境では自動 skip する。

実行例:
    uv run python -m pytest -m integration tests/test_model_contract.py
"""

import json
import urllib.error
import urllib.request

import pytest

from tools.config_loader import get_backend_execution_config
from tools.llm_client import call_llm

pytestmark = pytest.mark.integration


def _ollama_management_endpoint() -> str | None:
    """設定済みプロファイルから ollama 管理エンドポイントを取得する。無ければ None。"""
    try:
        config = get_backend_execution_config()
    except Exception:
        return None
    for profile in config.profiles.values():
        if profile.backend == "ollama" and profile.ollama_management_endpoint:
            return profile.ollama_management_endpoint.rstrip("/")
    return None


def _ollama_reachable(endpoint: str, timeout: float = 2.0) -> bool:
    """Ollama 管理 API に疎通できるかを軽量に確認する。"""
    try:
        with urllib.request.urlopen(f"{endpoint}/api/tags", timeout=timeout) as res:
            return res.getcode() == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


@pytest.fixture(scope="module")
def live_backend_available() -> None:
    """実バックエンドが利用可能でなければモジュール全体を skip する。"""
    endpoint = _ollama_management_endpoint()
    if not endpoint:
        pytest.skip("No ollama profile configured; live model contract tests skipped.")
    if not _ollama_reachable(endpoint):
        pytest.skip(f"Ollama backend not reachable at {endpoint}; skipping live tests.")


def test_planner_returns_dict_when_expecting_json(live_backend_available: None) -> None:
    """planner が expect_json=True で dict を返す契約を満たすことを確認する。

    値の中身は問わず、型と非空という最小契約のみを検証する。
    """
    result = call_llm(
        role="planner",
        system_prompt="You output a JSON object. Respond ONLY with valid JSON.",
        user_prompt='Return a JSON object like {"title": "sample", "steps": ["a", "b"]}.',
        expect_json=True,
        intent="spec_draft",
    )

    assert isinstance(result, dict)
    assert len(result) > 0


def test_reviewer_verdict_is_within_contract(live_backend_available: None) -> None:
    """reviewer の出力が verdict 契約 (LGTM / changes_requested) を満たすことを確認する。

    call_llm は JSON 抽出に失敗した場合も changes_requested を返すため、
    いずれにせよ verdict は既知の集合に収まるはずである。
    """
    diff_sample = (
        "diff --git a/sample.py b/sample.py\n"
        "+def add(a, b):\n"
        "+    return a + b\n"
    )
    result = call_llm(
        role="reviewer",
        system_prompt=(
            "You are a code reviewer. Respond ONLY with a JSON object of the form "
            '{"verdict": "LGTM" | "changes_requested", "comments": []}.'
        ),
        user_prompt=f"Review this diff and return the verdict JSON.\n\n{diff_sample}",
        expect_json=True,
        intent="code_review",
    )

    assert isinstance(result, dict)
    # フォールバック補完 (JSON抽出失敗) ではなく、モデルが直接有効な JSON を出力したことを保証
    assert "comment" not in result, f"JSON fallback was triggered due to malformed LLM response: {result}"
    assert "verdict" in result, f"verdict key missing in response: {result}"
    assert result["verdict"] in {"LGTM", "changes_requested"}, (
        f"verdict out of contract: {result['verdict']}"
    )


def test_coder_produces_nonempty_text(live_backend_available: None) -> None:
    """coder が expect_json=False で非空のテキストを返す契約を満たすことを確認する。"""
    result = call_llm(
        role="coder",
        system_prompt="You are a Python coding assistant.",
        user_prompt="Write a one-line Python function that returns the string 'ok'.",
        expect_json=False,
        intent="code_edit",
    )

    assert isinstance(result, dict)
    assert "raw" in result
    assert isinstance(result["raw"], str)
    assert result["raw"].strip() != ""


def test_planner_json_is_serializable(live_backend_available: None) -> None:
    """planner の JSON 応答が再シリアライズ可能 (純粋な JSON 互換 dict) であることを確認する。"""
    result = call_llm(
        role="planner",
        system_prompt="You output a JSON object. Respond ONLY with valid JSON.",
        user_prompt='Return a JSON object with a "summary" string field.',
        expect_json=True,
        intent="spec_draft",
    )

    assert isinstance(result, dict)
    # dict -> JSON 文字列 -> dict の往復が成立することを契約とする
    round_tripped = json.loads(json.dumps(result))
    assert round_tripped == result

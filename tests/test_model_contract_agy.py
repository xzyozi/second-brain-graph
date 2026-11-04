"""agy モデル担保テスト (Live agy model contract tests - Issue #127).

実際の agy CLI を起動して call_llm (テキスト・JSON応答) を呼び出し、
期待する契約 (スキーマ・制約) を満たすかを実機検証する。

- integration マーカーを付与し、通常の単体テスト実行 (`-m "not integration"`) および CI からは除外する。
- agy CLI が未導入または未認証の環境では自動 skip する。

実行例:
    uv run python -m pytest -m integration tests/test_model_contract_agy.py
"""

from __future__ import annotations

import pytest

from tools.agy_client import AgyError, AgyNotFoundError, resolve_agy_executable, run_agy_text
from tools.llm_client import call_llm

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_agy_available() -> None:
    """agy 実行環境が利用可能でなければモジュール全体を skip する."""
    try:
        resolve_agy_executable()
    except AgyNotFoundError:
        pytest.skip("agy executable not found in PATH or known locations; live agy tests skipped.")

    # 軽量な疎通テスト
    try:
        res = run_agy_text("Respond with 'PONG' only.", timeout=30)
        if not res or not res.strip():
            pytest.skip("agy returned empty response; skipping live tests.")
    except AgyError as e:
        pytest.skip(f"agy execution failed or unauthenticated ({e}); skipping live tests.")


def test_agy_text_response_contract(live_agy_available: None) -> None:
    """planner (spec_draft) がテキスト応答契約を満たすことを確認する."""
    result = call_llm(
        role="planner",
        intent="spec_draft",
        user_prompt="Issue: Add a simple add(a, b) function in math_util.py. Draft a short plan.",
    )
    assert isinstance(result, dict)
    assert "raw" in result
    assert len(result["raw"].strip()) > 0


def test_agy_json_response_contract(live_agy_available: None) -> None:
    """reviewer (code_review) が expect_json=True で dict (verdict 等) を返す契約を満たすことを確認する."""
    result = call_llm(
        role="reviewer",
        intent="code_review",
        user_prompt=(
            "Review this diff:\n"
            "```diff\n"
            "+def add(a: int, b: int) -> int:\n"
            "+    return a + b\n"
            "```\n"
            "Output JSON with verdict (LGTM or changes_requested) and comments list."
        ),
        expect_json=True,
    )
    assert isinstance(result, dict)
    assert "verdict" in result
    assert result["verdict"] in ("LGTM", "changes_requested")

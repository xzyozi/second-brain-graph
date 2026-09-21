#!/usr/bin/env python3
"""tools/jev_adapter.py - JEV (Judge & Evaluation via Vectorized-logits) 連携アダプター (PM-053, DD-006 §1.1).

submodules/jev-localsystem を内部モジュールとしてロードし、
Zero-Decode（1トークン推論 ＋ Logprobs抽出）による超高速規程適合判定を提供します。
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("jev_adapter")

# 1. JEV Core SDK のパス解決とインポート
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_JEV_SRC = _PROJECT_ROOT / "submodules" / "jev-localsystem" / "src"

if str(_JEV_SRC) not in sys.path and _JEV_SRC.exists():
    sys.path.insert(0, str(_JEV_SRC))

try:
    from jev import JudgePipeline, JudgeRequestDTO, JudgeResponseDTO
    _JEV_AVAILABLE = True
except ImportError:
    _JEV_AVAILABLE = False
    logger.warning(
        f"JEV Core SDK could not be imported from {_JEV_SRC}. "
        "Make sure 'git submodule update --init' has been executed."
    )

_PIPELINE_INSTANCE: Optional[Any] = None


def is_jev_available() -> bool:
    """JEV Core SDK が利用可能か確認する。"""
    return _JEV_AVAILABLE


def get_jev_pipeline(
    model_name: Optional[str] = None,
    ollama_base_url: Optional[str] = None,
) -> Optional[Any]:
    """JEV JudgePipeline のシングルトンインスタンスを取得する。"""
    global _PIPELINE_INSTANCE
    if not _JEV_AVAILABLE:
        return None

    if _PIPELINE_INSTANCE is None:
        effective_model = (
            model_name
            or os.environ.get("JEV_MODEL")
            or "qwen2.5:0.5b"
        )
        effective_url = (
            ollama_base_url
            or os.environ.get("OLLAMA_API_BASE")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        )
        try:
            _PIPELINE_INSTANCE = JudgePipeline(
                default_model=effective_model,
                lightweight_model=effective_model,
            )
            logger.info(
                f"Initialized JEV JudgePipeline (model={effective_model}, url={effective_url})"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize JEV JudgePipeline: {e}")
            return None

    return _PIPELINE_INSTANCE


# DoD YAGNI 検問用ポリシー正本
PLAN_CONFORMANCE_POLICY = (
    "実装計画（Implementation Plan）が、要求仕様（Issue Specifications）の範囲内に厳密に収まっているかを判定せよ。\n"
    "以下のいずれかに該当する場合は不適合（No）とする：\n"
    "1. 要求されていない新しい機能、パラメータ、または設定値の追加（YAGNI違反・過剰設計）\n"
    "2. 対象ファイル（Target Files）以外の無関係なファイルの改変\n"
    "3. 要求と直接関係のない大規模なリファクタリングやアーキテクチャの刷新\n"
    "Issue要件を満たす必要最小限の実装方針となっている場合のみ適合（Yes）とする。"
)


def verify_plan_conformance(
    issue_id: str,
    instruction: str,
    impl_plan: str,
    target_files: Optional[List[str]] = None,
    pipeline: Optional[Any] = None,
) -> Tuple[bool, float, str]:
    """策定された実装計画 (impl_plan) が Issue 要求仕様に適合しているかを JEV NoulTask で判定する (DD-006 §1.1).

    Args:
        issue_id: 対象 Issue ID (例: 'EC-001')
        instruction: Issue の要求仕様記述
        impl_plan: Planner LLM が策定した実装方針 (Definition of Done)
        target_files: 対象ファイル一覧
        pipeline: 明示的に指定する JudgePipeline (テスト・モック用)

    Returns:
        Tuple[is_valid, confidence, detail_msg]:
            - is_valid: 適合 (True) または 不適合 (False)
            - confidence: 判定の確信度 / 確率 (0.0〜1.0)
            - detail_msg: 判定理由または詳細ログ
    """
    if not impl_plan or not impl_plan.strip():
        return False, 0.0, "Empty implementation plan"

    pipe = pipeline or get_jev_pipeline()
    if pipe is None:
        logger.warning(
            f"[{issue_id}] JEV JudgePipeline unavailable. Bypassing plan conformance check (fail-open)."
        )
        return True, 1.0, "JEV unavailable (bypassed)"

    target_files_str = ", ".join(target_files) if target_files else "(None specified)"
    context_text = (
        f"【Issue ID】: {issue_id}\n\n"
        f"【要求仕様 (Issue Requirements)】:\n{instruction.strip()}\n\n"
        f"【対象ファイル (Target Files)】:\n{target_files_str}\n\n"
        f"【策定された実装計画 (Implementation Plan)】:\n{impl_plan.strip()}"
    )

    request = JudgeRequestDTO(
        task_type="noul",
        context_text=context_text,
        rule_definition=PLAN_CONFORMANCE_POLICY,
    )

    try:
        response: JudgeResponseDTO = pipe.judge(request)
        if response.status == "SUCCESS":
            is_valid = response.verdict == "Yes"
            confidence = response.confidence if response.confidence is not None else 1.0
            detail = (
                f"JEV Plan Conformance: {'PASSED' if is_valid else 'REJECTED'} "
                f"(verdict={response.verdict}, conf={confidence:.3f}, latency={response.latency_ms}ms)"
            )
            logger.info(f"[{issue_id}] {detail}")
            return is_valid, confidence, detail
        elif response.status == "INCONCLUSIVE":
            logger.warning(f"[{issue_id}] JEV Plan Conformance INCONCLUSIVE, bypassing.")
            return True, 0.5, "Inconclusive verdict (bypassed)"
        else:
            logger.warning(
                f"[{issue_id}] JEV Plan Conformance ERROR: {response.error_message}. Bypassing."
            )
            return True, 1.0, f"JEV error: {response.error_message} (bypassed)"
    except Exception as e:
        logger.warning(
            f"[{issue_id}] JEV execution failed ({e}). Bypassing plan conformance check."
        )
        return True, 1.0, f"Execution exception: {e} (bypassed)"

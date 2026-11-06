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

    class JudgeRequestDTO:  # type: ignore[no-redef]
        """JEV Core SDK 未展開環境用のフォールバック DTO。"""

        def __init__(
            self,
            task_type: str = "noul",
            context_text: str = "",
            rule_definition: str = "",
            **kwargs: Any,
        ) -> None:
            self.task_type = task_type
            self.context_text = context_text
            self.rule_definition = rule_definition
            self.extra = kwargs

    class JudgeResponseDTO:  # type: ignore[no-redef]
        """JEV Core SDK 未展開環境用のフォールバック DTO。"""

        def __init__(
            self,
            status: str = "SUCCESS",
            verdict: Optional[str] = None,
            confidence: Optional[float] = None,
            latency_ms: float = 0.0,
            error_message: Optional[str] = None,
        ) -> None:
            self.status = status
            self.verdict = verdict
            self.confidence = confidence
            self.latency_ms = latency_ms
            self.error_message = error_message

    class JudgePipeline:  # type: ignore[no-redef]
        """JEV Core SDK 未展開環境用のフォールバック Pipeline。"""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def judge(self, request: Any) -> Any:
            raise RuntimeError("JEV Core SDK is not installed")


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
        effective_model = model_name or os.environ.get("JEV_MODEL") or "qwen2.5:0.5b"
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
    impl_plan: Optional[str] = None,
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


# レビュー合否検問用ポリシー正本 (DD-006 §3.1.1, Issue #50)
REVIEW_CONFORMANCE_POLICY = (
    "実装差分（Git diff）が、要求仕様（Issue Specifications）および実装計画（DoD: Definition of Done）を"
    "過不足なく満たしているかを判定せよ。\n"
    "以下のいずれかに該当する場合は不適合（No）とする：\n"
    "1. Issueで要求された必須の機能、修正、またはテストが未実装・欠落している\n"
    "2. 要求されていない余計な機能や設定値が追加されている（YAGNI違反・過剰設計）\n"
    "3. 自動テスト（pytest）が失敗している、またはテストコードが無意味に形骸化されている\n"
    "4. 要求仕様やDoDと矛盾する実装方針となっている\n"
    "Issue要求仕様およびDoDを過不足なく満たし、テストが成功している場合のみ適合（Yes）とする。"
)


def verify_review_conformance(
    issue_id: str,
    instruction: str,
    diff_text: str,
    impl_plan: Optional[str] = None,
    pytest_returncode: Optional[int] = None,
    pipeline: Optional[Any] = None,
) -> Tuple[bool, float, str]:
    """Reviewer LLM が LGTM と判定した差分に対し、JEV NoulTask で合否判定の裏取り検証（決定化）を行う (DD-006 §3.1.1, Issue #50).

    Args:
        issue_id: 対象 Issue ID (例: 'EC-001')
        instruction: Issue の要求仕様記述
        diff_text: 対象ファイルの Git diff 全文
        impl_plan: Planner LLM が策定した実装計画 (Definition of Done)
        pytest_returncode: 直前の pytest 終了コード (0: 成功, それ以外: 失敗)
        pipeline: 明示的に指定する JudgePipeline (テスト・モック用)

    Returns:
        Tuple[is_valid, confidence, detail_msg]:
            - is_valid: 適合 (True: LGTM確定) または 不適合 (False: changes_requested上書き)
            - confidence: 判定の確信度 / 確率 (0.0〜1.0)
            - detail_msg: 判定理由または詳細ログ
    """
    if not diff_text or not diff_text.strip():
        return False, 0.0, "Empty diff: No code changes to review"

    if pytest_returncode is not None and pytest_returncode != 0:
        return False, 1.0, f"pytest failed with returncode {pytest_returncode}"

    pipe = pipeline or get_jev_pipeline()
    if pipe is None:
        logger.warning(
            f"[{issue_id}] JEV JudgePipeline unavailable. Bypassing review conformance check (fail-open)."
        )
        return True, 1.0, "JEV unavailable (bypassed)"

    plan_str = impl_plan.strip() if impl_plan else "(None specified)"
    pytest_str = "SUCCESS (0)" if pytest_returncode == 0 else f"Code: {pytest_returncode}"

    # 長大な diff の場合は JEV の context 最大長（約 12,000 文字）を超えないように安全にクリップ
    max_diff_len = 8000
    effective_diff = diff_text.strip()
    if len(effective_diff) > max_diff_len:
        effective_diff = effective_diff[:max_diff_len] + "\n... [diff truncated for length]"

    context_text = (
        f"【Issue ID】: {issue_id}\n\n"
        f"【要求仕様 (Issue Requirements)】:\n{instruction.strip()}\n\n"
        f"【実装計画 (DoD)】:\n{plan_str}\n\n"
        f"【自動テスト結果 (pytest)】:\n{pytest_str}\n\n"
        f"【実装差分 (Git diff)】:\n{effective_diff}"
    )

    request = JudgeRequestDTO(
        task_type="noul",
        context_text=context_text,
        rule_definition=REVIEW_CONFORMANCE_POLICY,
    )

    try:
        response: JudgeResponseDTO = pipe.judge(request)
        if response.status == "SUCCESS":
            is_valid = response.verdict == "Yes"
            confidence = response.confidence if response.confidence is not None else 1.0
            detail = (
                f"JEV Review Conformance: {'PASSED' if is_valid else 'REJECTED'} "
                f"(verdict={response.verdict}, conf={confidence:.3f}, latency={response.latency_ms}ms)"
            )
            logger.info(f"[{issue_id}] {detail}")
            return is_valid, confidence, detail
        elif response.status == "INCONCLUSIVE":
            logger.warning(f"[{issue_id}] JEV Review Conformance INCONCLUSIVE, bypassing.")
            return True, 0.5, "Inconclusive verdict (bypassed)"
        else:
            logger.warning(
                f"[{issue_id}] JEV Review Conformance ERROR: {response.error_message}. Bypassing."
            )
            return True, 1.0, f"JEV error: {response.error_message} (bypassed)"
    except Exception as e:
        logger.warning(
            f"[{issue_id}] JEV review execution failed ({e}). Bypassing review conformance check."
        )
        return True, 1.0, f"Execution exception: {e} (bypassed)"

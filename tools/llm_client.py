#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM 経由でのモデル一元管理動的 LLM 呼び出しモジュール."""

import json
import logging
import os
import tempfile
from typing import Any, Dict

from openai import OpenAI

from tools.agy_client import run_agy_text
from tools.backend_coordinator import get_coordinator
from tools.config_loader import ProfileConfig, get_model_params
from tools.sanitizer import sanitize_text

logger = logging.getLogger("llm_client")

ROLE_TO_INTENT_MAP = {
    "planner": "spec_draft",
    "coder": "code_edit",
    "reviewer": "code_review",
}


def _parse_llm_output(raw_output: str, expect_json: bool) -> Dict[str, Any]:
    """LLM の生出力を、OpenAI 経路・agy 経路で共通のルールで解析する。

    expect_json=False の場合は生文字列をそのまま保持する。expect_json=True の場合は
    JSON object の抽出を試み、失敗時は changes_requested への安全側フォールバックとする
    (ローカル LLM や agy の出力に前置き・コードフェンスが混ざる想定への対応)。
    """
    if not expect_json:
        return {"raw": raw_output}

    try:
        parsed = json.loads(raw_output)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start_idx = raw_output.find("{")
    if start_idx != -1:
        try:
            decoder = json.JSONDecoder()
            parsed, _ = decoder.raw_decode(raw_output[start_idx:])
            if isinstance(parsed, dict):
                return parsed
            return {
                "verdict": "changes_requested",
                "comment": "JSONルートがオブジェクトではありません",
                "raw": raw_output,
            }
        except json.JSONDecodeError as e:
            return {
                "verdict": "changes_requested",
                "comment": f"JSONパースエラー: {e}",
                "raw": raw_output,
            }

    return {"verdict": "changes_requested", "comment": "JSON抽出失敗", "raw": raw_output}


def _do_agy_llm_call(
    clean_system_prompt: str,
    clean_user_prompt: str,
    expect_json: bool,
    timeout: int,
    profile: ProfileConfig,
) -> Dict[str, Any]:
    """agy をテキスト応答器として呼び出す (SBOS-DD-005 §4.1).

    cwd は空の一時ディレクトリとし、agy にリポジトリを読ませず書かせない。
    temperature / max_tokens に相当する指定手段は agy に無いため使用しない
    (指定手段が判明したら #117 の結果に基づき追加する)。
    """
    prompt = f"[SYSTEM]\n{clean_system_prompt}\n\n[USER]\n{clean_user_prompt}"
    if expect_json:
        prompt += (
            "\n\n[OUTPUT FORMAT]\n"
            "Output ONLY a single JSON object. Do not include code fences, "
            "explanations, or any text before or after the JSON object."
        )

    agy_timeout = profile.timeout or timeout
    with tempfile.TemporaryDirectory(prefix="agy_llm_") as tmp_dir:
        raw_output = run_agy_text(prompt, timeout=agy_timeout, cwd=tmp_dir)

    return _parse_llm_output(raw_output, expect_json)


def call_llm(
    role: str,
    system_prompt: str,
    user_prompt: str,
    expect_json: bool = False,
    timeout: int = 600,
    intent: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call LLM via OpenAI API or agy, using parameters configured in config/models.yaml.

    Args:
        role: Model role ('planner', 'coder', 'reviewer', etc.)
        system_prompt: System prompt text
        user_prompt: User prompt text
        expect_json: If True, parses output as JSON with fallback
        timeout: Request timeout in seconds
        intent: The intent of the execution (e.g. 'spec_draft', 'task_decomposition'). Falls back to role map.
        **kwargs: Additional override parameters passed to OpenAI chat.completions.create
            (ignored when the resolved profile's backend is 'agy').

    Returns:
        Dict containing LLM response or parsed JSON.
    """
    if not intent:
        intent = ROLE_TO_INTENT_MAP.get(role, "")
    if not intent:
        raise ValueError(
            "intent is required for call_llm (e.g. 'spec_draft', 'code_review') "
            "and no default fallback exists."
        )

    coordinator = get_coordinator()

    def _do_llm_call(profile: ProfileConfig) -> Dict[str, Any]:
        # #20 (DD-003 §10.3): LLM 送信直前の機密情報マスキング。agy 経路にも適用する。
        clean_system_prompt = sanitize_text(system_prompt)
        clean_user_prompt = sanitize_text(user_prompt)

        if profile.backend == "agy":
            return _do_agy_llm_call(
                clean_system_prompt, clean_user_prompt, expect_json, timeout, profile
            )

        # Coordinator Adapter sets OPENAI_API_BASE / OLLAMA_API_BASE
        api_base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OLLAMA_API_BASE")
        if not api_base:
            raise ValueError(
                f"Endpoint (api_base) is not set by Coordinator for intent '{intent}'."
            )

        # Load dynamic model parameters from config/models.yaml (PM-007, PM-011 SSOT)
        role_params = get_model_params(role)

        model_name = profile.model
        if not model_name:
            raise ValueError(
                f"Profile provided by Coordinator is missing 'model' for intent '{intent}'."
            )

        temperature = role_params.get("temperature")
        if temperature is None:
            raise ValueError(f"Missing 'temperature' in role '{role}'.")

        max_tokens = role_params.get("max_tokens")
        if max_tokens is None:
            raise ValueError(f"Missing 'max_tokens' in role '{role}'.")

        # Allow explicit kwargs to override defaults
        completion_params: Dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": clean_system_prompt},
                {"role": "user", "content": clean_user_prompt},
            ],
            "temperature": kwargs.get("temperature", temperature),
            "max_tokens": kwargs.get("max_tokens", max_tokens),
        }

        # Add any extra custom kwargs
        for key, value in kwargs.items():
            if key not in completion_params:
                completion_params[key] = value

        client = OpenAI(base_url=api_base, api_key="local", timeout=timeout)

        try:
            response = client.chat.completions.create(**completion_params)
        except Exception as e:
            logger.error(f"OpenAI API Error ({role} / {model_name} / {intent}): {e}")
            raise

        raw_output = response.choices[0].message.content or ""
        return _parse_llm_output(raw_output, expect_json)

    # Execute via coordinator
    return coordinator.execute(intent, {"action": _do_llm_call})

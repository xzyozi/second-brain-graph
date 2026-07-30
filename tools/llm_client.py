#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM 経由でのモデル一元管理動的 LLM 呼び出しモジュール."""

import json
import logging
import os
from typing import Any, Dict

from openai import OpenAI

from tools.backend_coordinator import get_coordinator
from tools.config_loader import ProfileConfig, get_model_params

logger = logging.getLogger("llm_client")

ROLE_TO_INTENT_MAP = {
    "planner": "spec_draft",
    "coder": "code_edit",
    "reviewer": "code_review",
}


def call_llm(
    role: str,
    system_prompt: str,
    user_prompt: str,
    expect_json: bool = False,
    timeout: int = 300,
    intent: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call LLM via OpenAI API using parameters configured in config/models.json.

    Args:
        role: Model role ('planner', 'coder', 'reviewer', etc.)
        system_prompt: System prompt text
        user_prompt: User prompt text
        expect_json: If True, parses output as JSON with fallback
        timeout: Request timeout in seconds
        intent: The intent of the execution (e.g. 'spec_draft', 'task_decomposition'). Falls back to role map.
        **kwargs: Additional override parameters passed to OpenAI chat.completions.create

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
        # Coordinator Adapter sets OPENAI_API_BASE / OLLAMA_API_BASE
        api_base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OLLAMA_API_BASE")
        if not api_base:
            raise ValueError(f"Endpoint (api_base) is not set by Coordinator for intent '{intent}'.")

        # Load dynamic model parameters from config/models.json (PM-007, PM-011 SSOT)
        role_params = get_model_params(role)

        model_name = profile.model
        if not model_name:
            raise ValueError(f"Profile provided by Coordinator is missing 'model' for intent '{intent}'.")

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
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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
        if not expect_json:
            return {"raw": raw_output}

        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start_idx = raw_output.find('{')
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
                return {"verdict": "changes_requested", "comment": f"JSONパースエラー: {e}", "raw": raw_output}

        return {"verdict": "changes_requested", "comment": "JSON抽出失敗", "raw": raw_output}

    # Execute via coordinator
    return coordinator.execute(intent, {"action": _do_llm_call})

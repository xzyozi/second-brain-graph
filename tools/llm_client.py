#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM 経由でのモデル一元管理動的 LLM 呼び出しモジュール."""

import json
import logging
import re
from typing import Any, Dict, Optional

from openai import OpenAI
from tools.config_loader import get_model_params, load_model_config

logger = logging.getLogger("llm_client")


def call_llm(
    role: str,
    system_prompt: str,
    user_prompt: str,
    expect_json: bool = False,
    timeout: int = 300,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Call LLM via OpenAI API (llama-server) using parameters configured in config/models.json.

    Args:
        role: Model role ('planner', 'coder', 'reviewer', etc.)
        system_prompt: System prompt text
        user_prompt: User prompt text
        expect_json: If True, parses output as JSON with fallback
        timeout: Request timeout in seconds
        **kwargs: Additional override parameters passed to OpenAI chat.completions.create

    Returns:
        Dict containing LLM response or parsed JSON.
    """
    config = load_model_config()
    api_base = config.get("api_base", "http://localhost:8080/v1")

    # Load dynamic model parameters from config/models.json (PM-007, PM-011 SSOT)
    role_params = get_model_params(role)
    model_name = role_params.get("model_name", "gemma-4-12B-it-qat-UD-Q4_K_XL")
    temperature = role_params.get("temperature", 0.1)
    max_tokens = role_params.get("max_tokens", 35000)

    # Allow explicit kwargs to override defaults
    completion_params: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": kwargs.get("temperature", temperature),
        "max_tokens": kwargs.get("max_tokens", max_tokens),
        "timeout": timeout,
        "api_base": api_base,
    }

    # Add any extra custom kwargs
    for key, value in kwargs.items():
        if key not in completion_params:
            completion_params[key] = value

    client = OpenAI(base_url=api_base, api_key="local", timeout=timeout)

    try:
        # 互換性のため openai クライアントから不要な completion_params を取り除く (api_base, timeout はclient側で設定)
        api_params = completion_params.copy()
        api_params.pop("api_base", None)
        api_params.pop("timeout", None)
        
        response = client.chat.completions.create(**api_params)
    except Exception as e:
        logger.error(f"OpenAI API Error ({role} / {model_name}): {e}")
        raise

    raw_output = response.choices[0].message.content or ""
    if not expect_json:
        return {"raw": raw_output}

    json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if not json_match:
        return {"verdict": "changes_requested", "comment": "JSON抽出失敗", "raw": raw_output}

    try:
        parsed = json.loads(json_match.group(0))
        if isinstance(parsed, dict):
            return parsed
        return {"verdict": "changes_requested", "comment": "JSONルートがオブジェクトではありません", "raw": raw_output}
    except Exception as e:
        return {"verdict": "changes_requested", "comment": f"JSONパースエラー: {e}", "raw": raw_output}

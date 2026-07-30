#!/usr/bin/env python3
"""tools/llm_client.py - LiteLLM 経由でのモデル一元管理動的 LLM 呼び出しモジュール."""

import json
import logging
import re
from typing import Any, Dict, Optional

import os
from openai import OpenAI
from tools.config_loader import get_model_params, load_model_config, get_backend_execution_config
from tools.backend_coordinator import BackendExecutionCoordinator

logger = logging.getLogger("llm_client")



def call_llm(
    role: str,
    system_prompt: str,
    user_prompt: str,
    expect_json: bool = False,
    timeout: int = 300,
    intent: Optional[str] = None,
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
        if role == "planner":
            intent = "spec_draft"
        elif role == "reviewer":
            intent = "code_review"
        else:
            intent = "code_edit"

    coordinator = BackendExecutionCoordinator()

    def _do_llm_call() -> Dict[str, Any]:
        config = load_model_config()
        # Coordinator Adapter sets OPENAI_API_BASE / OLLAMA_API_BASE
        api_base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OLLAMA_API_BASE")
        if not api_base:
            raise ValueError(f"Endpoint (api_base) is not set by Coordinator for intent '{intent}'.")


        # Load dynamic model parameters from config/models.json (PM-007, PM-011 SSOT)
        role_params = get_model_params(role)
        
        # Override model_name with the one from the profile if available
        backend_cfg = get_backend_execution_config()
        profile_name = backend_cfg.get("routes", {}).get(intent)
        if not profile_name:
            raise ValueError(f"No route defined for intent '{intent}'.")
            
        profile = backend_cfg.get("profiles", {}).get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' is not defined.")
            
        model_name = profile.get("model") or role_params.get("model_name")
        if not model_name:
            raise ValueError(f"Missing 'model' in profile '{profile_name}' and no fallback in role '{role}'.")
        
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
            "timeout": timeout,
            "api_base": api_base,
        }

        # Add any extra custom kwargs
        for key, value in kwargs.items():
            if key not in completion_params:
                completion_params[key] = value

        client = OpenAI(base_url=api_base, api_key="local", timeout=timeout)

        try:
            # 互換性のため openai クライアントから不要な completion_params を取り除く
            api_params = completion_params.copy()
            api_params.pop("api_base", None)
            api_params.pop("timeout", None)
            
            response = client.chat.completions.create(**api_params)
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
                return {"verdict": "changes_requested", "comment": "JSONルートがオブジェクトではありません", "raw": raw_output}
            except json.JSONDecodeError as e:
                return {"verdict": "changes_requested", "comment": f"JSONパースエラー: {e}", "raw": raw_output}

        return {"verdict": "changes_requested", "comment": "JSON抽出失敗", "raw": raw_output}

    # Execute via coordinator
    return coordinator.execute(intent, {"action": _do_llm_call})

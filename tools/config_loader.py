"""Configuration Loader for Second Brain OS Model Management."""

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_base": "http://localhost:11434",
    "default_provider": "ollama",
    "models": {
        "planner": {
            "model_name": "ollama/gemma4-12b-it-Q4_K_M:latest",
            "temperature": 0.2,
            "max_tokens": 35000,
        },
        "coder": {
            "model_name": "ollama/gemma-4-py_coder:latest",
            "temperature": 0.1,
            "max_tokens": 35000,
        },
        "reviewer": {
            "model_name": "ollama/gemma4-12b-it-Q4_K_M:latest",
            "temperature": 0.1,
            "max_tokens": 35000,
        },
    },
    "aider": {
        "model_name": "ollama/gemma-4-py_coder:latest",
        "no_auto_commits": True,
        "edit_format": "diff",
    },
    "backend_execution": {
        "mode": "exclusive",
        "fallback": "disabled",
        "routes": {
            "spec_draft": "reasoning_economy",
            "task_decomposition": "reasoning_economy",
            "task_prioritization": "reasoning_economy",
            "code_edit": "coding_ollama",
            "aider_edit": "coding_ollama",
            "code_review": "coding_ollama"
        },
        "profiles": {
            "reasoning_economy": {
                "backend": "llama_server",
                "model": "gemma-4-12B-it-qat-UD-Q4_K_XL"
            },
            "coding_ollama": {
                "backend": "ollama",
                "model": "gemma-4-py_coder:latest"
            }
        }
    }
}


def get_config_path() -> Path:
    """Get absolute path to config/models.json."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / "config" / "models.json"


def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file with fallback to default."""
    config_path = get_config_path()
    if not config_path.exists():
        return DEFAULT_CONFIG

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"Warning: Failed to load config from {config_path}: {e}")
        return DEFAULT_CONFIG


def get_model_name(role: str) -> str:
    """Get configured model name for a specific role (planner, coder, reviewer, aider)."""
    config = load_model_config()
    if role == "aider":
        return str(config.get("aider", {}).get("model_name", "ollama/gemma-4-py_coder:latest"))

    models = config.get("models", {})
    if role in models:
        return str(models[role].get("model_name", "ollama/gemma-4-py_coder:latest"))

    return "ollama/gemma-4-py_coder:latest"


def get_model_params(role: str) -> Dict[str, Any]:
    """Get all configured model parameters (temperature, max_tokens, etc.) for a specific role."""
    config = load_model_config()
    models = config.get("models", {})
    if role in models and isinstance(models[role], dict):
        params = dict(models[role])
        # Return parameters excluding metadata descriptions
        params.pop("description", None)
        return params

    return {"model_name": "ollama/gemma-4-py_coder:latest", "temperature": 0.1, "max_tokens": 35000}


def get_backend_execution_config() -> Dict[str, Any]:
    """Get backend execution routing and profiles."""
    config = load_model_config()
    return config.get("backend_execution", DEFAULT_CONFIG["backend_execution"])

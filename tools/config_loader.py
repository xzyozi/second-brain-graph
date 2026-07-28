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
            "max_tokens": 8192,
        },
        "coder": {
            "model_name": "ollama/gemma-4-py_coder:latest",
            "temperature": 0.1,
            "max_tokens": 8192,
        },
        "reviewer": {
            "model_name": "ollama/gemma4-12b-it-Q4_K_M:latest",
            "temperature": 0.1,
            "max_tokens": 8192,
        },
    },
    "aider": {
        "model_name": "ollama/gemma-4-py_coder:latest",
        "no_auto_commits": True,
        "edit_format": "diff",
    },
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

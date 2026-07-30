"""Configuration Loader for Second Brain OS Model Management."""

import json
from pathlib import Path
from typing import Any, Dict

# DEFAULT_CONFIG was removed to prevent silent fallbacks to unsafe defaults.


def get_config_path() -> Path:
    """Get absolute path to config/models.json."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / "config" / "models.json"


def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file. Raises error if missing."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Required configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception as e:
        raise RuntimeError(f"Failed to parse config from {config_path}: {e}")


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
    backend_config = config.get("backend_execution")
    if not backend_config:
        raise ValueError("Missing 'backend_execution' configuration in models.json.")
    return backend_config

"""Configuration Loader for Second Brain OS Model Management."""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

# DEFAULT_CONFIG was removed to prevent silent fallbacks to unsafe defaults.


class AiderConfig(BaseModel):
    model_name: str
    no_auto_commits: bool = True

class RoleConfig(BaseModel):
    model_name: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    description: Optional[str] = None

class ProfileConfig(BaseModel):
    backend: str
    model: str
    endpoint: str
    port: Optional[int] = None
    model_path: Optional[str] = None

class BackendExecutionConfig(BaseModel):
    routes: Dict[str, str]
    profiles: Dict[str, ProfileConfig]

class RootConfig(BaseModel):
    aider: AiderConfig
    models: Dict[str, RoleConfig]
    backend_execution: BackendExecutionConfig

def get_config_path() -> Path:
    """Get absolute path to config/models.json."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / "config" / "models.json"

def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file. Raises error if missing or invalid."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Required configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Pydantic validation
            RootConfig.model_validate(data)
            return data
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {config_path}: {e}")


def get_model_name(role: str) -> str:
    """Get configured model name for a specific role (planner, coder, reviewer, aider)."""
    config = load_model_config()
    if role == "aider":
        model_name = config.get("aider", {}).get("model_name")
        if not model_name:
            raise ValueError("Missing 'model_name' for role 'aider' in models.json.")
        return str(model_name)

    models = config.get("models", {})
    if role in models:
        model_name = models[role].get("model_name")
        if not model_name:
            raise ValueError(f"Missing 'model_name' for role '{role}' in models.json.")
        return str(model_name)

    raise ValueError(f"Role '{role}' is not defined in models.json.")


def get_model_params(role: str) -> Dict[str, Any]:
    """Get all configured model parameters (temperature, max_tokens, etc.) for a specific role."""
    config = load_model_config()
    models = config.get("models", {})
    if role in models and isinstance(models[role], dict):
        params = dict(models[role])
        # Return parameters excluding metadata descriptions
        params.pop("description", None)
        if "model_name" not in params:
            raise ValueError(f"Missing 'model_name' parameter for role '{role}' in models.json.")
        return params

    raise ValueError(f"Role '{role}' is not defined in models.json.")


def get_backend_execution_config() -> Dict[str, Any]:
    """Get backend execution routing and profiles."""
    config = load_model_config()
    backend_config = config.get("backend_execution")
    if not backend_config:
        raise ValueError("Missing 'backend_execution' configuration in models.json.")
    return backend_config

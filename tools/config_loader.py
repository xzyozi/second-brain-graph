"""Configuration Loader for Second Brain OS Model Management."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, ConfigDict, model_validator

# DEFAULT_CONFIG was removed to prevent silent fallbacks to unsafe defaults.


class AiderConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    no_auto_commits: bool = True
    edit_format: Optional[str] = None
    description: Optional[str] = None

class RoleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    temperature: float
    max_tokens: int
    description: Optional[str] = None

class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    backend: Literal["ollama", "llama_server"]
    model: str
    endpoint: str
    port: Optional[int] = None
    model_path: Optional[str] = None
    assume_free_on_offline: bool = False

    @model_validator(mode='after')
    def check_llama_server_fields(self) -> 'ProfileConfig':
        if self.backend == 'llama_server':
            if self.port is None:
                raise ValueError("port must be specified when backend is llama_server")
            if self.model_path is None:
                raise ValueError("model_path must be specified when backend is llama_server")
        return self

class BackendExecutionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: str
    fallback: str
    routes: Dict[str, str]
    profiles: Dict[str, ProfileConfig]

    @model_validator(mode='after')
    def check_routes_exist(self) -> 'BackendExecutionConfig':
        for intent, profile_name in self.routes.items():
            if profile_name not in self.profiles:
                raise ValueError(f"Route '{intent}' refers to undefined profile '{profile_name}'")
        return self

class RootConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    aider: AiderConfig
    models: Dict[str, RoleConfig]
    backend_execution: BackendExecutionConfig

def get_config_path() -> Path:
    """Get absolute path to config/models.json."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / "config" / "models.json"

def load_model_config() -> RootConfig:
    """Load model configuration from JSON file and return validated Pydantic model."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Required configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return RootConfig.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {config_path}: {e}")


def get_model_params(role: str) -> Dict[str, Any]:
    """Get all configured model parameters (temperature, max_tokens, etc.) for a specific role."""
    config = load_model_config()
    models = config.models
    if role in models:
        params = models[role].model_dump(exclude_unset=True, exclude={"description"})
        return params

    raise ValueError(f"Role '{role}' is not defined in models.json.")


def get_backend_execution_config() -> BackendExecutionConfig:
    """Get backend execution routing and profiles."""
    config = load_model_config()
    return config.backend_execution

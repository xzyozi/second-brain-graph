"""Configuration Loader for Second Brain OS Model Management."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# DEFAULT_CONFIG was removed to prevent silent fallbacks to unsafe defaults.


class AiderConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    no_auto_commits: bool = True
    edit_format: Optional[str] = None
    description: Optional[str] = None

class RoleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=1)
    description: Optional[str] = None

class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    backend: Literal["ollama", "llama_server"]
    model: str = Field(min_length=1)
    openai_endpoint: str = Field(min_length=1, pattern=r"^https?://")
    ollama_management_endpoint: Optional[str] = Field(None, pattern=r"^https?://")
    port: Optional[int] = Field(None, ge=1, le=65535)
    model_path: Optional[str] = Field(None, min_length=1)

    @model_validator(mode='after')
    def check_backend_fields(self) -> 'ProfileConfig':
        if self.backend == 'llama_server':
            if self.port is None:
                raise ValueError("port must be specified when backend is llama_server")
            if not self.model_path:
                raise ValueError("model_path must be specified and non-empty when backend is llama_server")
        elif self.backend == 'ollama':
            if not self.ollama_management_endpoint:
                raise ValueError("ollama_management_endpoint must be specified when backend is ollama")
        return self

class BackendExecutionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal["exclusive"]
    fallback: str = Field(min_length=1)
    gpu_lease_timeout: int = Field(120, ge=1)
    routes: Dict[str, str]
    profiles: Dict[str, ProfileConfig]

    @model_validator(mode='after')
    def check_routes_and_fallback(self) -> 'BackendExecutionConfig':
        for intent, profile_name in self.routes.items():
            if profile_name not in self.profiles:
                raise ValueError(f"Route '{intent}' refers to undefined profile '{profile_name}'")

        if self.fallback != "disabled" and self.fallback not in self.profiles:
            raise ValueError(f"Fallback '{self.fallback}' must be 'disabled' or refer to a defined profile")

        return self

class RootConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    aider: AiderConfig
    models: Dict[str, RoleConfig]
    backend_execution: BackendExecutionConfig

def get_config_path() -> Path:
    """Get absolute path to config/models.json."""
    root_dir = Path(__file__).resolve().parent.parent
    return root_dir / "config" / "models.json"

@lru_cache(maxsize=1)
def load_model_config() -> RootConfig:
    """Load model configuration from JSON file and return validated Pydantic model (cached)."""
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Required configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return RootConfig.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {config_path}: {e}") from e


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


def get_aider_config() -> AiderConfig:
    """Get Aider execution configuration."""
    config = load_model_config()
    return config.aider


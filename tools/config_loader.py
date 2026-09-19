"""Configuration Loader for Second Brain OS Management (YAML & Pydantic)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ==============================================================================
# 1. Models & Backend Execution Configuration (models.yaml)
# ==============================================================================


class AiderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    no_auto_commits: bool = True
    edit_format: Optional[str] = None
    timeout: int = 1200
    description: Optional[str] = None


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=1)
    description: Optional[str] = None


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["ollama", "llama_server"]
    model: str = Field(min_length=1)
    openai_endpoint: str = Field(min_length=1, pattern=r"^https?://")
    ollama_management_endpoint: Annotated[Optional[str], Field(pattern=r"^https?://")] = None
    port: Annotated[Optional[int], Field(ge=1, le=65535)] = None
    model_path: Annotated[Optional[str], Field(min_length=1)] = None

    @model_validator(mode="after")
    def check_backend_fields(self) -> "ProfileConfig":
        if self.backend == "llama_server":
            if self.port is None:
                raise ValueError("port must be specified when backend is llama_server")
            if not self.model_path:
                raise ValueError(
                    "model_path must be specified and non-empty when backend is llama_server"
                )
        elif self.backend == "ollama":
            if not self.ollama_management_endpoint:
                raise ValueError(
                    "ollama_management_endpoint must be specified when backend is ollama"
                )
        return self


class BackendExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["exclusive"]
    fallback: str = Field(min_length=1)
    gpu_lease_timeout: Annotated[int, Field(ge=1)] = 120
    routes: Dict[str, str]
    profiles: Dict[str, ProfileConfig]

    @model_validator(mode="after")
    def check_routes_and_fallback(self) -> "BackendExecutionConfig":
        for intent, profile_name in self.routes.items():
            if profile_name not in self.profiles:
                raise ValueError(f"Route '{intent}' refers to undefined profile '{profile_name}'")

        if self.fallback != "disabled" and self.fallback not in self.profiles:
            raise ValueError(
                f"Fallback '{self.fallback}' must be 'disabled' or refer to a defined profile"
            )

        return self


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aider: AiderConfig
    models: Dict[str, RoleConfig]
    backend_execution: BackendExecutionConfig


# 後方互換性のためのエイリアス
RootConfig = ModelConfig


# ==============================================================================
# 2. Prompts Configuration (prompt.yaml)
# ==============================================================================


class PlannerPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_draft_system: str


class CoderPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_restriction_template: str
    execution_strategy_step_by_step: str
    strict_output_rules: str
    read_only_test_enforcement: str


class AdvisorPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_feedback_system: str


class ReviewerPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code_review_system: str


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planner: PlannerPromptConfig
    coder: CoderPromptConfig
    advisor: AdvisorPromptConfig
    reviewer: ReviewerPromptConfig


# ==============================================================================
# 3. Tags & Policy Configuration (tag.yaml)
# ==============================================================================


class TaskClassificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read_only_test_tasks: List[str]
    feature_tasks: List[str]
    label_mappings: Dict[str, str]
    fallback_keyword_signals: List[str]


class QualityGuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tampering_detection_enabled: bool = True
    protected_assertion_patterns: List[str]
    forbidden_skip_patterns: List[str]


class TagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_classification: TaskClassificationConfig
    quality_guard: QualityGuardConfig


# ==============================================================================
# 4. Unified Application Configuration
# ==============================================================================


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: ModelConfig
    prompt: PromptConfig
    tag: TagConfig


# ==============================================================================
# Loader Functions
# ==============================================================================


def get_config_dir() -> Path:
    """Get absolute path to config/ directory."""
    return Path(__file__).resolve().parent.parent / "config"


def get_config_path(filename: str = "models.yaml") -> Path:
    """Get absolute path to a configuration file."""
    return get_config_dir() / filename


def _load_yaml_or_json(path: Path) -> Dict[str, Any]:
    """Load dictionary from YAML or JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        if path.suffix in [".yaml", ".yml"]:
            data = yaml.safe_load(f)
        else:
            data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a top-level dictionary/mapping")
    return data


@lru_cache(maxsize=1)
def load_model_config() -> ModelConfig:
    """Load model configuration from models.yaml (or models.json fallback) and return validated model."""
    yaml_path = get_config_path("models.yaml")
    json_path = get_config_path("models.json")

    target_path = yaml_path if yaml_path.exists() else json_path
    if not target_path.exists():
        raise FileNotFoundError(
            f"Required configuration file not found: {yaml_path} or {json_path}"
        )

    try:
        data = _load_yaml_or_json(target_path)
        return ModelConfig.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {target_path}: {e}") from e


@lru_cache(maxsize=1)
def load_prompt_config() -> PromptConfig:
    """Load prompt configuration from prompt.yaml and return validated model."""
    target_path = get_config_path("prompt.yaml")
    try:
        data = _load_yaml_or_json(target_path)
        return PromptConfig.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {target_path}: {e}") from e


@lru_cache(maxsize=1)
def load_tag_config() -> TagConfig:
    """Load tag configuration from tag.yaml and return validated model."""
    target_path = get_config_path("tag.yaml")
    try:
        data = _load_yaml_or_json(target_path)
        return TagConfig.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Failed to parse or validate config from {target_path}: {e}") from e


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and return unified AppConfig combining models, prompt, and tag configs."""
    return AppConfig(
        models=load_model_config(),
        prompt=load_prompt_config(),
        tag=load_tag_config(),
    )


# Convenience helper functions for models


def get_model_params(role: str) -> Dict[str, Any]:
    """Get all configured model parameters (temperature, max_tokens, etc.) for a specific role."""
    config = load_model_config()
    models = config.models
    if role in models:
        params = models[role].model_dump(exclude_unset=True, exclude={"description"})
        return params

    raise ValueError(f"Role '{role}' is not defined in model configuration.")


def get_backend_execution_config() -> BackendExecutionConfig:
    """Get backend execution routing and profiles."""
    config = load_model_config()
    return config.backend_execution


def get_aider_config() -> AiderConfig:
    """Get Aider execution configuration."""
    config = load_model_config()
    return config.aider

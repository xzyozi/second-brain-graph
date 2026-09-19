"""Unit tests for tools/config_loader.py validation logic.

正常系 (実 config/models.json の読み込み) は他テストで担保されているため、
ここでは Pydantic model_validator による異常系 (fail-closed) を中心に検証する。
モデルを直接インスタンス化し、実ファイルや lru_cache へ依存しない。
"""

import pytest
from pydantic import ValidationError

from tools.config_loader import (
    BackendExecutionConfig,
    ProfileConfig,
    get_backend_execution_config,
    get_model_params,
)


# ---------------------------------------------------------------------------
# ProfileConfig.check_backend_fields
# ---------------------------------------------------------------------------
def test_profile_llama_server_requires_port() -> None:
    """llama_server バックエンドで port が欠損する場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError, match="port must be specified"):
        ProfileConfig(
            backend="llama_server",
            model="test-model",
            openai_endpoint="http://localhost:8080/v1",
            model_path="./models/test.gguf",
        )


def test_profile_llama_server_requires_model_path() -> None:
    """llama_server バックエンドで model_path が欠損する場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError, match="model_path must be specified"):
        ProfileConfig(
            backend="llama_server",
            model="test-model",
            openai_endpoint="http://localhost:8080/v1",
            port=8080,
        )


def test_profile_ollama_requires_management_endpoint() -> None:
    """ollama バックエンドで management_endpoint が欠損する場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError, match="ollama_management_endpoint must be specified"):
        ProfileConfig(
            backend="ollama",
            model="test-model",
            openai_endpoint="http://localhost:11434/v1",
        )


def test_profile_rejects_non_http_endpoint() -> None:
    """openai_endpoint が http(s) スキームでない場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError):
        ProfileConfig(
            backend="ollama",
            model="test-model",
            openai_endpoint="ftp://localhost:11434",
            ollama_management_endpoint="http://localhost:11434",
        )


def test_profile_rejects_unknown_backend() -> None:
    """未知の backend 種別は Literal 検証で拒否されることを確認する。"""
    with pytest.raises(ValidationError):
        ProfileConfig(
            backend="unknown_backend",  # type: ignore[arg-type]
            model="test-model",
            openai_endpoint="http://localhost:11434/v1",
        )


def test_profile_valid_ollama_passes() -> None:
    """妥当な ollama プロファイルは検証を通過することを確認する (正常系の対照)。"""
    profile = ProfileConfig(
        backend="ollama",
        model="test-model",
        openai_endpoint="http://localhost:11434/v1",
        ollama_management_endpoint="http://localhost:11434",
    )
    assert profile.backend == "ollama"
    assert profile.model == "test-model"


# ---------------------------------------------------------------------------
# BackendExecutionConfig.check_routes_and_fallback
# ---------------------------------------------------------------------------
def _valid_ollama_profile() -> ProfileConfig:
    return ProfileConfig(
        backend="ollama",
        model="test-model",
        openai_endpoint="http://localhost:11434/v1",
        ollama_management_endpoint="http://localhost:11434",
    )


def test_backend_config_rejects_route_to_undefined_profile() -> None:
    """routes が未定義プロファイルを参照する場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError, match="undefined profile"):
        BackendExecutionConfig(
            mode="exclusive",
            fallback="disabled",
            routes={"code_edit": "missing_profile"},
            profiles={"coding_ollama": _valid_ollama_profile()},
        )


def test_backend_config_rejects_invalid_fallback() -> None:
    """fallback が 'disabled' でも定義済みプロファイルでもない場合に検証エラーとなることを確認する。"""
    with pytest.raises(ValidationError, match="Fallback"):
        BackendExecutionConfig(
            mode="exclusive",
            fallback="nonexistent_profile",
            routes={"code_edit": "coding_ollama"},
            profiles={"coding_ollama": _valid_ollama_profile()},
        )


def test_backend_config_accepts_fallback_disabled() -> None:
    """fallback='disabled' は妥当として受理されることを確認する (正常系の対照)。"""
    config = BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"code_edit": "coding_ollama"},
        profiles={"coding_ollama": _valid_ollama_profile()},
    )
    assert config.fallback == "disabled"


def test_backend_config_accepts_fallback_to_defined_profile() -> None:
    """定義済みプロファイルを指す fallback は受理されることを確認する。"""
    config = BackendExecutionConfig(
        mode="exclusive",
        fallback="coding_ollama",
        routes={"code_edit": "coding_ollama"},
        profiles={"coding_ollama": _valid_ollama_profile()},
    )
    assert config.fallback == "coding_ollama"


# ---------------------------------------------------------------------------
# get_model_params / get_backend_execution_config (実 config 経由の契約)
# ---------------------------------------------------------------------------
def test_get_model_params_rejects_unknown_role() -> None:
    """未定義ロールを要求した場合に ValueError となることを確認する。"""
    with pytest.raises(ValueError, match="is not defined"):
        get_model_params("nonexistent_role")


def test_get_backend_execution_config_routes_are_consistent() -> None:
    """実 config のルートがすべて定義済みプロファイルを指すことを確認する。"""
    config = get_backend_execution_config()
    for intent, profile_name in config.routes.items():
        assert profile_name in config.profiles, f"Route '{intent}' -> '{profile_name}' is undefined"


# ---------------------------------------------------------------------------
# YAML Configuration Loaders (models.yaml, prompt.yaml, tag.yaml, AppConfig)
# ---------------------------------------------------------------------------
def test_load_model_config_loads_yaml() -> None:
    """models.yaml が正常にロードされ、Pydantic モデルとして妥当であることを確認する。"""
    from tools.config_loader import load_model_config

    config = load_model_config()
    assert config.aider.no_auto_commits is True
    assert "planner" in config.models
    assert "coder" in config.models
    assert "reviewer" in config.models
    assert config.backend_execution.mode == "exclusive"


def test_load_prompt_config_loads_yaml() -> None:
    """prompt.yaml が正常にロードされ、各ロールのプロンプトが取得できることを確認する。"""
    from tools.config_loader import load_prompt_config

    prompt_config = load_prompt_config()
    assert len(prompt_config.planner.spec_draft_system.strip()) > 0
    assert len(prompt_config.coder.scope_restriction_template.strip()) > 0
    assert len(prompt_config.advisor.test_feedback_system.strip()) > 0
    assert len(prompt_config.reviewer.code_review_system.strip()) > 0
    assert "[TEST INTEGRITY AUDIT" in prompt_config.reviewer.code_review_system


def test_load_tag_config_loads_yaml() -> None:
    """tag.yaml が正常にロードされ、タスク分類タグおよび品質ガード設定が取得できることを確認する。"""
    from tools.config_loader import load_tag_config

    tag_config = load_tag_config()
    assert "bug" in tag_config.task_classification.read_only_test_tasks
    assert "fix" in tag_config.task_classification.read_only_test_tasks
    assert "feature" in tag_config.task_classification.feature_tasks
    assert tag_config.task_classification.label_mappings.get("bug") == "fix"
    assert tag_config.quality_guard.tampering_detection_enabled is True
    assert "assert " in tag_config.quality_guard.protected_assertion_patterns
    assert "@pytest.mark.skip" in tag_config.quality_guard.forbidden_skip_patterns


def test_get_config_returns_unified_app_config() -> None:
    """get_config() が models, prompt, tag をすべて含む統合 AppConfig を返すことを確認する。"""
    from tools.config_loader import AppConfig, get_config

    app_config = get_config()
    assert isinstance(app_config, AppConfig)
    assert app_config.models is not None
    assert app_config.prompt is not None
    assert app_config.tag is not None
    assert app_config.models.aider.timeout == 1200

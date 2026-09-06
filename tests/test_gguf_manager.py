#!/usr/bin/env python3
"""tests/test_gguf_manager.py - tools/gguf_manager.py の単体テスト."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.gguf_manager import (
    GgufFileNotFoundError,
    ensure_models_dir,
    get_models_dir,
    list_gguf_models,
    resolve_gguf_path,
    validate_gguf_exists,
)


def test_get_models_dir():
    models_dir = get_models_dir()
    assert isinstance(models_dir, Path)
    assert models_dir.name == "models"


def test_ensure_models_dir(tmp_path):
    with patch("tools.gguf_manager.get_models_dir", return_value=tmp_path / "models"):
        res = ensure_models_dir()
        assert res.exists()
        assert res.is_dir()


def test_resolve_gguf_path_relative():
    rel_path = "models/sample.gguf"
    resolved = resolve_gguf_path(rel_path)
    assert resolved.is_absolute()
    assert resolved.name == "sample.gguf"


def test_resolve_gguf_path_absolute(tmp_path):
    abs_file = tmp_path / "sample.gguf"
    resolved = resolve_gguf_path(abs_file)
    assert resolved == abs_file


def test_validate_gguf_exists_success(tmp_path):
    dummy_gguf = tmp_path / "test_model.gguf"
    dummy_gguf.touch()

    resolved = validate_gguf_exists(dummy_gguf, "test_role")
    assert resolved == dummy_gguf


def test_validate_gguf_exists_not_found(tmp_path):
    non_existent = tmp_path / "non_existent.gguf"
    with pytest.raises(GgufFileNotFoundError) as exc_info:
        validate_gguf_exists(non_existent, "main")
    assert "not found at" in str(exc_info.value)


def test_list_gguf_models(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "b_model.gguf").touch()
    (models_dir / "a_model.gguf").touch()
    (models_dir / "not_gguf.txt").touch()

    with patch("tools.gguf_manager.get_models_dir", return_value=models_dir):
        models = list_gguf_models()
        assert len(models) == 2
        assert models[0].name == "a_model.gguf"
        assert models[1].name == "b_model.gguf"

#!/usr/bin/env python3
"""tools.build_modelfileの単体テスト。"""

from pathlib import Path
from typing import Any

import pytest

import tools.build_modelfile as build_modelfile


def _prepare_project_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(build_modelfile, "PROJECT_ROOT", tmp_path)
    gguf_path = tmp_path / "models" / "example.gguf"
    gguf_path.parent.mkdir()
    gguf_path.write_bytes(b"GGUF")
    return gguf_path


def test_build_modelfile_uses_project_root_and_logical_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gguf_path = _prepare_project_root(monkeypatch, tmp_path)

    result = build_modelfile.build_modelfile(
        "models/example.gguf", "local/qwen3", "coder", template="qwen"
    )

    assert result.gguf_path == gguf_path
    assert result.registered_name == "local/qwen3:coder"
    assert result.output_path.name == "Modelfile_local%2Fqwen3%3Acoder"
    content = result.output_path.read_text(encoding="utf-8")
    assert "FROM ../../models/example.gguf" in content
    assert "# Registered name: local/qwen3:coder" in content


def test_missing_gguf_requires_explicit_preparation_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_modelfile, "PROJECT_ROOT", tmp_path)

    with pytest.raises(build_modelfile.ModelfileValidationError, match="was not found"):
        build_modelfile.build_modelfile("models/future.gguf", "qwen3", "coder", template="qwen")

    result = build_modelfile.build_modelfile(
        "models/future.gguf",
        "qwen3",
        "coder",
        template="qwen",
        allow_missing_gguf=True,
    )

    assert result.output_path.exists()
    assert "FROM ../../models/future.gguf" in result.output_path.read_text(encoding="utf-8")


def test_gguf_extension_is_required_even_in_preparation_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_modelfile, "PROJECT_ROOT", tmp_path)

    with pytest.raises(build_modelfile.ModelfileValidationError, match=".gguf extension"):
        build_modelfile.build_modelfile(
            "models/future.bin",
            "qwen3",
            "coder",
            template="qwen",
            allow_missing_gguf=True,
        )


def test_existing_modelfile_requires_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)
    build_modelfile.build_modelfile("models/example.gguf", "qwen3", "coder", template="qwen")

    with pytest.raises(build_modelfile.ModelfileValidationError, match="already exists"):
        build_modelfile.build_modelfile("models/example.gguf", "qwen3", "coder", template="qwen")

    result = build_modelfile.build_modelfile(
        "models/example.gguf", "qwen3", "coder", template="qwen", force=True
    )
    assert result.output_path.exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"num_ctx": 0}, "num_ctx"),
        ({"num_thread": 0}, "num_thread"),
        ({"num_gpu": -1}, "num_gpu"),
        ({"temperature": 2.1}, "temperature"),
        ({"top_p": 0.0}, "top_p"),
        ({"top_k": 0}, "top_k"),
        ({"repeat_penalty": 0.0}, "repeat_penalty"),
    ],
)
def test_parameter_ranges_are_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)

    with pytest.raises(build_modelfile.ModelfileValidationError, match=message):
        build_modelfile.build_modelfile(
            "models/example.gguf", "qwen3", "coder", template="qwen", **kwargs
        )


def test_num_gpu_auto_omits_parameter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)

    result = build_modelfile.build_modelfile(
        "models/example.gguf", "qwen3", "coder", template="qwen", num_gpu=None
    )

    assert "PARAMETER num_gpu" not in result.output_path.read_text(encoding="utf-8")


def test_system_prompt_file_is_included(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("Use concise answers.", encoding="utf-8", newline="\n")

    result = build_modelfile.build_modelfile(
        "models/example.gguf",
        "qwen3",
        "coder",
        template="qwen",
        system_prompt_file=prompt_path,
    )

    assert 'SYSTEM """Use concise answers."""' in result.output_path.read_text(encoding="utf-8")


def test_system_prompt_file_rejects_modelfile_delimiter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text('bad """ delimiter', encoding="utf-8", newline="\n")

    with pytest.raises(build_modelfile.ModelfileValidationError, match="unsupported"):
        build_modelfile.build_modelfile(
            "models/example.gguf",
            "qwen3",
            "coder",
            template="qwen",
            system_prompt_file=prompt_path,
        )


def test_template_must_be_explicit_in_cli() -> None:
    with pytest.raises(SystemExit):
        build_modelfile.parse_args(["--gguf-path", "models/example.gguf", "--model-name", "qwen3"])


def test_invalid_model_name_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_project_root(monkeypatch, tmp_path)

    with pytest.raises(build_modelfile.ModelfileValidationError, match="model_name"):
        build_modelfile.build_modelfile("models/example.gguf", "../qwen3", "coder", template="qwen")

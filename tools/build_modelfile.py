#!/usr/bin/env python3
"""GGUFモデル向けの検証済みOllama Modelfileを生成するCLI・モジュール。"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
ROLE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_SYSTEM_PROMPT = """You are an expert software engineer and systems architect.
Your task is to help the user with precise, highly efficient, and bug-free code.
When asked to perform file operations, structural log analysis, or tool executions, ensure that your responses conform strictly to the required schema or functional calling format without any conversational filler.
Always prioritize code portability, utilizing standard libraries or designated robust frameworks."""
QWEN_TEMPLATE = """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ if .Prompt }}<|im_start|>user
{{ .Prompt }}<|im_end|>
{{ end }}<|im_start|>assistant
{{ .Response }}<|im_end|>"""


class ModelfileValidationError(ValueError):
    """Modelfile生成に必要な入力値が契約を満たさない場合に送出する。"""


@dataclass(frozen=True)
class ModelfileBuildResult:
    """Modelfile生成結果。登録は行わず、利用者がコマンドを実行する。"""

    registered_name: str
    output_path: Path
    gguf_path: Path


def _validate_identifier(value: str, pattern: re.Pattern[str], label: str) -> str:
    normalized = value.strip()
    if not pattern.fullmatch(normalized):
        raise ModelfileValidationError(
            f"{label} must contain only letters, digits, '.', '_', '-', or permitted separators"
        )
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ModelfileValidationError(f"{label} must not contain empty, '.' or '..' segments")
    return normalized


def validate_model_name(model_name: str) -> str:
    """Ollamaタグ本体として使うモデル名を検証する。"""
    return _validate_identifier(model_name, MODEL_NAME_PATTERN, "model_name")


def validate_role(role: str) -> str:
    """Ollamaタグ末尾として使うroleを検証する。"""
    normalized = _validate_identifier(role, ROLE_PATTERN, "role")
    if "/" in normalized:
        raise ModelfileValidationError("role must not contain '/'")
    return normalized


def resolve_gguf_path(gguf_path: str | Path, allow_missing: bool = False) -> Path:
    """GGUFパスをプロジェクトルート基準で解決・検証する。"""
    path = Path(gguf_path)
    resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    if resolved.suffix.lower() != ".gguf":
        raise ModelfileValidationError(f"GGUF file must have a .gguf extension: {resolved}")
    if resolved.exists():
        if not resolved.is_file():
            raise ModelfileValidationError(f"GGUF path must be a regular file: {resolved}")
        if resolved.stat().st_size == 0:
            raise ModelfileValidationError(f"GGUF file must not be empty: {resolved}")
    elif not allow_missing:
        raise ModelfileValidationError(f"GGUF file was not found: {resolved}")
    return resolved


def validate_parameters(
    num_ctx: int,
    num_thread: int,
    num_gpu: int | None,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
) -> None:
    """ハードウェア・推論パラメータの安全な値域を検証する。"""
    if num_ctx < 1:
        raise ModelfileValidationError("num_ctx must be at least 1")
    if num_thread < 1:
        raise ModelfileValidationError("num_thread must be at least 1")
    if num_gpu is not None and num_gpu < 0:
        raise ModelfileValidationError("num_gpu must be 'auto' or at least 0")
    if not 0.0 <= temperature <= 2.0:
        raise ModelfileValidationError("temperature must be between 0.0 and 2.0")
    if not 0.0 < top_p <= 1.0:
        raise ModelfileValidationError("top_p must be greater than 0.0 and at most 1.0")
    if top_k < 1:
        raise ModelfileValidationError("top_k must be at least 1")
    if repeat_penalty <= 0.0:
        raise ModelfileValidationError("repeat_penalty must be greater than 0.0")


def load_system_prompt(system_prompt_file: str | Path | None) -> str:
    """UTF-8のSYSTEMプロンプトを読み、Modelfileを壊す区切り文字を拒否する。"""
    if system_prompt_file is None:
        return DEFAULT_SYSTEM_PROMPT
    path = Path(system_prompt_file)
    if not path.is_file():
        raise ModelfileValidationError(f"system_prompt_file must be a regular file: {path}")
    try:
        prompt = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ModelfileValidationError(f"system_prompt_file must be UTF-8: {path}") from exc
    if not prompt.strip():
        raise ModelfileValidationError("system_prompt_file must not be empty")
    if "\x00" in prompt or '"""' in prompt:
        raise ModelfileValidationError(
            "system_prompt_file contains unsupported Modelfile delimiters"
        )
    return prompt


def registered_model_name(model_name: str, role: str) -> str:
    """モデル名とroleからOllamaへ登録する論理名を作る。"""
    return f"{validate_model_name(model_name)}:{validate_role(role)}"


def modelfile_filename(model_name: str, role: str) -> str:
    """Windows安全かつ登録名と一対一対応するModelfileファイル名を返す。"""
    encoded_name = quote(registered_model_name(model_name, role), safe="._-")
    return f"Modelfile_{encoded_name}"


def get_modelfiles_dir() -> Path:
    """プロジェクト内の生成用Modelfileディレクトリを返す。"""
    return PROJECT_ROOT / "tools" / "modelfiles"


def _from_reference(gguf_path: Path, output_dir: Path) -> str:
    try:
        reference = Path(os.path.relpath(gguf_path, start=output_dir)).as_posix()
    except ValueError:
        reference = gguf_path.as_posix()
    return reference if reference.startswith(".") else f"./{reference}"


def generate_modelfile_content(
    gguf_reference: str,
    *,
    num_ctx: int,
    num_thread: int,
    num_gpu: int | None,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    template: str,
    system_prompt: str,
) -> str:
    """検証済み入力からQwen用Modelfile本文を生成する。"""
    if template != "qwen":
        raise ModelfileValidationError(f"Unsupported template: {template}")
    validate_parameters(num_ctx, num_thread, num_gpu, temperature, top_p, top_k, repeat_penalty)
    gpu_parameter = "" if num_gpu is None else f"PARAMETER num_gpu {num_gpu}\n"
    return f'''# Generated by tools/build_modelfile.py
# Registered name: {{registered_name_placeholder}}

FROM {gguf_reference}

PARAMETER num_ctx {num_ctx}
PARAMETER num_thread {num_thread}
{gpu_parameter}PARAMETER temperature {temperature}
PARAMETER top_p {top_p}
PARAMETER top_k {top_k}
PARAMETER repeat_penalty {repeat_penalty}

TEMPLATE """{QWEN_TEMPLATE}"""

SYSTEM """{system_prompt}"""
'''


def build_modelfile(
    gguf_path: str | Path,
    model_name: str,
    role: str,
    *,
    num_ctx: int = 8192,
    num_thread: int = 8,
    num_gpu: int | None = 32,
    temperature: float = 0.2,
    top_p: float = 0.9,
    top_k: int = 20,
    repeat_penalty: float = 1.05,
    template: str = "qwen",
    system_prompt_file: str | Path | None = None,
    allow_missing_gguf: bool = False,
    force: bool = False,
) -> ModelfileBuildResult:
    """検証済みの永続Modelfileを生成する。Ollama登録は実行しない。"""
    resolved_gguf = resolve_gguf_path(gguf_path, allow_missing=allow_missing_gguf)
    registered_name = registered_model_name(model_name, role)
    output_dir = get_modelfiles_dir()
    output_path = output_dir / modelfile_filename(model_name, role)
    prompt = load_system_prompt(system_prompt_file)
    content = generate_modelfile_content(
        _from_reference(resolved_gguf, output_dir),
        num_ctx=num_ctx,
        num_thread=num_thread,
        num_gpu=num_gpu,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repeat_penalty=repeat_penalty,
        template=template,
        system_prompt=prompt,
    ).replace("{registered_name_placeholder}", registered_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("w" if force else "x", encoding="utf-8", newline="\n") as output_file:
            output_file.write(content)
    except FileExistsError as exc:
        raise ModelfileValidationError(
            f"Modelfile already exists: {output_path}. Use --force to replace it."
        ) from exc
    return ModelfileBuildResult(registered_name, output_path, resolved_gguf)


def _parse_num_gpu(value: str) -> int | None:
    if value == "auto":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "num-gpu must be 'auto' or a non-negative integer"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("num-gpu must be 'auto' or a non-negative integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a validated Qwen Ollama Modelfile.")
    parser.add_argument(
        "--gguf-path", required=True, help="GGUF path, relative to the project root"
    )
    parser.add_argument("--model-name", required=True, help="Ollama model tag base name")
    parser.add_argument("--role", default="coder", help="Ollama model tag suffix")
    parser.add_argument("--template", required=True, choices=("qwen",), help="Chat template")
    parser.add_argument("--num-ctx", type=int, default=8192, help="Context window (at least 1)")
    parser.add_argument("--num-thread", type=int, default=8, help="CPU threads (at least 1)")
    parser.add_argument("--num-gpu", type=_parse_num_gpu, default=32, help="GPU layers or auto")
    parser.add_argument("--temperature", type=float, default=0.2, help="0.0 to 2.0")
    parser.add_argument("--top-p", type=float, default=0.9, help="greater than 0.0 to 1.0")
    parser.add_argument("--top-k", type=int, default=20, help="at least 1")
    parser.add_argument("--repeat-penalty", type=float, default=1.05, help="greater than 0.0")
    parser.add_argument("--system-prompt-file", help="UTF-8 text file used as the SYSTEM prompt")
    parser.add_argument(
        "--allow-missing-gguf",
        action="store_true",
        help="Allow Modelfile preparation before the GGUF file is placed",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing Modelfile with the same logical model name",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_modelfile(
            args.gguf_path,
            args.model_name,
            args.role,
            num_ctx=args.num_ctx,
            num_thread=args.num_thread,
            num_gpu=args.num_gpu,
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            repeat_penalty=args.repeat_penalty,
            template=args.template,
            system_prompt_file=args.system_prompt_file,
            allow_missing_gguf=args.allow_missing_gguf,
            force=args.force,
        )
    except ModelfileValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    relative_path = result.output_path.relative_to(PROJECT_ROOT).as_posix()
    print(f"Modelfile: {relative_path}")
    print(f"Registered name: {result.registered_name}")
    print("Review the generated file, then run:")
    print(f"ollama create {result.registered_name} -f ./{relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

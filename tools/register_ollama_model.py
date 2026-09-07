#!/usr/bin/env python3
"""GGUFファイルをOllamaのローカルモデルとして安全に登録するCLI・モジュール。"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.gguf_manager import GgufFileNotFoundError, validate_gguf_exists  # noqa: E402

logger = logging.getLogger("register_ollama_model")
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class OllamaRegistrationError(RuntimeError):
    """Ollamaモデルの登録前検証またはCLI実行が失敗した場合に送出する。"""


@dataclass(frozen=True)
class RegistrationResult:
    """登録処理の結果。dry-run時は実行コマンドの確認用途に使う。"""

    model_name: str
    gguf_path: Path
    command: tuple[str, ...]
    dry_run: bool


def _validate_model_name(model_name: str) -> str:
    normalized_name = model_name.strip()
    if not MODEL_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError(
            "model_name must contain only letters, digits, '.', '_', '-', '/', or ':'"
        )
    return normalized_name


def _validate_gguf_file(gguf_path: str | Path) -> Path:
    resolved_path = validate_gguf_exists(gguf_path, "Ollama registration")
    if resolved_path.suffix.lower() != ".gguf":
        raise ValueError(f"GGUF file must have a .gguf extension: {resolved_path}")
    return resolved_path


def _run_ollama(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise OllamaRegistrationError(
            f"Ollama command was not found: {command[0]}. Install Ollama or specify --ollama-command."
        ) from exc


def _assert_model_is_not_registered(
    model_name: str, ollama_command: str, allow_replace: bool
) -> None:
    if allow_replace:
        return

    result = _run_ollama((ollama_command, "list"))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise OllamaRegistrationError(f"Unable to list registered Ollama models: {detail}")

    registered_names = {
        line.split(maxsplit=1)[0]
        for line in result.stdout.splitlines()[1:]
        if line.strip()
    }
    if model_name in registered_names:
        raise OllamaRegistrationError(
            f"Ollama model '{model_name}' is already registered. Use --force to replace it."
        )


def _write_modelfile(gguf_path: Path) -> Path:
    """GGUFと同じディレクトリに一時Modelfileを作成し、相対FROMパスを使う。"""
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        suffix=".Modelfile",
        prefix=".ollama-register-",
        dir=gguf_path.parent,
        delete=False,
    ) as modelfile:
        modelfile.write(f"FROM ./{gguf_path.name}\n")
        return Path(modelfile.name)


def register_gguf_model(
    gguf_path: str | Path,
    model_name: str,
    *,
    ollama_command: str = "ollama",
    force: bool = False,
    dry_run: bool = False,
) -> RegistrationResult:
    """GGUFをOllamaモデルとして登録する。既存タグの置換にはforce=Trueが必要。"""
    resolved_path = _validate_gguf_file(gguf_path)
    normalized_name = _validate_model_name(model_name)
    if not ollama_command.strip():
        raise ValueError("ollama_command must not be empty")

    if dry_run:
        command = (ollama_command, "create", normalized_name, "-f", "<temporary Modelfile>")
        return RegistrationResult(normalized_name, resolved_path, command, dry_run=True)

    _assert_model_is_not_registered(normalized_name, ollama_command, force)
    modelfile_path = _write_modelfile(resolved_path)
    command = (ollama_command, "create", normalized_name, "-f", str(modelfile_path))
    try:
        result = _run_ollama(command)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise OllamaRegistrationError(
                f"Failed to register Ollama model '{normalized_name}': {detail}"
            )
    finally:
        modelfile_path.unlink(missing_ok=True)

    logger.info("Registered GGUF model '%s' with Ollama.", normalized_name)
    return RegistrationResult(normalized_name, resolved_path, command, dry_run=False)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register a standalone GGUF file as an Ollama local model."
    )
    parser.add_argument("gguf_path", help="Path to the GGUF file to register")
    parser.add_argument("model_name", help="Ollama model tag to create")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow replacement when the model tag is already registered",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print the planned registration without calling Ollama",
    )
    parser.add_argument(
        "--ollama-command",
        default="ollama",
        help="Ollama CLI command or executable path (default: ollama)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    )
    args = parse_args(argv)
    try:
        result = register_gguf_model(
            args.gguf_path,
            args.model_name,
            ollama_command=args.ollama_command,
            force=args.force,
            dry_run=args.dry_run,
        )
    except (GgufFileNotFoundError, OllamaRegistrationError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    if result.dry_run:
        logger.info(
            "Dry run: would register '%s' from '%s'.",
            result.model_name,
            result.gguf_path,
        )
    else:
        logger.info(
            "Registered '%s'. Configure it as an Ollama profile in config/models.json to use it.",
            result.model_name,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

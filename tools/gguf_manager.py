#!/usr/bin/env python3
"""tools/gguf_manager.py - GGUFモデルファイルの配置構造・パス解決・存在検証を管理するモジュール."""

import logging
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger("gguf_manager")


class GgufFileNotFoundError(FileNotFoundError):
    """GGUFモデルファイルが見つからない場合に送出される例外."""
    pass


def get_models_dir() -> Path:
    """
    プロジェクトルート直下の models/ ディレクトリの絶対パスを返す。
    """
    return Path(__file__).resolve().parent.parent / "models"


def ensure_models_dir() -> Path:
    """
    models/ ディレクトリが存在しない場合は作成し、その Path を返す。
    """
    models_dir = get_models_dir()
    if not models_dir.exists():
        logger.info(f"Creating models directory at: {models_dir}")
        models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def resolve_gguf_path(model_path: Union[str, Path]) -> Path:
    """
    モデルパス（相対パスまたは絶対パス）を受け取り、プロジェクトルート規約に従って解決した Path を返す。
    相対パスの場合はプロジェクトルート基準で解決する。
    """
    path = Path(model_path)
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parent.parent
        path = (project_root / path).resolve()
    return path


def validate_gguf_exists(model_path: Union[str, Path], role_description: str = "main") -> Path:
    """
    指定された GGUF モデルファイルが存在するかチェックする。
    存在する場合は解決された Path を返し、存在しない場合は GgufFileNotFoundError を送出する。
    """
    resolved_path = resolve_gguf_path(model_path)
    if not resolved_path.is_file():
        err_msg = (
            f"GGUF model file for '{role_description}' not found at: {resolved_path}\n"
            f"Please ensure the GGUF file is placed in '{get_models_dir()}' "
            f"or update the 'model_path' setting in 'config/models.json'."
        )
        logger.error(err_msg)
        raise GgufFileNotFoundError(err_msg)
    return resolved_path


def list_gguf_models() -> List[Path]:
    """
    models/ ディレクトリ内に配置されている *.gguf ファイルのリストを返す。
    """
    models_dir = ensure_models_dir()
    return sorted(list(models_dir.glob("*.gguf")))

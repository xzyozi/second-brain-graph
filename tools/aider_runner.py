import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("aider_runner")


class AiderRunError(Exception):
    """Aider 実行時のタイムアウトおよびシステムエラー例外"""

    pass


class GitDiffError(Exception):
    """Git diff 取得失敗時の例外 (fail-closed 契約)"""

    pass


def get_default_aider_model() -> str:
    """config/models.json から Aider 編集用のモデル名を取得する (DD-003 仕様準拠).
    取得失敗時は警告ログを出力しフォールバックモデル名を返す。
    """
    try:
        from tools.config_loader import get_backend_execution_config

        config = get_backend_execution_config()
        profile_name = config.routes.get("aider_edit") or config.routes.get("code_edit")
        if profile_name and profile_name in config.profiles:
            profile = config.profiles[profile_name]
            model_name = profile.model
            if profile.backend == "ollama" and not model_name.startswith("ollama/"):
                return f"ollama/{model_name}"
            return model_name
    except Exception as e:
        logger.error(f"Failed to load model config for Aider, using fallback: {e}")
    return "ollama/qwen2.5-coder:7b-instruct"


def get_git_diff(cwd: Optional[str] = None) -> str:
    """現在の Git 作業ツリーの差分を取得する。失敗時は GitDiffError を送出する (fail-closed).
    初期コミット前のリポジトリ等で HEAD が存在しない場合はフォールバックして差分を取得する。
    """
    try:
        # 新規作成された未追跡ファイル (untracked files) も git diff 対象に含めるため intent-to-add を設定
        subprocess.run(
            ["git", "add", "-N", "."],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if res.returncode != 0:
            err_msg = res.stderr.lower()
            if (
                "bad revision" in err_msg
                or "ambiguous argument 'head'" in err_msg
                or "unknown revision" in err_msg
            ):
                # Fallback for initial commit (no HEAD)
                # Capture both staged and unstaged changes since 'git diff HEAD' is unavailable.
                diffs = []
                cached_res = subprocess.run(
                    ["git", "diff", "--cached"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if cached_res.returncode == 0 and cached_res.stdout:
                    diffs.append(cached_res.stdout)

                unstaged_res = subprocess.run(
                    ["git", "diff"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if unstaged_res.returncode == 0 and unstaged_res.stdout:
                    diffs.append(unstaged_res.stdout)

                if cached_res.returncode == 0 and unstaged_res.returncode == 0:
                    return "\n".join(diffs)
            raise GitDiffError(
                f"git diff command failed with returncode {res.returncode}: {res.stderr}"
            )
        return res.stdout
    except Exception as e:
        if isinstance(e, GitDiffError):
            raise
        raise GitDiffError(f"Failed to execute git diff: {e}") from e


def cleanup_unauthorized_aider_artifacts(cwd: Optional[str], target_files: List[str]) -> List[str]:
    """Aider がプロンプトの会話文等を誤って新規ファイルとして作成した場合、
    target_files 以外の意図しない不正ファイルを自動検知して削除し Git ステータスを正常化する。
    """
    removed: List[str] = []
    if not cwd:
        return removed
    cwd_path = Path(cwd)
    normalized_targets = {Path(tf).as_posix() for tf in target_files}

    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if not line.strip():
                    continue
                raw_filename = line[3:].strip().strip('"')
                posix_file = Path(raw_filename).as_posix()

                if (
                    posix_file not in normalized_targets
                    and not posix_file.startswith(".aider")
                    and not posix_file.startswith(".pytest")
                    and not posix_file == ".gitignore"
                ):
                    file_path = cwd_path / raw_filename
                    if file_path.exists() and file_path.is_file():
                        logger.warning(
                            f"[Aider Sanitizer] Detected and removing unauthorized artifact: {raw_filename}"
                        )
                        try:
                            subprocess.run(
                                ["git", "rm", "-f", "--", raw_filename],
                                cwd=cwd,
                                capture_output=True,
                                text=True,
                                check=False,
                                timeout=10,
                            )
                            if file_path.exists():
                                file_path.unlink()
                            removed.append(raw_filename)
                        except Exception as ce:
                            logger.warning(f"Failed to remove unauthorized file {raw_filename}: {ce}")
    except Exception as e:
        logger.warning(f"Failed to check git status for unauthorized artifacts: {e}")
    return removed


def run_aider(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
    edit_format: Optional[str] = None,
) -> bool:
    """Aider CLI を subprocess 経由で非対話形式で実行する。
    - Ollama API ベースが指定されている場合、末尾の /v1 サフィックスを自動除去する。
    - config/models.json から edit_format および timeout (デフォルト 1200秒/20分) を動的に設定可能。
    - タイムアウトおよび非ゼロ終了時は AiderRunError を発生させる。
    - 対象ファイルが存在しない場合は警告ログを出力し、新規ファイル作成を許可する。
    """
    if model is None:
        model = get_default_aider_model()

    if edit_format is None or timeout is None:
        try:
            from tools.config_loader import get_aider_config

            aider_cfg = get_aider_config()
            if edit_format is None:
                edit_format = aider_cfg.edit_format
            if timeout is None:
                timeout = aider_cfg.timeout
        except Exception as e:
            logger.warning(f"Failed to load Aider config: {e}")

    if timeout is None:
        timeout = 1200

    cwd_path = Path(cwd) if cwd else Path.cwd()
    for tf in target_files:
        abs_path = cwd_path / tf
        if not abs_path.exists():
            logger.warning(f"Target file does not exist (will be created by Aider): {abs_path}")

    env = os.environ.copy()
    env["AIDER_SHOW_MODEL_WARNINGS"] = "false"

    # Ollama API ベースサフィックスの自動サニタイズ
    if "OLLAMA_API_BASE" in env:
        api_base = env["OLLAMA_API_BASE"]
        if api_base.endswith("/v1"):
            env["OLLAMA_API_BASE"] = api_base[:-3]
        elif api_base.endswith("/v1/"):
            env["OLLAMA_API_BASE"] = api_base[:-4]

    msg_file = None
    try:
        cmd = [
            "aider",
            "--model",
            model,
            "--no-auto-commits",
            "--yes-always",
            "--no-show-model-warnings",
        ]

        if edit_format:
            cmd.extend(["--edit-format", edit_format])

        # Windows コマンドライン長制限 (WinError 206) 回避および並行実行競合防止のため UUID 一時ファイルを使用
        msg_filename = f".aider.instruction_{uuid.uuid4().hex[:8]}.tmp"
        msg_path = cwd_path / msg_filename
        msg_path.write_text(instruction, encoding="utf-8")
        msg_file = msg_path

        cmd.extend(["--message-file", str(msg_path.resolve())])
        cmd.extend(target_files)

        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # 不正な前置き文等による意図しない新規ファイルの自動排除
        cleanup_unauthorized_aider_artifacts(cwd, target_files)

        if result.returncode != 0:
            logger.error(f"Aider failed with exit code {result.returncode}: {result.stderr}")
            raise AiderRunError(
                f"Aider process failed with returncode {result.returncode}: {result.stderr}"
            )
        return True
    except subprocess.TimeoutExpired as e:
        cleanup_unauthorized_aider_artifacts(cwd, target_files)
        raise AiderRunError(f"Aider execution timed out after {timeout} seconds") from e
    except AiderRunError:
        raise
    except Exception as e:
        cleanup_unauthorized_aider_artifacts(cwd, target_files)
        raise AiderRunError(f"Failed to run Aider CLI: {e}") from e
    finally:
        if msg_file and msg_file.exists():
            try:
                msg_file.unlink()
            except Exception:
                pass

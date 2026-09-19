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


def get_git_diff(cwd: Optional[str] = None, base_branch: Optional[str] = None) -> str:
    """現在の Git 作業ツリーの差分を取得する。失敗時は GitDiffError を送出する (fail-closed).
    初期コミット前のリポジトリ等で HEAD が存在しない場合はフォールバックして差分を取得する。
    HEAD との差分が空の場合で base_branch が指定されている場合、ブランチ全体の差分 (origin/{base_branch}...HEAD) をフォールバック取得する。
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

        diff_out = res.stdout
        # HEAD との差分が空で base_branch が指定されている場合、コミット済み差分をフォールバック取得
        if not diff_out.strip() and base_branch:
            for branch_ref in [f"origin/{base_branch}...HEAD", f"{base_branch}...HEAD"]:
                branch_diff = subprocess.run(
                    ["git", "diff", branch_ref],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                if branch_diff.returncode == 0 and branch_diff.stdout.strip():
                    return branch_diff.stdout

        return diff_out
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
                            logger.warning(
                                f"Failed to remove unauthorized file {raw_filename}: {ce}"
                            )
    except Exception as e:
        logger.warning(f"Failed to check git status for unauthorized artifacts: {e}")
    return removed


def get_max_target_file_lines(cwd: Optional[str], target_files: List[str]) -> int:
    """対象ファイル群の中で最大の行数を返す（未存在ファイルは 0 行）。"""
    max_lines = 0
    cwd_path = Path(cwd) if cwd else Path.cwd()
    for tf in target_files:
        abs_path = cwd_path / tf
        if abs_path.exists() and abs_path.is_file():
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                max_lines = max(max_lines, len(content.splitlines()))
            except Exception as e:
                logger.warning(f"Failed to read line count for {tf}: {e}")
    return max_lines


def resolve_effective_edit_format(
    edit_format: Optional[str],
    max_lines: int,
    threshold: int = 100,
) -> str:
    """ハイブリッド設定または明示設定から、実際に使用する edit_format を決定する。"""
    fmt = (edit_format or "whole").lower()
    if fmt == "hybrid":
        if max_lines >= threshold:
            logger.info(
                f"Hybrid mode: max file lines={max_lines} >= threshold={threshold}. "
                "Selecting 'diff' format for accelerated editing."
            )
            return "diff"
        else:
            logger.info(
                f"Hybrid mode: max file lines={max_lines} < threshold={threshold}. "
                "Selecting 'whole' format for safe editing."
            )
            return "whole"
    return fmt


def revert_working_tree_files(cwd: Optional[str], target_files: List[str]) -> None:
    """フォールバック実行前に target_files の変更を元に戻す。"""
    if not target_files:
        return
    try:
        cmd = ["git", "checkout", "--"] + target_files
        subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as e:
        logger.warning(f"Failed to revert files with git checkout: {e}")
    cleanup_unauthorized_aider_artifacts(cwd, target_files)


def _execute_aider_single(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str],
    model: str,
    timeout: int,
    format_to_run: str,
) -> bool:
    """指定された edit_format で Aider CLI プロセスを単一実行する。"""
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
            "--edit-format",
            format_to_run,
        ]

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
        cleanup_unauthorized_aider_artifacts(cwd, target_files)

        if result.returncode != 0:
            logger.error(
                f"Aider failed (format={format_to_run}) with exit code {result.returncode}: {result.stderr}"
            )
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


def run_aider(
    instruction: str,
    target_files: List[str],
    cwd: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
    edit_format: Optional[str] = None,
    hybrid_line_threshold: Optional[int] = None,
    fallback_to_whole: Optional[bool] = None,
) -> bool:
    """Aider CLI を subprocess 経由で非対話形式で実行する。
    - config/models.yaml から edit_format, timeout, hybrid_line_threshold, fallback_to_whole を動的に取得。
    - edit_format='hybrid' 時:
        - 100行未満（新規ファイル含む）➔ 'whole' で安全実行
        - 100行以上 ➔ 'diff' で高速実行
    - fallback_to_whole=True 時:
        - 'diff' / 'udiff' 実行で失敗した場合、自動でワーキングツリーを退避復元し、'whole' で再実行。
    """
    if model is None:
        model = get_default_aider_model()

    if (
        edit_format is None
        or timeout is None
        or hybrid_line_threshold is None
        or fallback_to_whole is None
    ):
        try:
            from tools.config_loader import get_aider_config

            aider_cfg = get_aider_config()
            if edit_format is None:
                edit_format = aider_cfg.edit_format
            if timeout is None:
                timeout = aider_cfg.timeout
            if hybrid_line_threshold is None:
                hybrid_line_threshold = aider_cfg.hybrid_line_threshold
            if fallback_to_whole is None:
                fallback_to_whole = aider_cfg.fallback_to_whole
        except Exception as e:
            logger.warning(f"Failed to load Aider config: {e}")

    if timeout is None:
        timeout = 1200
    if hybrid_line_threshold is None:
        hybrid_line_threshold = 100
    if fallback_to_whole is None:
        fallback_to_whole = True

    # 最大ファイル行数を判定して実効 edit_format を決定
    max_lines = get_max_target_file_lines(cwd, target_files)
    effective_format = resolve_effective_edit_format(
        edit_format, max_lines, threshold=hybrid_line_threshold
    )

    logger.info(
        f"Running Aider with model='{model}', format='{effective_format}' "
        f"(max_lines={max_lines}, fallback_to_whole={fallback_to_whole})"
    )

    # diff / udiff の場合に whole への自動フォールバックを適用
    if effective_format in ["diff", "udiff"] and fallback_to_whole:
        try:
            return _execute_aider_single(
                instruction=instruction,
                target_files=target_files,
                cwd=cwd,
                model=model,
                timeout=timeout,
                format_to_run=effective_format,
            )
        except AiderRunError as e:
            logger.warning(
                f"Aider execution with format '{effective_format}' failed: {e}. "
                "Reverting changes and falling back to 'whole' format for safe recovery."
            )
            revert_working_tree_files(cwd, target_files)
            return _execute_aider_single(
                instruction=instruction,
                target_files=target_files,
                cwd=cwd,
                model=model,
                timeout=timeout,
                format_to_run="whole",
            )

    return _execute_aider_single(
        instruction=instruction,
        target_files=target_files,
        cwd=cwd,
        model=model,
        timeout=timeout,
        format_to_run=effective_format,
    )

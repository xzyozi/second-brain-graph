"""Aider Runner module for Second Brain OS.

Executes Aider CLI using configured models (e.g. Gemini 4 / Code Py).
"""

import os
import subprocess
from typing import List, Optional

from tools.backend_coordinator import get_coordinator
from tools.config_loader import ProfileConfig, load_model_config


class AiderRunError(Exception):
    """Raised when Aider CLI execution fails or times out."""
    pass


def run_aider(
    instruction: str,
    target_files: List[str],
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: Optional[int] = 600,
) -> bool:
    """Run Aider CLI to apply non-destructive code edits based on instruction."""
    coordinator = get_coordinator()
    intent = "aider_edit"

    def _do_run_aider(profile: ProfileConfig) -> bool:
        config = load_model_config()
        aider_cfg = config.aider

        target_model = model or profile.model
        if not target_model:
            raise ValueError("Profile provided by Coordinator is missing 'model'.")

        is_ollama = profile.backend == "ollama"
        has_prefix = target_model.startswith("ollama/") or target_model.startswith("ollama_chat/")
        if is_ollama and not has_prefix:
            target_model = f"ollama/{target_model}"

        no_auto_commits = aider_cfg.no_auto_commits

        cmd = ["aider", "--model", target_model, "--yes-always"]

        if no_auto_commits:
            cmd.append("--no-auto-commits")

        cmd.extend(["--message", instruction])
        cmd.extend(target_files)

        env = os.environ.copy()
        # Coordinator のアダプタが patch_env で設定した OLLAMA_API_BASE 等を継承する
        if "OLLAMA_API_BASE" in env and env["OLLAMA_API_BASE"].endswith("/v1"):
            env["OLLAMA_API_BASE"] = env["OLLAMA_API_BASE"].removesuffix("/v1")

        eff_timeout = timeout if timeout is not None else getattr(aider_cfg, "timeout", 600)

        try:
            print(f"[AiderRunner] Running Aider with model '{target_model}' on {target_files}...")
            res = subprocess.run(cmd, cwd=cwd, env=env, check=True, timeout=eff_timeout)
            return res.returncode == 0
        except subprocess.TimeoutExpired as e:
            msg = f"Aider実行がタイムアウトしました (timeout={eff_timeout})"
            print(f"[AiderRunner] Error: {msg}")
            raise AiderRunError(msg) from e
        except FileNotFoundError:
            print("[AiderRunner] Error: Aider CLI is not installed in the current environment.")
            return False
        except subprocess.CalledProcessError as e:
            print(f"[AiderRunner] Aider execution failed with exit code {e.returncode}")
            return False
        except Exception as e:
            print(f"[AiderRunner] Unexpected error executing Aider: {e}")
            return False

    return coordinator.execute(intent, {"action": _do_run_aider})


def get_git_diff(cwd: Optional[str] = None) -> str:
    """Get the current uncommitted git diff for the target project repository."""
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout
    except Exception as e:
        print(f"[AiderRunner] Failed to fetch git diff: {e}")
        return ""



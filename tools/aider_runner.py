"""Aider Runner module for Second Brain OS.

Executes Aider CLI using configured models (e.g. Gemini 4 / Code Py).
"""

import os
import subprocess
from typing import List, Optional

from tools.config_loader import get_model_name, load_model_config


def run_aider(
    instruction: str,
    target_files: List[str],
    model: Optional[str] = None,
    cwd: Optional[str] = None,
) -> bool:
    """Run Aider CLI to apply non-destructive code edits based on instruction."""
    config = load_model_config()
    aider_cfg = config.get("aider", {})

    target_model = model or get_model_name("aider")
    no_auto_commits = aider_cfg.get("no_auto_commits", True)

    cmd = ["aider", "--model", target_model]

    if no_auto_commits:
        cmd.append("--no-auto-commits")

    cmd.extend(["--message", instruction])
    cmd.extend(target_files)

    env = os.environ.copy()
    api_base = config.get("api_base")
    if api_base:
        env["OLLAMA_API_BASE"] = api_base

    try:
        print(f"[AiderRunner] Running Aider with model '{target_model}' on {target_files}...")
        res = subprocess.run(cmd, cwd=cwd, env=env, check=True)
        return res.returncode == 0
    except FileNotFoundError:
        print("[AiderRunner] Error: Aider CLI is not installed in the current environment.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"[AiderRunner] Aider execution failed with exit code {e.returncode}")
        return False
    except Exception as e:
        print(f"[AiderRunner] Unexpected error executing Aider: {e}")
        return False

"""llama-server プロセスを起動・監視・終了する Adapter。"""

import logging
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)


@contextmanager
def managed_llama_server(
    model_path: str,
    port: int,
    *,
    executable: str = "llama-server.exe",
    ctx_size: int = 131072,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """llama-server を起動し、終了時にプロセスとポートを必ず解放する。"""
    command = [
        executable,
        "-m",
        model_path,
        "-ngl",
        "99",
        "-c",
        str(ctx_size),
        "--port",
        str(port),
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    health_url = f"http://localhost:{port}/health"

    for _ in range(60):
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.getcode() == 200:
                    break
        except (urllib.error.URLError, ConnectionResetError):
            if process.poll() is not None:
                raise RuntimeError("llama-server failed to start.") from None
            time.sleep(2)
    else:
        process.terminate()
        raise TimeoutError("llama-server did not become healthy within 120 seconds.")

    try:
        yield process
    finally:
        logger.info("Terminating llama-server and freeing VRAM.")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

        for _ in range(10):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                if connection.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(1)
        else:
            raise RuntimeError(f"llama-server failed to free port {port} after termination.")

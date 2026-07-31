#!/usr/bin/env python3
"""tools/llama_backend.py - llama.cpp (llama-server) の動的制御モジュール."""

from contextlib import contextmanager
import logging
import socket
import subprocess
import time
from typing import Generator
import urllib.error
import urllib.request

logger = logging.getLogger("llama_backend")

@contextmanager
def managed_llama_server(
    model_path: str = "./models/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
    draft_model_path: str = "./models/mtp-gemma-4-12B-it.gguf",
    port: int = 8080,
    ctx_size: int = 131072,
    executable: str = "llama-server.exe"
) -> Generator[subprocess.Popen, None, None]:
    """
    指定されたパラメータで llama-server をバックグラウンド起動し、ブロックを抜ける際に終了(VRAM解放)する。
    """
    cmd = [
        executable,
        "-m", model_path,
        "--model-draft", draft_model_path,
        "-ngl", "99",
        "-ngld", "99",
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "4",
        "-c", str(ctx_size),
        "-fa", "on",
        "--jinja",
        "-np", "1",
        "-ctk", "q8_0",
        "-ctv", "q8_0",
        "-ctkd", "f16",
        "-ctvd", "f16",
        "-b", "4096",
        "-ub", "1280",
        "--port", str(port)
    ]

    logger.info(f"Starting llama-server dynamically on port {port}...")
    logger.debug(f"Command: {' '.join(cmd)}")

    # サーバープロセスの起動 (標準出力・エラー出力は親プロセスに流すか捨てる)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # サーバーがリクエストを受け付けられるまでポーリング待機
    health_url = f"http://localhost:{port}/health"
    max_retries = 60
    ready = False

    for i in range(max_retries):
        try:
            req = urllib.request.urlopen(health_url, timeout=2)
            if req.getcode() == 200:
                ready = True
                logger.info(f"llama-server is ready and listening on port {port}.")
                break
        except (urllib.error.URLError, ConnectionResetError):
            pass

        # プロセスが予期せず落ちていないか確認
        if process.poll() is not None:
            logger.error(f"llama-server terminated unexpectedly with exit code {process.returncode}")
            raise RuntimeError("llama-server failed to start.")

        time.sleep(2)

    if not ready:
        process.terminate()
        raise TimeoutError(f"llama-server did not become healthy within {max_retries * 2} seconds.")

    try:
        # yieldして呼び出し元のブロックを実行
        yield process
    finally:
        # 処理完了後、または例外発生時に確実にプロセスを終了してVRAMを解放する
        logger.info("Terminating llama-server and freeing VRAM...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("llama-server did not terminate gracefully, forcing kill...")
            process.kill()
            process.wait()

        # ポート解放を監査 (VRAM解放の確実な担保)
        logger.info("Auditing port release...")
        port_freed = False
        for _ in range(10):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                result = s.connect_ex(('127.0.0.1', port))
                if result != 0:
                    port_freed = True
                    break
            time.sleep(1)

        if not port_freed:
            raise RuntimeError(f"llama-server failed to free port {port} after termination.")

        logger.info("VRAM has been completely freed.")


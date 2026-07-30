#!/usr/bin/env python3
"""tools/backend_coordinator.py - LLMバックエンドの排他併用を管理するCoordinator."""

import os
import time
import logging
import urllib.request
import urllib.error
import json
from typing import Any, Dict, Callable
from pathlib import Path

from tools.config_loader import get_backend_execution_config
from tools.llama_backend import managed_llama_server

logger = logging.getLogger("backend_coordinator")

class GpuLeaseAdapter:
    """GPUリースの排他制御を管理するアダプタ"""
    def __init__(self, lock_file: str = "metadata/.gpu_lease.lock"):
        self.lock_file = Path(lock_file)
        self.stale_timeout = 7200

    def acquire(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                with os.fdopen(fd, 'w') as f:
                    f.write(str(os.getpid()))
                logger.info("GPU lease acquired.")
                return
            except FileExistsError:
                mtime = os.path.getmtime(self.lock_file)
                if time.time() - mtime > self.stale_timeout:
                    logger.warning("Stale GPU lease detected. Removing...")
                    try:
                        self.lock_file.unlink()
                        continue
                    except Exception:
                        pass
                logger.info("Waiting for GPU lease...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error acquiring GPU lease: {e}")
                raise

    def release(self):
        try:
            self.lock_file.unlink()
            logger.info("GPU lease released.")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Error releasing GPU lease: {e}")


def unload_ollama_models():
    """Ollamaにロードされているモデルを解放する"""
    try:
        # ps api で現在ロードされているモデルを取得
        req = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=2)
        if req.getcode() == 200:
            data = json.loads(req.read().decode('utf-8'))
            models = data.get("models", [])
            for m in models:
                model_name = m.get("name")
                if model_name:
                    logger.info(f"Unloading Ollama model: {model_name}")
                    unload_req = urllib.request.Request(
                        "http://localhost:11434/api/generate",
                        data=json.dumps({"model": model_name, "keep_alive": 0}).encode('utf-8'),
                        headers={'Content-Type': 'application/json'}
                    )
                    urllib.request.urlopen(unload_req, timeout=5)
    except Exception as e:
        logger.debug(f"Failed to check/unload Ollama models (Ollama might not be running): {e}")


class OllamaBackendAdapter:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Callable = request.get("action")
        if not action:
            raise ValueError("OllamaBackendAdapter requires an 'action' callable in request")
        
        logger.info(f"Executing workload on Ollama backend with profile: {self.profile}")
        
        # AiderやLLMクライアント向けに環境変数を設定
        api_base = "http://localhost:11434"
        os.environ["OLLAMA_API_BASE"] = api_base
        
        # Actionの実行
        return action()


class LlamaServerBackendAdapter:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Callable = request.get("action")
        if not action:
            raise ValueError("LlamaServerBackendAdapter requires an 'action' callable in request")
        
        model_name = self.profile.get("model", "gemma-4-12B-it-qat-UD-Q4_K_XL")
        # GGUFパスの簡易マッピング（実際は設定やディレクトリ構造に依存）
        model_path = f"./models/{model_name}.gguf"
        
        logger.info(f"Executing workload on llama-server backend with profile: {self.profile}")
        
        # Ollama のVRAMを解放する
        unload_ollama_models()
        
        # クライアント向けの環境変数を設定
        os.environ["OPENAI_API_BASE"] = "http://localhost:8080/v1"
        os.environ["OLLAMA_API_BASE"] = "http://localhost:8080/v1"

        # llama-server を起動してタスクを実行し、完了後にプロセスを停止
        with managed_llama_server(model_path=model_path, port=8080):
            return action()


class BackendExecutionCoordinator:
    def __init__(self):
        self.config = get_backend_execution_config()
        self.gpu_lease = GpuLeaseAdapter()

    def execute(self, intent: str, request: Dict[str, Any]) -> Any:
        """
        intent (e.g. 'spec_draft', 'aider_edit') に基づいてプロファイルを選択し、
        GPUリースを取得した上で、適切なバックエンドアダプタを介してリクエストを実行する。
        """
        routes = self.config.get("routes", {})
        profiles = self.config.get("profiles", {})
        
        profile_name = routes.get(intent)
        if not profile_name:
            logger.warning(f"No route found for intent '{intent}'. Falling back to coding_ollama.")
            profile_name = "coding_ollama"
            
        profile = profiles.get(profile_name, {})
        backend_type = profile.get("backend", "ollama")
        
        logger.info(f"Resolved intent '{intent}' to profile '{profile_name}' (backend: {backend_type})")
        
        adapter = None
        if backend_type == "llama_server":
            adapter = LlamaServerBackendAdapter(profile)
        elif backend_type == "ollama":
            adapter = OllamaBackendAdapter(profile)
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")

        self.gpu_lease.acquire()
        try:
            return adapter.execute(request)
        except Exception as e:
            logger.error(f"Execution failed on backend {backend_type} for intent {intent}: {e}")
            raise
        finally:
            self.gpu_lease.release()

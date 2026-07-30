#!/usr/bin/env python3
"""tools/backend_coordinator.py - LLMバックエンドの排他併用を管理するCoordinator."""

import os
import time
import logging
import urllib.request
import urllib.error
import json
import contextlib
from typing import Any, Dict, Callable, Optional, Iterator, Union
from pathlib import Path
from filelock import FileLock, Timeout

from tools.config_loader import get_backend_execution_config, ProfileConfig
from tools.llama_backend import managed_llama_server

logger = logging.getLogger("backend_coordinator")

@contextlib.contextmanager
def patch_env(**env_vars: str) -> Iterator[None]:
    """
    一時的に環境変数を設定し、ブロック終了後に元の状態へ復元するコンテキストマネージャ。
    
    Args:
        **env_vars: 設定する環境変数のキーと値
    """
    original = {k: os.environ.get(k) for k in env_vars.keys()}
    os.environ.update(env_vars)
    try:
        yield
    finally:
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class GpuLeaseAdapter:
    """
    GPUリースの排他制御を管理するアダプタ。
    
    ローカルの単一GPU (VRAM) を Ollama と llama-server で安全に排他利用するため、
    filelock (OSネイティブロック) を用いたリース管理を行う。
    プロセス異常終了時は OS がロックを自動回収するため TOCTOU の心配がない。
    """
    def __init__(self, lock_file: str = ".gpu_lease.lock") -> None:
        lock_path = Path(__file__).resolve().parent.parent / "metadata" / lock_file
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(lock_path), timeout=60)

    def acquire(self) -> None:
        """
        GPUリースを取得する。取得できない場合はTimeoutErrorを送出する。
        """
        try:
            logger.info("Waiting for GPU lease...")
            self.lock.acquire()
            logger.info("GPU lease acquired.")
        except Timeout:
            logger.error("Failed to acquire GPU lease within timeout.")
            raise TimeoutError("Failed to acquire GPU lease within 60 seconds.")

    def release(self) -> None:
        """
        GPUリースを解放する。
        """
        try:
            self.lock.release()
            logger.info("GPU lease released.")
        except Exception as e:
            logger.error(f"Error releasing GPU lease: {e}")


def unload_ollama_models(endpoint: str, assume_free_on_offline: bool) -> None:
    """Ollamaにロードされているモデルを解放する"""
    if endpoint.endswith("/v1") or endpoint.endswith("/v1/"):
        base_url = endpoint.rsplit("/v1", 1)[0]
    else:
        base_url = endpoint

    ps_url = f"{base_url.rstrip('/')}/api/ps"
    gen_url = f"{base_url.rstrip('/')}/api/generate"

    try:
        # ps api で現在ロードされているモデルを取得
        req = urllib.request.urlopen(ps_url, timeout=2)
        if req.getcode() == 200:
            data = json.loads(req.read().decode('utf-8'))
            models = data.get("models", [])
            for m in models:
                model_name = m.get("name")
                if model_name:
                    logger.info(f"Unloading Ollama model: {model_name}")
                    unload_req = urllib.request.Request(
                        gen_url,
                        data=json.dumps({"model": model_name, "keep_alive": 0}).encode('utf-8'),
                        headers={'Content-Type': 'application/json'}
                    )
                    urllib.request.urlopen(unload_req, timeout=5)
            
            # Verify unloading
            start_time = time.time()
            while time.time() - start_time < 10:
                req = urllib.request.urlopen(ps_url, timeout=2)
                if req.getcode() == 200:
                    data = json.loads(req.read().decode('utf-8'))
                    if not data.get("models"):
                        return
                time.sleep(1)
            raise RuntimeError("Failed to unload Ollama models within timeout. VRAM might not be freed.")
            
    except urllib.error.URLError as e:
        if assume_free_on_offline:
            logger.info(f"Ollama appears to be offline or unreachable: {e}. Assuming VRAM is free.")
        else:
            logger.error(f"Ollama appears to be offline or unreachable: {e}. Cannot guarantee VRAM is free. Aborting.")
            raise RuntimeError(f"Ollama unreachable: {e}. To ignore, set assume_free_on_offline=true in profile.")


class OllamaBackendAdapter:
    """
    Ollama バックエンドのタスク実行アダプタ。
    
    実行時に OLLAMA_API_BASE を一時的に環境変数としてパッチし、
    タスク終了後に元に戻す（副作用をブロック内に閉じ込める）。
    """
    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Optional[Callable[..., Any]] = request.get("action")
        if action is None:
            raise ValueError("OllamaBackendAdapter requires an 'action' callable in request")
        
        logger.info(f"Executing workload on Ollama backend with profile: {self.profile}")
        
        endpoint = self.profile.endpoint
        
        with patch_env(OLLAMA_API_BASE=endpoint, OPENAI_API_BASE=endpoint):
            return action(self.profile)


class LlamaServerBackendAdapter:
    """
    llama-server バックエンドのタスク実行アダプタ。
    
    実行前に Ollama の VRAM を解放し、llama-server プロセスを起動する。
    実行中は APIエンドポイントを :8080/v1 に一時パッチし、
    タスク終了時には必ずプロセスを終了（VRAM解放）させ、環境変数を復元する。
    """
    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Optional[Callable[..., Any]] = request.get("action")
        if action is None:
            raise ValueError("LlamaServerBackendAdapter requires an 'action' callable in request")
        
        model_path = self.profile.model_path
        port = self.profile.port
        endpoint = self.profile.endpoint
        assume_free = self.profile.assume_free_on_offline
        
        # Pydantic validates port and model_path for llama_server
        assert model_path is not None
        assert port is not None
            
        logger.info(f"Executing workload on llama-server backend with profile: {self.profile}")
        
        unload_ollama_models(endpoint=endpoint, assume_free_on_offline=assume_free)
        
        with patch_env(OPENAI_API_BASE=endpoint, OLLAMA_API_BASE=endpoint):
            with managed_llama_server(model_path=model_path, port=port):
                return action(self.profile)


class BackendExecutionCoordinator:
    def __init__(self) -> None:
        self.config = get_backend_execution_config()
        self.gpu_lease = GpuLeaseAdapter()

    def execute(self, intent: str, request: Dict[str, Any]) -> Any:
        """
        intent (e.g. 'spec_draft', 'aider_edit') に基づいてプロファイルを選択し、
        GPUリースを取得した上で、適切なバックエンドアダプタを介してリクエストを実行する。
        """
        routes = self.config.routes
        profiles = self.config.profiles
        
        profile_name = routes.get(intent)
        if not profile_name:
            raise ValueError(f"No route mapped for intent '{intent}'. Explicit routing is required.")
            
        profile = profiles.get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' is not defined in backend profiles.")
        
        backend_type = profile.backend
        
        logger.info(f"Resolved intent '{intent}' to profile '{profile_name}' (backend: {backend_type})")
        
        adapter: Union[LlamaServerBackendAdapter, OllamaBackendAdapter]
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

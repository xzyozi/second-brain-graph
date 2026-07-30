#!/usr/bin/env python3
"""tools/backend_coordinator.py - LLMバックエンドの排他併用を管理するCoordinator."""

import os
import time
import logging
import urllib.request
import urllib.error
import json
import contextlib
import uuid
from typing import Any, Dict, Callable, Optional, Iterator, Union
from pathlib import Path

from tools.config_loader import get_backend_execution_config
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
    ファイルロックを用いたリース管理を行う。プロセス生存確認により、
    クラッシュ時の不要なロック（Stale Lock）を安全にパージする。
    """
    def __init__(self, lock_file: str = ".gpu_lease.lock") -> None:
        self.lock_file = Path(__file__).resolve().parent.parent / "metadata" / lock_file
        self.max_wait_timeout = 60  # 最大待機時間 (秒)
        self.owner_token = uuid.uuid4().hex

    def acquire(self) -> None:
        """
        GPUリースを取得する。取得できない場合はTimeoutErrorを送出する。
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        
        while True:
            try:
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                with os.fdopen(fd, 'w') as f:
                    f.write(f"{os.getpid()}:{self.owner_token}")
                logger.info("GPU lease acquired.")
                return
            except FileExistsError:
                # 所有者プロセスの生存確認
                try:
                    with open(self.lock_file, 'r') as f:
                        content = f.read().strip()
                        if ":" in content:
                            pid_str, _ = content.split(":", 1)
                        else:
                            pid_str = content
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        try:
                            # 自身のプロセスでない、かつ対象のPIDのプロセスが存在するかチェック
                            # Windows の場合 os.kill(pid, 0) は機能しない場合があるため考慮が必要だが
                            # Python 3.8+ では利用可能
                            os.kill(pid, 0)
                        except OSError:
                            # プロセスが存在しない -> Stale Lock
                            logger.warning(f"Stale GPU lease detected (PID {pid} is dead). Removing...")
                            self.lock_file.unlink(missing_ok=True)
                            continue
                except Exception as e:
                    logger.debug(f"Error checking lock owner: {e}")
                
                if time.time() - start_time > self.max_wait_timeout:
                    raise TimeoutError(f"Failed to acquire GPU lease within {self.max_wait_timeout} seconds.")
                
                logger.info("Waiting for GPU lease...")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Error acquiring GPU lease: {e}")
                raise

    def release(self) -> None:
        """
        GPUリースを解放する。自身が所有者の場合のみファイルを削除する。
        """
        try:
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()
            
            expected_content = f"{os.getpid()}:{self.owner_token}"
            if content == expected_content:
                self.lock_file.unlink()
                logger.info("GPU lease released.")
            else:
                logger.debug("GPU lease is owned by another process or token mismatch. Skipping release.")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Error releasing GPU lease: {e}")


def unload_ollama_models() -> None:
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
            
            # Verify unloading
            start_time = time.time()
            while time.time() - start_time < 10:
                req = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=2)
                if req.getcode() == 200:
                    data = json.loads(req.read().decode('utf-8'))
                    if not data.get("models"):
                        return
                time.sleep(1)
            raise RuntimeError("Failed to unload Ollama models within timeout. VRAM might not be freed.")
            
    except Exception as e:
        logger.error(f"Failed to verify/unload Ollama models (Ollama might not be running or failed to clear): {e}")
        raise RuntimeError(f"Ollama unload failed: {e}")


class OllamaBackendAdapter:
    """
    Ollama バックエンドのタスク実行アダプタ。
    
    実行時に OLLAMA_API_BASE を一時的に環境変数としてパッチし、
    タスク終了後に元に戻す（副作用をブロック内に閉じ込める）。
    """
    def __init__(self, profile: Dict[str, Any]) -> None:
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Optional[Callable[..., Any]] = request.get("action")
        if action is None:
            raise ValueError("OllamaBackendAdapter requires an 'action' callable in request")
        
        logger.info(f"Executing workload on Ollama backend with profile: {self.profile}")
        
        # Profile から endpoint を取得（未設定時は localhost:11434）
        api_base = self.profile.get("endpoint", "http://localhost:11434")
        
        with patch_env(OLLAMA_API_BASE=api_base, OPENAI_API_BASE=api_base):
            return action()


class LlamaServerBackendAdapter:
    """
    llama-server バックエンドのタスク実行アダプタ。
    
    実行前に Ollama の VRAM を解放し、llama-server プロセスを起動する。
    実行中は APIエンドポイントを :8080/v1 に一時パッチし、
    タスク終了時には必ずプロセスを終了（VRAM解放）させ、環境変数を復元する。
    """
    def __init__(self, profile: Dict[str, Any]) -> None:
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Optional[Callable[..., Any]] = request.get("action")
        if action is None:
            raise ValueError("LlamaServerBackendAdapter requires an 'action' callable in request")
        
        model_name = self.profile.get("model")
        if not model_name:
            raise ValueError("LlamaServer profile must specify a 'model'")
            
        model_path = f"./models/{model_name}.gguf"
        
        logger.info(f"Executing workload on llama-server backend with profile: {self.profile}")
        
        unload_ollama_models()
        
        api_base = self.profile.get("endpoint", "http://localhost:8080/v1")
        
        with patch_env(OPENAI_API_BASE=api_base, OLLAMA_API_BASE=api_base):
            with managed_llama_server(model_path=model_path, port=8080):
                return action()


class BackendExecutionCoordinator:
    def __init__(self) -> None:
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
            raise ValueError(f"No route mapped for intent '{intent}'. Explicit routing is required.")
            
        profile = profiles.get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' is not defined in backend profiles.")
        backend_type = profile.get("backend", "ollama")
        
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

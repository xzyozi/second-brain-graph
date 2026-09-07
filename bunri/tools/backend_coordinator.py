"""LLMバックエンドの排他実行と実行先解決を担う Module。"""

import contextlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Optional

from tools.config_loader import ProfileConfig, get_backend_execution_config
from tools.llama_backend import managed_llama_server

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def patch_env(**env_vars: str) -> Iterator[None]:
    """ブロック中だけ環境変数を設定し、終了時に必ず元へ戻す。"""
    original = {key: os.environ.get(key) for key in env_vars}
    os.environ.update(env_vars)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class GpuLeaseAdapter:
    """bunri単位のローカルGPU排他リース Adapter。"""

    def __init__(self, timeout: int = 60) -> None:
        runtime_dir = Path(__file__).resolve().parent.parent / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path = runtime_dir / ".gpu_lease.lock"
        self._timeout = timeout
        self._handle: Optional[BinaryIO] = None

    def __enter__(self) -> "GpuLeaseAdapter":
        self._handle = self._lock_path.open("a+b")
        if self._lock_path.stat().st_size == 0:
            self._handle.write(b"\\0")
            self._handle.flush()
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                self._lock()
                return self
            except OSError as error:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise TimeoutError(
                        f"Failed to acquire GPU lease within {self._timeout} seconds."
                    ) from error
                time.sleep(0.1)

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._handle is None:
            return
        self._unlock()
        self._handle.close()
        self._handle = None

    def _lock(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)


def _normalise_management_url(endpoint: str) -> str:
    """Ollama管理エンドポイントからOpenAI互換の /v1 接尾辞を除く。"""
    return endpoint.removesuffix("/v1/").removesuffix("/v1").rstrip("/")


def unload_ollama_models(management_endpoint: str) -> None:
    """Ollamaのロード済みモデルを解放する。未起動時は処理を継続する。"""
    base_url = _normalise_management_url(management_endpoint)
    try:
        with urllib.request.urlopen(f"{base_url}/api/ps", timeout=2) as response:
            if response.getcode() != 200:
                return
            payload = json.loads(response.read().decode("utf-8"))
        for model in payload.get("models", []):
            model_name = model.get("name")
            if not model_name:
                continue
            request = urllib.request.Request(
                f"{base_url}/api/generate",
                data=json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(request, timeout=5)
    except urllib.error.URLError:
        logger.info("Ollama management API is unavailable; continuing with GPU handoff.")


class OllamaBackendAdapter:
    """Ollamaプロファイルで呼び出しを実行する Adapter。"""

    def __init__(self, profile: ProfileConfig) -> None:
        self._profile = profile

    def execute(self, request: dict[str, Any]) -> Any:
        action: Optional[Callable[[ProfileConfig], Any]] = request.get("action")
        if action is None:
            raise ValueError("OllamaBackendAdapter requires an 'action' callable.")
        management_endpoint = self._profile.ollama_management_endpoint or self._profile.openai_endpoint
        with patch_env(
            OLLAMA_API_BASE=_normalise_management_url(management_endpoint),
            OPENAI_API_BASE=self._profile.openai_endpoint,
        ):
            return action(self._profile)


class LlamaServerBackendAdapter:
    """llama-serverプロファイルで呼び出しを実行する Adapter。"""

    def __init__(self, profile: ProfileConfig, config: Any) -> None:
        self._profile = profile
        self._config = config

    def execute(self, request: dict[str, Any]) -> Any:
        action: Optional[Callable[[ProfileConfig], Any]] = request.get("action")
        if action is None:
            raise ValueError("LlamaServerBackendAdapter requires an 'action' callable.")
        assert self._profile.model_path is not None
        assert self._profile.port is not None
        management_endpoint = next(
            (
                item.ollama_management_endpoint
                for item in self._config.profiles.values()
                if item.backend == "ollama" and item.ollama_management_endpoint
            ),
            None,
        )
        if management_endpoint:
            unload_ollama_models(management_endpoint)
        with patch_env(
            OPENAI_API_BASE=self._profile.openai_endpoint,
            OLLAMA_API_BASE=self._profile.openai_endpoint,
        ):
            with managed_llama_server(self._profile.model_path, self._profile.port):
                return action(self._profile)


class BackendExecutionCoordinator:
    """intentを設定済みプロファイルへ解決し、GPU排他下で実行する Module。"""

    def __init__(self) -> None:
        self._config = get_backend_execution_config()
        self._gpu_lease = GpuLeaseAdapter(timeout=self._config.gpu_lease_timeout)

    def execute(self, intent: str, request: dict[str, Any]) -> Any:
        profile_name = self._config.routes.get(intent)
        if not profile_name:
            raise ValueError(f"No route mapped for intent '{intent}'. Explicit routing is required.")
        profile = self._config.profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"Profile '{profile_name}' is not defined in backend profiles.")
        if profile.backend == "ollama":
            adapter: Any = OllamaBackendAdapter(profile)
        elif profile.backend == "llama_server":
            adapter = LlamaServerBackendAdapter(profile, self._config)
        else:
            raise ValueError(f"Unknown backend type: {profile.backend}")
        with self._gpu_lease:
            return adapter.execute(request)


@lru_cache(maxsize=1)
def get_coordinator() -> BackendExecutionCoordinator:
    """共有Coordinatorを返す。"""
    return BackendExecutionCoordinator()

#!/usr/bin/env python3
"""tools/backend_coordinator.py - LLMバックエンドのルーティングおよび実行を管理するCoordinator."""

from __future__ import annotations

import contextlib
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from filelock import FileLock, Timeout

from tools.config_loader import ProfileConfig, get_backend_execution_config

logger = logging.getLogger("backend_coordinator")


@contextlib.contextmanager
def patch_env(**env_vars: str) -> Iterator[None]:
    """一時的に環境変数を設定し、ブロック終了後に元の状態へ復元するコンテキストマネージャ."""
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
    """GPUリースの排他制御を管理するアダプタ.

    ローカル GPU 利用時の排他制御用（agy 経路では使用しない）。
    """

    def __init__(self, lock_file: str = ".gpu_lease.lock", timeout: int = 60) -> None:
        lock_path = Path(__file__).resolve().parent.parent / "metadata" / lock_file
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.lock = FileLock(str(lock_path), timeout=timeout)

    def __enter__(self) -> GpuLeaseAdapter:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    def acquire(self) -> None:
        """GPUリースを取得する。取得できない場合はTimeoutErrorを送出する."""
        try:
            logger.info("Waiting for GPU lease...")
            self.lock.acquire()
            logger.info("GPU lease acquired.")
        except Timeout as e:
            logger.error("Failed to acquire GPU lease within timeout.")
            raise TimeoutError(f"Failed to acquire GPU lease within {self.timeout} seconds.") from e

    def release(self) -> None:
        """GPUリースを解放する."""
        try:
            self.lock.release()
            logger.info("GPU lease released.")
        except Exception as e:
            logger.error(f"Error releasing GPU lease: {e}")


class AgyBackendAdapter:
    """agy バックエンドのタスク実行アダプタ.

    GPU リースは取得せず、環境変数のパッチも行わない。
    agy の起動処理は後続の agy_client の責務であり、ここでは action を呼ぶ。
    """

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    def execute(self, request: Dict[str, Any]) -> Any:
        action: Optional[Callable[..., Any]] = request.get("action")
        if action is None:
            raise ValueError("AgyBackendAdapter requires an 'action' callable in request")

        logger.info(f"Executing workload on agy backend with profile: {self.profile}")
        return action(self.profile)


class BackendExecutionCoordinator:
    """intent (e.g. 'spec_draft', 'code_edit') に基づいてバックエンドプロファイルを解決し実行する Coordinator."""

    def __init__(self) -> None:
        self.config = get_backend_execution_config()
        self.gpu_lease = GpuLeaseAdapter(timeout=self.config.gpu_lease_timeout)

    def execute(self, intent: str, request: Dict[str, Any]) -> Any:
        """intent に基づいてプロファイルを選択し、アダプタを介してリクエストを実行する."""
        routes = self.config.routes
        profiles = self.config.profiles

        profile_name = routes.get(intent)
        if not profile_name:
            raise ValueError(
                f"No route mapped for intent '{intent}'. Explicit routing is required."
            )

        profile = profiles.get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' is not defined in backend profiles.")

        backend_type = profile.backend

        logger.info(
            f"Resolved intent '{intent}' to profile '{profile_name}' (backend: {backend_type})"
        )

        if backend_type == "agy":
            adapter = AgyBackendAdapter(profile)
            return adapter.execute(request)

        raise ValueError(
            f"Backend '{backend_type}' is retired/unsupported. Only 'agy' is supported (Issue #128)."
        )


@lru_cache(maxsize=1)
def get_coordinator() -> BackendExecutionCoordinator:
    """Get singleton instance of BackendExecutionCoordinator."""
    return BackendExecutionCoordinator()

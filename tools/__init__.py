"""Tools package initialization and backwards-compatibility facade.

tools/ 配下のモジュールが 5 つのサブパッケージ（core, backends, lifecycle, workspace, models）
へ再配置された後も、既存の `from tools.xxx import ...` や `import tools.xxx` が
100% 動作し続けるよう、後方互換リダイレクト機能を提供します。
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

# 旧モジュール名から新サブパッケージへのマッピング定義
_LEGACY_MODULE_MAP: dict[str, str] = {
    # core
    "orchestrator_graph": "tools.core.orchestrator_graph",
    "edit_guard": "tools.core.edit_guard",
    "prompt_harness": "tools.core.prompt_harness",
    "sanitizer": "tools.core.sanitizer",
    # backends
    "agy_client": "tools.backends.agy_client",
    "agy_runner": "tools.backends.agy_runner",
    "agy_policy": "tools.backends.agy_policy",
    "backend_coordinator": "tools.backends.backend_coordinator",
    "llm_client": "tools.backends.llm_client",
    "jev_adapter": "tools.backends.jev_adapter",
    # lifecycle
    "issue_spec_manager": "tools.lifecycle.issue_spec_manager",
    "periodic_review_runner": "tools.lifecycle.periodic_review_runner",
    "close_stale_issues": "tools.lifecycle.close_stale_issues",
    # workspace
    "metadata_store": "tools.workspace.metadata_store",
    "config_loader": "tools.workspace.config_loader",
    "git_utils": "tools.workspace.git_utils",
    # models
    "gguf_manager": "tools.models.gguf_manager",
    "register_ollama_model": "tools.models.register_ollama_model",
    "build_modelfile": "tools.models.build_modelfile",
}

# sys.modules へエイリアスを事前登録し、`import tools.xxx` を完全互換化
for _legacy_name, _target_pkg in _LEGACY_MODULE_MAP.items():
    _full_legacy = f"tools.{_legacy_name}"
    if _full_legacy not in sys.modules:
        try:
            _mod = importlib.import_module(_target_pkg)
            sys.modules[_full_legacy] = _mod
        except Exception:
            pass


def __getattr__(name: str) -> Any:
    """PEP 562: 未インポートの旧モジュール名を動的に新サブパッケージから解決する."""
    if name in _LEGACY_MODULE_MAP:
        target = _LEGACY_MODULE_MAP[name]
        mod = importlib.import_module(target)
        sys.modules[f"tools.{name}"] = mod
        return mod
    raise AttributeError(f"module 'tools' has no attribute '{name}'")

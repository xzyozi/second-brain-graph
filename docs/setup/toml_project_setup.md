# pyproject.toml / Ruff / Mypy / Pytest 設定ガイド

本プロジェクトでは `pyproject.toml` にて、`setuptools` ビルド構成、`Ruff` (Linter/Formatter)、`Mypy` (Type Checker)、`Pytest` (Testing) の全設定を規定しています。

---

## 1. `pyproject.toml` の構成

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "second-brain-graph"
version = "0.1.0"
description = "LLMマルチエージェント × ナレッジグラフ統括・自律タスク実行基盤"
requires-python = ">=3.10, <3.14"

dependencies = [
    "langgraph>=0.1.0",
    "litellm>=1.30.0",
    "aider-chat>=0.30.0",
    "pydantic>=2.0.0",
    "pytest-json-report>=1.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
    "mypy>=1.0.0",
    "pip-licenses>=4.0.0",
]
```

---

## 2. ツール別設定詳細

### ① Ruff (Linter & Formatter)
- `line-length = 100`
- `select = ["E", "F", "W", "I", "N", "B"]` (Error, Pyflakes, Warning, Isort, Naming, Bugbear)
- コマンド: `uv run ruff check .` / `uv run ruff format .`

### ② Mypy (型チェック)
- `python_version = "3.10"`
- コマンド: `uv run mypy .`

### ③ Pytest (単体テスト)
- `testpaths = ["tests"]`
- コマンド: `uv run pytest`

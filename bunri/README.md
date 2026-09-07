# bunri modules

`bunri` は、LLM 呼び出し、ローカルバックエンド実行、Aider 実行を提供する自己完結した Module 群です。親リポジトリの `metadata/`、中央台帳、またはネストした Git リポジトリは必要としません。

## 構成

- `tools/config_loader.py`: `config/models.json` を Pydantic で検証して提供する Module
- `tools/backend_coordinator.py`: intent をバックエンドへ解決し、ローカル GPU リースを管理する Module
- `tools/llm_client.py`: OpenAI 互換 API 呼び出しを構成する Module
- `tools/aider_runner.py`: Aider CLI と Git 差分取得を行う Module

実行時に生成される GPU ロックは `runtime/` 配下に限定され、Git 管理の対象外です。モデル設定はこのディレクトリ内の `config/models.json` が正本です。

## 検証

`bunri/` をカレントディレクトリとして、次を実行します。

```powershell
uv run --no-sync pytest
uv run --no-sync ruff check tools tests
```

テストでは外部の LLM、Ollama、Aider、llama-server を起動しません。各外部依存は Module の seam でモック化します。

# GGUFをOllamaモデルとして登録する

## 目的

`tools/register_ollama_model.py` は、独立したGGUFファイルをOllamaのローカルモデルタグとして登録するツールです。`tools/` は本リポジトリの実装層でもあるため、CLIの処理は再利用可能な `register_gguf_model()` に集約しています。

登録操作と実行設定は分離します。このツールは `config/models.json` を変更しません。登録済みモデルをオーケストレータで使う場合だけ、利用者がOllama profileとrouteを設定してください。

## 前提条件

- Ollamaがインストール済みで、`ollama` コマンドを実行できること
- 登録するファイルが存在し、拡張子が `.gguf` であること
- 対象ファイルを読み取れること

## 実行手順

最初に副作用なしで入力を確認します。

```powershell
uv run python tools/register_ollama_model.py .\models\example.gguf local-example:latest --dry-run
```

問題がなければ登録します。

```powershell
uv run python tools/register_ollama_model.py .\models\example.gguf local-example:latest
```

同名タグが登録済みの場合、意図しない置換を防ぐため処理は失敗します。置換する場合だけ `--force` を指定します。

```powershell
uv run python tools/register_ollama_model.py .\models\example.gguf local-example:latest --force
```

Ollamaの実行ファイルがPATHにない場合は、`--ollama-command` で明示できます。

```powershell
uv run python tools/register_ollama_model.py .\models\example.gguf local-example:latest --ollama-command C:\tools\ollama.exe
```

## 処理内容

1. プロジェクトルートを基準にGGUFパスを解決し、ファイルの存在と拡張子を検証します。
2. `ollama list` で同名タグを確認します。
3. GGUFと同じディレクトリに一時Modelfileを作成し、相対 `FROM` パスでGGUFを指定します。
4. `ollama create <tag> -f <Modelfile>` を実行します。
5. 成否にかかわらず一時Modelfileを削除します。

Ollamaへの登録は、モデルを常にVRAMへ常駐させることを保証しません。ただし、リクエストごとに `llama-server.exe` を生成・終了する方式とは異なり、Ollamaが管理する常駐プロセスで利用できます。

## 参考

OllamaのGGUFインポートとModelfileの仕様は、公式ドキュメントを参照してください: [Importing a Model](https://docs.ollama.com/import)。内容はライセンス制約に配慮して要約・再構成しています。

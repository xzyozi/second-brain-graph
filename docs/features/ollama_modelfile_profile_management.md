# Ollama Modelfileプロファイル管理

## 目的

`tools/build_modelfile.py` は、独立したGGUFファイルを参照するQwen用Ollama Modelfileを生成する。Ollama登録、`config/models.json` のprofile追加、intent route変更は実行しない。

`tools/register_ollama_model.py` は最小構成の一時ModelfileでGGUFを登録するツールである。一方、本ツールはハードウェア資源、推論パラメータ、Qwenテンプレート、SYSTEMプロンプトを含む永続Modelfileを生成する。

## 論理名と生成ファイル名

Ollamaへの登録名は次の形式とする。

```text
<model-name>:<role>
```

Windowsでは `:` と `/` をファイル名に使えないため、生成ファイル名は登録名を可逆なパーセント表現へ変換する。

| Ollama登録名           | 生成ファイル名                       |
| ---------------------- | ------------------------------------ |
| `qwen3.6-35b:coder`    | `Modelfile_qwen3.6-35b%3Acoder`      |
| `local/qwen3:reviewer` | `Modelfile_local%2Fqwen3%3Areviewer` |

これにより、登録名とModelfileは一対一に対応し、Windowsでも安全に保存できる。

## 入力契約

| 入力                   | 契約                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------- |
| `--gguf-path`          | 相対パスはプロジェクトルート基準で解決する。通常は存在する通常ファイルかつ `.gguf` 拡張子を必須とする。 |
| `--allow-missing-gguf` | GGUF配置前のModelfile設計時だけ、存在確認を明示的に省略する。拡張子・パス検証は省略しない。             |
| `--model-name`         | Ollamaタグ本体。英数字、`.`, `_`, `-`, `/` のみを許可し、空・`.`・`..` のパスセグメントを拒否する。     |
| `--role`               | Ollamaタグ末尾。英数字、`.`, `_`, `-` のみを許可する。                                                  |
| `--template`           | 必須。現時点では `qwen` のみを許可する。                                                                |
| `--system-prompt-file` | 任意のUTF-8テキストファイル。空、NUL、Modelfile区切りの三重引用符を含む値は拒否する。                   |
| `--force`              | 同じ論理名の既存Modelfileを明示的に置換する。既定では上書きを拒否する。                                 |

## パラメータ契約

| 入力               | 許可値                                              | 既定値 |
| ------------------ | --------------------------------------------------- | ------ |
| `--num-ctx`        | 1以上の整数                                         | 8192   |
| `--num-thread`     | 1以上の整数                                         | 8      |
| `--num-gpu`        | `auto` または0以上の整数。`auto` は行を出力しない。 | 32     |
| `--temperature`    | 0.0以上2.0以下                                      | 0.2    |
| `--top-p`          | 0.0超1.0以下                                        | 0.9    |
| `--top-k`          | 1以上の整数                                         | 20     |
| `--repeat-penalty` | 0.0超                                               | 1.05   |


## 実行手順

GGUFが未配置のため、Modelfileだけを準備する場合:

```powershell
uv run python tools/build_modelfile.py `
  --gguf-path .\models\qwen3.gguf `
  --model-name qwen3 `
  --role coder `
  --template qwen `
  --allow-missing-gguf
```

GGUFを配置済みの場合:

```powershell
uv run python tools/build_modelfile.py `
  --gguf-path .\models\qwen3.gguf `
  --model-name qwen3 `
  --role coder `
  --template qwen `
  --num-gpu auto `
  --top-p 0.9 `
  --top-k 20
```

生成後、内容を確認した上で、表示された `ollama create <登録名> -f <Modelfile>` を利用者が手動実行する。Ollama登録はこのツールの責務ではない。

## 責務分離

| モジュール                       | 責務                                                              |
| -------------------------------- | ----------------------------------------------------------------- |
| `tools/build_modelfile.py`       | 検証済みの永続Modelfileを生成し、手動登録コマンドを表示する。     |
| `tools/register_ollama_model.py` | 独立GGUFを最小ModelfileでOllamaへ安全に登録する。                 |
| `config/models.json`             | 登録済みOllamaモデルをアプリのprofile・intent routeへ割り当てる。 |

## 注意事項

- `num_thread` と `num_gpu` は実行マシンのCPU・GPU・VRAMに依存する。既定値はQwenコーディング用途の例であり、環境ごとに調整する。
- Qwen以外のモデルには、対応するテンプレートを追加するまで `--template qwen` を使用しない。
- GGUFの登録はVRAM常駐を保証しない。常駐・退避はOllamaの実行時管理の対象である。
- SYSTEMプロンプトはモデルの利用目的に応じて版管理する。

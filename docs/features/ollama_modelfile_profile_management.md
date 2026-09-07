# Ollama Modelfileプロファイル管理

## 目的

GGUFをOllamaへ登録する際、単なるモデル取り込みではなく、ハードウェア資源・推論挙動・チャットテンプレート・システムプロンプトを含むモデル固有のModelfileプロファイルを管理する。

本メモは、将来作成するModelfile生成・登録ツールの入力要件とする。既存の `tools/register_ollama_model.py` はGGUFを最小構成で登録するツールであり、本メモのパラメータは扱わない。

## 参照プロファイル

対象例は `Qwen3.6-35B-A3B-UD-IQ4_XS.gguf` を `qwen3.6-35B-A3B-UD-IQ4_XS` として登録するケースである。

```text
ollama create qwen3.6-35B-A3B-UD-IQ4_XS -f ./Modelfile_Modelfile_qwen3_6_35b-a3b
```

| 分類         | Modelfile設定                                            | 意図                                                                |
| ------------ | -------------------------------------------------------- | ------------------------------------------------------------------- |
| ベースモデル | `FROM ./Qwen3.6-35B-A3B-UD-IQ4_XS.gguf`                  | 登録する独立GGUFを指定する。                                        |
| コンテキスト | `PARAMETER num_ctx 8192`                                 | コード・文脈を扱うための8Kコンテキスト。                            |
| CPU資源      | `PARAMETER num_thread 8`                                 | 実行環境の物理コア数に合わせて調整する。                            |
| GPU資源      | `PARAMETER num_gpu 32`                                   | 12GB VRAM環境を想定したレイヤー割当の例。環境依存で調整・省略する。 |
| 生成の安定性 | `temperature 0.2`、`top_p 0.9`、`top_k 20`               | コーディングと構造化出力の安定性を重視する。                        |
| 繰返し制御   | `repeat_penalty 1.05`                                    | 冗長・反復出力を抑制する。                                          |
| チャット形式 | Qwenの `<                                                | im_start                                                            | >` / `< | im_end | >` テンプレート | system、user、assistantのメッセージ形式をモデル仕様へ合わせる。 |
| システム指示 | ソフトウェアエンジニア／アーキテクト向けSYSTEMプロンプト | 精確なコード生成、構造化出力、不要な会話文抑制を指示する。          |

## 将来ツールの責務

将来の専用ツールは、以下を明示的な入力として永続Modelfileを生成・更新し、必要時にOllamaへ登録する。

1. GGUFパスとOllamaモデルタグ
2. コンテキスト長、CPUスレッド数、GPUレイヤー数
3. 生成パラメータ（temperature、top-p、top-k、repeat penalty）
4. モデルファミリーに対応したチャットテンプレート
5. SYSTEMプロンプト

生成前に、GGUFの存在、モデルタグ、パラメータ範囲、テンプレート形式を検証する。既存タグの置換と `config/models.json` のルーティング変更は、利用者の明示操作を必須とする。

## 責務分離

| モジュール                       | 責務                                                              |
| -------------------------------- | ----------------------------------------------------------------- |
| `tools/register_ollama_model.py` | 独立GGUFを最小ModelfileでOllamaへ安全に登録する。                 |
| 将来のModelfile管理ツール        | モデル固有の永続Modelfileを生成・検証・更新する。                 |
| `config/models.json`             | 登録済みOllamaモデルをアプリのprofile・intent routeへ割り当てる。 |

## 注意事項

- `num_thread` と `num_gpu` は実行マシンのCPU・GPU・VRAMに依存するため、モデル固有の固定値として扱わない。
- チャットテンプレートとSYSTEMプロンプトは、モデルの学習形式・利用目的に応じて版管理する。
- GGUFの登録はVRAM常駐を保証しない。常駐・退避はOllamaの実行時管理の対象である。

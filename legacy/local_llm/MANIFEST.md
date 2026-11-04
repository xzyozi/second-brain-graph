# ローカルLLM（Aider + Ollama / llama-server）資産 MANIFEST

| 項目           | 内容                                                                                                                                          |
| :------------- | :-------------------------------------------------------------------------------------------------------------------------------------------- |
| 目的           | JEV を除くローカルLLM使用箇所を agy へ置き換える（Epic #116）に先立ち、coder 専用およびローカル推論基盤の資産を、参照・復元できる形で保存する |
| 作成日         | 2026年11月4日                                                                                                                                 |
| 取得元         | `develop`（コミット `2eef4c2`、PR #130 のマージ時点）。コード・設定の内容は `4e44375` 以降変わっていない                                      |
| 復元点（タグ） | `archive/local-llm-20261104`（取得元コミットに作成）                                                                                          |
| 参照Issue      | #118（本資産の退避）、#116（Epic）、#128（退役。本資産の退避が完了していることが着手条件）                                                    |

## 1. 重要な前提

- **本ディレクトリは参照専用である。** 現役のコードは `tools/` と `config/` にあり、ここのファイルは編集しない。
- **退避したコードは単体では動かない。** `tools` パッケージを import するため、復元は§5の手順で本体へ戻して行う。
- **JEV は退避対象外であり、現役のまま残る。** JEV（`tools/jev_adapter.py`、`submodules/jev-localsystem`、`tools/screen_issues.py`）は Ollama（既定 `qwen2.5:0.5b`）へ直接接続するため、**Ollama の実行環境は agy 移行後も必要**である。
- `legacy/` は ruff と mypy の対象外にしている（`pyproject.toml` の `exclude`）。pytest は `tests/` のみを収集するため、`legacy/` は実行されない。

## 2. 退避した内容と元の場所

| 退避先（`legacy/local_llm/` 以下）     | 元の場所                                    | 区分             | 備考                                                                                                  |
| :------------------------------------- | :------------------------------------------ | :--------------- | :---------------------------------------------------------------------------------------------------- |
| `tools/aider_runner.py`                | `tools/aider_runner.py`                     | coder 実行コード | Aider CLI の起動、`get_git_diff`、`target_files` 外の後始末（`cleanup_unauthorized_aider_artifacts`） |
| `tools/benchmark_aider_formats.py`     | `tools/benchmark_aider_formats.py`          | 計測ツール       | Aider の `edit_format` 比較。オーケストレーターの実行経路には含まれない                               |
| `tools/backend_coordinator.py`         | `tools/backend_coordinator.py`              | 推論基盤         | GPU リース、Ollama / llama-server Adapter。**原本は現役**（planner / reviewer が使用）                |
| `tools/llama_backend.py`               | `tools/llama_backend.py`                    | 推論基盤         | llama-server の起動・終了。**原本は現役**                                                             |
| `config/models.yaml.example`           | `config/models.yaml`                        | 設定             | `aider:`、3つの profile、`routes` 8件を含む移行前の全体                                               |
| `config/prompt.yaml.example`           | `config/prompt.yaml`                        | 設定             | `coder:` の Aider 専用ルールを含む                                                                    |
| `modelfiles/Modelfile_qwen3.6.example` | `tools/templates/Modelfile_qwen3.6.example` | Modelfile 例     | Qwen 系 35B MoE 向けの例                                                                              |
| `docs/design/*`                        | `docs/design/SBOS-*.md`                     | 設計書           | 改訂前の設計書。取得元は `4e44375`。詳細は `docs/design/BACKUP_NOTE.md`                               |

- **設定ファイルを `*.yaml.example` にしている理由**: `tools/config_loader.py` は `config/models.yaml` のみを読む。生きた設定として誤って読まれないようにするためである。
- 取得時に改行のみ LF へ正規化している。内容は変えていない。
- **退避していないもの（理由つき）**: `tools/gguf_manager.py`、`tools/register_ollama_model.py`、`tools/build_modelfile.py` は、Ollama / GGUF の運用ツールで、JEV 用の Ollama 運用でも使い得るため、現役のまま残している。退役の要否は #128 で判断する。

## 3. モデル重み

**重みは複製しない。** `models/*` は `.gitignore` により git 管理対象外である。

| モデル                         | ファイル / タグ                                                                        | 用途                                                     | 記録されている情報                       |
| :----------------------------- | :------------------------------------------------------------------------------------- | :------------------------------------------------------- | :--------------------------------------- |
| Ornith 1.5 9B                  | `models/Ornith-1.5-9B-Q5_K_M.gguf`（約 6.64 GB）→ Ollama タグ `ornith-1.5-9b:latest`   | coder（`coding_ollama`）                                 | ファイル名とサイズ、登録コマンド（下記） |
| Gemma 4 12B                    | Ollama タグ `gemma4-12b-it-Q4_K_M:latest`                                              | planner / reviewer（`reasoning_ollama`）                 | タグ名のみ                               |
| Gemma 4 12B（llama-server 用） | `models/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf`、draft は `models/mtp-gemma-4-12B-it.gguf` | `reasoning_economy`（現在どの route からも参照されない） | ファイル名のみ                           |

- **取得元（配布元 URL）と SHA256 は、リポジトリ内に記録が無い。** 本退避を実施した環境では `models/` が空で、重みが存在しないため、確認できなかった。**推測では記載しない。** 重みのある環境で、次の手順により追記すること。
  1. `Get-FileHash -Algorithm SHA256 models\<ファイル名>` で SHA256 を取得する。
  2. 配布元（モデルカードの URL）を、取得時の記録（ブラウザ履歴、ダウンロード記録）から確認する。
  3. 上表の「記録されている情報」へ追記する。
- Ollama への登録手順（Ornith）: `python tools/register_ollama_model.py models/Ornith-1.5-9B-Q5_K_M.gguf ornith-1.5-9b:latest`（`docs/features/coder_test_and_github_ci_pr_fixer.md` §2.1）。汎用手順は `docs/how-to/ollama_gguf_registration.md`。

## 4. 設計判断の履歴

`tools/aider_runner.py`、`tools/backend_coordinator.py`、`config/models.yaml` に関わるコミットから、判断の経緯を時系列で整理した。詳細は各コミットを参照。

| 時期       | コミット               | 判断                                                                                                                                |
| :--------- | :--------------------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| 2026-07-29 | `8d43253`              | モデル設定ローダーと Aider 実行エンジンを実装。自前 AST マージと自前 Coder Agent を Aider に置き換え                                |
| 2026-07-29 | `b0c838c`              | Aider を完全自動・非対話で実行するため `--yes-always` を追加                                                                        |
| 2026-07-30 | `168363a`              | Ollama から llama-server への移行と、VRAM を動的に確保するバックエンドを実装                                                        |
| 2026-07-30 | `9c2c618` 〜 `d656fe8` | 全 LLM 呼び出しを `BackendExecutionCoordinator` 経由に統一。GPU リースを堅牢化（UUID 所有者トークン、絶対パス、環境変数の漏れ防止） |
| 2026-07-30 | `7ea4190`              | GPU リースのタイムアウト連動、Ollama 未起動時の耐性を修正（PM-050）                                                                 |
| 2026-07-30 | `0b57659`              | Ollama エンドポイントの `/v1` 除去、モデル名の `ollama/` プレフィックス自動補正                                                     |
| 2026-08-02 | `530185c`              | Aider の指示を `--message-file` で渡すよう変更し、Windows のコマンドライン長制限（WinError 206）を回避                              |
| 2026-08-03 | `06f5f42`              | Aider のタイムアウトを 20 分（1200 秒）に拡張。この時点の設定ファイルは `config/models.json`（のちに `models.yaml` へ移行）         |
| 2026-09-06 | `ddcafb7`              | GGUF モデル管理（`gguf_manager.py`）を新設し、llama-server と統合                                                                   |
| 2026-09-16 | `88e6d7c`              | Aider が GPU リースを迂回していた不備を修正し、Coordinator 経由に統一（#25）                                                        |
| 2026-09-17 | `3622153`              | Aider が作る不正ファイルの自動排除（フェイルセーフ）                                                                                |
| 2026-09-19 | `beb5a65`              | 行数に応じた hybrid 編集モードと、`diff` 失敗時の `whole` 自動フォールバックを実装（#32）                                           |
| 2026-10-08 | `0353a2a`              | **`diff` モード優先**、コンテキストの軽量化、空テストファイルの除外ガードを追加                                                     |

## 5. 知見

### 5.1 `edit_format` は `diff` に固定した（`whole` を避けた理由）

`config/models.yaml` の現行設定とそのコメントに基づく。**根拠は設定ファイルのコメントのみで、計測データはリポジトリに残っていない。**

- `edit_format: "diff"`: コメントによれば、`whole` は CoT（思考の連鎖）が膨らみ、18 分を超えるタイムアウトを起こしたため。
- `hybrid_line_threshold: 0`: 常に `diff` を優先して、巨大なトークン生成を防ぐ。
- `fallback_to_whole: false`: ローカルLLMでは `whole` が CoT の爆発とパース不能のリスクを持つため、原則として無効にした。
- `timeout: 1200`: 複数ファイルの推論・編集のため 20 分を確保。

### 5.2 記録の矛盾（要注意）

**`docs/features/coder_test_and_github_ci_pr_fixer.md` §2.3-3 は逆の内容を推奨している。** 「100〜200 行を超える大容量ファイルでは `diff` のハルシネーションが起きやすいため、`edit_format: "whole"` を推奨する」と記載されている。この記述（2026-09-15 作成）は、`diff` 優先に切り替えたコミット `0353a2a`（2026-10-08）より前のものであり、**現行の設定は `diff` 固定**である。復元・再検討の際は、モデルとファイル規模の組み合わせで再計測すること（`tools/benchmark_aider_formats.py`、`docs/features/aider_format_benchmark.md`）。ベンチマークの**結果自体は、リポジトリ内に記録が無い**（スクリプトと仕様書のみ）。

### 5.3 Aider 運用の落とし穴

- `target_files` は、CWD からの相対パスではなく、**Git リポジトリルートからの相対パス**で渡す（Aider は `.git` のあるルートを自動判定する）。
- `OLLAMA_API_BASE` の `/v1` サフィックスは、Aider 側の接続エラーを避けるため除去する。
- 指示は UUID 付きの一時ファイル（`.aider.instruction_<uuid>.tmp`）で渡し、`finally` で必ず削除する。並列実行時の上書き競合と WinError 206 を避けるため。
- Windows では `git config --global core.autocrlf input` を設定する。CRLF / LF 混在で diff が爆発するため（PM-012）。
- `target_files` 外の変更は、実行後に `cleanup_unauthorized_aider_artifacts` で戻す（#101）。追跡済みファイルは削除せず `git restore` する。
- 1 回の推論・編集に約 30 秒〜1 分かかる。オーケストレーターのタイムアウトは 300〜1200 秒に保つ。

### 5.4 GPU リースと推論基盤

- 全 backend の実行は `with self.gpu_lease:` で包まれ、単一 GPU を排他利用する。
- llama-server の起動前に、Ollama のロード済みモデルを解放する。Ollama の管理 API に到達できない場合は、VRAM の状態が不明のため、`SBOS_ALLOW_LLAMA_ON_UNKNOWN_VRAM` が `1` / `true` / `yes` でない限り起動を拒否する（#25）。
- `reasoning_economy`（llama-server）は定義されているが、現在どの route からも参照されていない（`docs/analysis/flow-gguf-20260907.md`）。

## 6. 復元手順

### 6.1 設計書のみ復元する場合
`docs/design/BACKUP_NOTE.md` に従う。

### 6.2 コード・設定を復元する場合（`archive/local-llm-20261104` タグ）
1. 復元点のタグへ切り替える: `git switch --detach archive/local-llm-20261104`
2. 必要なファイルを現在のブランチへ取り出す: `git checkout archive/local-llm-20261104 -- tools/aider_runner.py config/models.yaml`（対象は用途に応じて選ぶ）
3. `config/models.yaml` の `routes` を旧 profile（`reasoning_ollama` / `coding_ollama`）へ戻す。**旧 profile が削除された後（#128 完了後）は、`*.yaml.example` から復元する。**
4. Ollama を起動し、モデルを登録する（§3）。`pyproject.toml` の依存に `aider-chat` が残っていることを確認する。
5. `uv sync` を実行し、新しい Python プロセスで再実行する（設定は `lru_cache` でキャッシュされる）。

### 6.3 `legacy/` からの手動復元
`*.yaml.example` は拡張子を外して `config/` へ置けば、そのまま読み込める。`tools/*.py` は `tools/` へ戻す。ただし、本体側が変更されている場合は差分を確認すること。

## 7. 関連資料（原本。#129 の改訂で更新される場合がある）

| 資料                                                   | 内容                                                                                 |
| :----------------------------------------------------- | :----------------------------------------------------------------------------------- |
| `docs/design/SBOS-DD-004_Aider統合仕様.md`             | Aider 統合と agy 編集の設計（現行は改訂後。改訂前は本ディレクトリの `docs/design/`） |
| `docs/design/SBOS-DD-005_Backend_GPUリース仕様.md`     | Backend LLM 制御と GPU リース                                                        |
| `docs/features/aider_format_benchmark.md`              | `edit_format` 比較ベンチマークの仕様                                                 |
| `docs/features/coder_test_and_github_ci_pr_fixer.md`   | Coder モデルの実稼働検証（§5.2 の矛盾を含む）                                        |
| `docs/how-to/ollama_gguf_registration.md`              | GGUF の Ollama 登録手順                                                              |
| `docs/features/ollama_modelfile_profile_management.md` | Modelfile の生成と管理                                                               |
| `docs/analysis/flow-gguf-20260907.md`                  | GGUF 運用と llama-server 起動のフロー解析                                            |

# Aider edit_format 多角的実証ベンチマーク仕様書 (`tools/benchmark_aider_formats.py`)

- **対象コンポーネント**: `tools/benchmark_aider_formats.py`, `tools/aider_runner.py`
- **関連文書**: [`SBOS-DD-004_Aider統合仕様`](../design/SBOS-DD-004_Aider統合仕様.md)、[`coder_test_and_github_ci_pr_fixer.md`](coder_test_and_github_ci_pr_fixer.md)

---

## 1. 目的

ローカル LLM（Ornith 1.5 9B、Gemma 4 12B、Qwen 2.5 Coder 14B 等）に対し、Aider の `edit_format`（`whole` / `diff` 等）が実機でどの程度安定して差分編集できるかを多角的に測定するための検証スクリプトです。

`config/models.yaml` の `edit_format` 設定や `tools/aider_runner.py` の hybrid 編集・フォールバック挙動の妥当性を、モデルとファイル規模の組み合わせで実証するために使用します。本ツールはオーケストレーターの実行経路には含まれず、独立した計測ツールとして手動で起動します。

---

## 2. 検証シナリオ

隔離された一時 Git リポジトリ上でモックファイルを生成し、以下のシナリオごとに編集を試行します。

| シナリオ | 内容 |
| :--- | :--- |
| `small` | 小規模ファイルの編集 |
| `medium` | 中規模ファイルの編集 |
| `large` | 600 行超の大規模ファイルの編集 |
| `japanese` | 日本語混在コードの編集 |
| `new_file` | 新規ファイルの生成 |
| `hybrid_e2e` | `tools/aider_runner.py` の `run_aider()` を直接呼ぶ hybrid / fallback 総合検証 |
| `multi_file` | 複数ファイルの同時編集 |

`--scenarios all` を指定すると上記全シナリオを実行します。

---

## 3. 測定項目

各実行について以下を測定し、サマリ表として標準出力へ出力します。

- `success`: 終了コード 0・差分あり・Python 構文妥当（AST パース成功）のすべてを満たすか
- `elapsed_sec`: 所要時間（秒）
- `diff_lines`: 生成された Git 差分の行数
- `syntax_valid`: 編集後の Python ファイルが構文的に妥当か
- `err_msg`: エラー要約（先頭 200 文字まで）

各実行後は `git reset --hard` と `git clean -fd` で一時リポジトリを初期状態へ戻し、シナリオ間の独立性を保ちます。

---

## 4. CLI 入力契約

```powershell
uv run python tools/benchmark_aider_formats.py `
  --models "ollama/ornith-1.5-9b:latest" `
  --scenarios "small,medium,large,japanese,new_file,hybrid_e2e,multi_file" `
  --formats "whole,diff" `
  --timeout 240
```

| 引数 | 既定値 | 説明 |
| :--- | :--- | :--- |
| `--models` | `ollama/ornith-1.5-9b:latest` | 対象モデル。カンマ区切りで複数指定可能 |
| `--scenarios` | 全シナリオ | 実行シナリオ。カンマ区切り、または `all` |
| `--formats` | `whole,diff` | 比較する `edit_format`。カンマ区切り |
| `--timeout` | `240` | 各実行のタイムアウト秒数 |

---

## 5. 前提条件

- Aider CLI（`uv run aider`）が利用可能であること
- 対象モデルが Ollama（既定エンドポイント `http://localhost:11434`）で参照可能であること
- Git が利用可能であること（一時リポジトリの初期化・差分検出・リセットに使用）

# 環境構築仕様書（システム前提要件・マルチモデル配置・セットアップガイド）
**ローカルLLM（現行）／agy（移行設計）× LangGraph × LiteLLM × Aider × Reviewdog フルスタック構築仕様**

| 項目     | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-ENV-001                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 版数     | Rev.4.8（Epic #116: agy 環境要件の追記。完全オフライン前提の訂正）                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 改訂日   | 2026年11月4日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 作成日   | 2026年7月27日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 対象読者 | インフラエンジニア / システム管理者 / 開発環境構築担当エンジニア                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、[SBOS-DD-004](SBOS-DD-004_Aider%E7%B5%B1%E5%90%88%E4%BB%95%E6%A7%98.md)、[SBOS-DD-005](SBOS-DD-005_Backend_GPU%E3%83%AA%E3%83%BC%E3%82%B9%E4%BB%95%E6%A7%98.md)、[SBOS-DD-006](SBOS-DD-006_%E5%93%81%E8%B3%AA%E3%82%B2%E3%83%BC%E3%83%88_%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC%E4%BB%95%E6%A7%98.md)、[SBOS-DD-007](SBOS-DD-007_%E6%B0%B8%E7%B6%9A%E5%8C%96_%E6%8E%92%E4%BB%96%E5%88%B6%E5%BE%A1%E4%BB%95%E6%A7%98.md)、SBOS-OP-001（運用詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. ハードウェア・システム前提要件

> **前提の改訂（Rev.4.8、Epic #116）**: Rev.4.7 までは「完全オフライン環境およびローカルマシンの計算リソースで稼働する」ことを前提としていた。次のとおり改める。
> - **【現行】**: planner / coder / reviewer はローカルLLM（Ollama、llama-server、Aider）で動作する。以下の GPU 要件はこの構成のものである。
> - **【移行設計・未実装】**: JEV を除くローカルLLM使用箇所を agy へ置き換える（SBOS-DD-003 §2.2）。agy 経路では **GPU は不要**で、**インターネット接続と agy の認証が必要**になる（完全オフラインではなくなる）。
> - **JEV は据え置き**のため、agy 移行後も **Ollama と軽量モデル（既定 `qwen2.5:0.5b`）は必要**である。この用途に限れば、GPU 要件は最小要件で足りる見込みである（実測は未実施）。
> - 旧 profile を残す移行期間（Issue #123 まで）と、ロールバック時には、従来の GPU 要件がそのまま必要である。

本システムは、現行はローカルマシンの計算リソースで稼働する。以下のハードウェア・ソフトウェア要件を満たす必要がある。

### 1.1 推奨ハードウェア要件（GPU VRAM 割り当て）【現行】
ローカルLLMを並列あるいは高速ロードして稼働させるため、特に NVIDIA GPU または Apple Silicon (Mシリーズ) Unified Memory の VRAM 容量が極めて重要となる。

| パターン     | システム構成・GPUスペック                                                    | 稼働可能なモデル構成                                                          | 想定パフォーマンス                                                                             |
| :----------- | :--------------------------------------------------------------------------- | :---------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| **推奨環境** | **NVIDIA RTX 4090 (24GB VRAM)**<br>または Apple M3/M4 Max (64GB RAM)         | • 大型・高精度モデルを各役割 (`reviewer`, `planner`, `coder`, `aider`) に配備 | 大規模モデルをVRAMに常駐させつつ、高速応答性と高品質な設計・監査を両立。                       |
| **標準環境** | **NVIDIA RTX 4080 / 3090 (16GB VRAM)**<br>または Apple M2/M3 Pro (32GB RAM)  | • 中型標準モデルを各役割に配備                                                | 標準的なローカルモデル構成で全タスクの実用的かつ安定した自律処理が可能。                       |
| **最小要件** | **NVIDIA RTX 3060 / 4060 (8GB〜12GB VRAM)**<br>または Apple M1/M2 (16GB RAM) | • 全エージェント共通で軽量モデルを配備                                        | 軽量モデル単体による運用。高度なレビューや複雑な要件定義ではリトライ回数が増加する可能性あり。 |

### 1.2 必須ソフトウェアおよびミドルウェア
- **OS:** Linux (Ubuntu 22.04 LTS+ / Debian 12+), macOS (Sonoma 14+), または Windows 11 (Windows Native / WSL2 両対応)
- **Python:** Version 3.10 以上 (推奨: Python 3.11 または 3.12)
- **パッケージマネージャー:** `uv` (Astral製 - 依存関係の確定的かつ高速な解決のために必須)
- **Git:** Version 2.30 以上
- **Ollama:** Version 0.3.0 以上 (OpenAI 互換 REST API `/v1` エンドポイントが `localhost:11434` で有効化されていること)
- **Aider CLI:** `aider-chat` (Gitワーキングツリー差分編集用エンジン)【現行。agy への移行後も、退役（Issue #128）までは必要】
- **Reviewdog:** CLI (rdjson 差分行アノテーション表示用エンジン)
- **agy（Antigravity CLI）【移行設計】:** 非対話（ヘッドレス）で実行できること。実行ファイルは PATH 上、または `%USERPROFILE%\AppData\Local\agy\bin\agy.exe` / `~\.cargo\bin\agy.exe` に配置する（既存の `satellite-ideation-reviewer` スキルの解決順。`agy_client` もこれに従う予定）。事前に認証を済ませておくこと。認証情報の中身は、リポジトリ・ログ・ドキュメントに記録しない。
  - **確認項目（Issue #117 で確定し、本節へ反映する）**: 導入手順、認証方式、非対話での編集実行の可否、モデル指定オプションの有無、入力長の上限、作業ディレクトリに作られる成果物の名前。
  - **現時点の確認状況**: 調査時点の開発環境では、`agy` が PATH にも上記の既知の配置先にも見つからなかった。夜間 worker を動かす機器（導入済みか）を、移行の前に確認すること。

---

## 2. モデル配置管理仕様 (`config/models.yaml`)

> **訂正（Rev.4.8）**: Rev.4.7 までは SSOT を `config/models.json` と記載していたが、`tools/config_loader.py` が読み込むのは **`config/models.yaml` のみ**である（SBOS-DD-005 §2）。`models.json` は旧版のコピーであり、扱いは Issue #128 で決める。以下の §2.2 の JSON 例は、構造の説明用の旧形式であり、実際の設定の書式は `models.yaml`（`backend_execution.profiles` / `routes`）を正とする。

### 2.1 一元管理モデル設定方針
本システムでは、ドキュメントやモジュールコード内に具体的なモデル名を直接記述・ハードコードせず、すべて **`config/models.yaml`** にて一元管理（Single Source of Truth: SSOT）する。

ユーザー環境でダウンロード済み・利用可能な Ollama モデル (`ollama list`) を確認し、`config/models.yaml` に動的に割り当てる。

【移行設計】agy への移行後は、LLM の実行先を `backend_execution.routes` が指す profile で切り替える。agy の profile（`backend: agy`）にはモデルのパスやエンドポイントを持たない（SBOS-DD-005 §2.1）。

### 2.2 設定ファイル構成例（旧形式の `config/models.json`）

```json
{
  "api_base": "http://localhost:11434",
  "default_provider": "ollama",
  "models": {
    "planner": {
      "model_name": "ollama/<実在の汎用ローカルモデル名>",
      "temperature": 0.2,
      "max_tokens": 35000
    },
    "coder": {
      "model_name": "ollama/<実在のコード用ローカルモデル名>",
      "temperature": 0.1,
      "max_tokens": 35000
    },
    "reviewer": {
      "model_name": "ollama/<実在の汎用ローカルモデル名>",
      "temperature": 0.1,
      "max_tokens": 35000
    }
  },
  "aider": {
    "model_name": "ollama/<実在のコード用ローカルモデル名>",
    "no_auto_commits": true,
    "edit_format": "diff"
  }
}
```

各モジュール (`tools/llm_client.py`, `tools/aider_runner.py` 等) は `tools/config_loader.py` 経由でこの設定を動的に参照し、LLM 呼び出しを行う。
Aider 実行時は環境変数 `OLLAMA_API_BASE=http://localhost:11434` を設定し、`--no-auto-commits` (複数形) フラグを付加して非破壊的なワーキングツリー差分適用を行う。

---

## 3. ステップ・バイ・ステップ環境構築手順

新規マシンまたはクリーンな開発環境に本システムスタックをゼロから構築するための手順書を以下に規定する。

### Step 1: 必須ツールと Python パッケージマネージャー (uv) の導入
```bash
# 1. uv のインストール
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # または ~/.zshrc

# 2. Ollama サーバーの稼働確認
curl -s http://localhost:11434/api/version
```

### Step 2: 母艦リポジトリおよび Git 隔離構造の初期化
```bash
# 1. 母艦ディレクトリの作成と Git 初期化
mkdir -p ~/second-brain
cd ~/second-brain
git init

# 2. ツール・テンプレートおよびキャッシュ用フォルダ構成の作成
mkdir -p tools/.cache tools/templates projects config

# 3. 母艦側 .gitignore の作成（衛星プロジェクト完全遮断ルールの適用 PM-027）
cat << 'EOF' > .gitignore
# 衛星プロジェクトのソースコードおよびGit履歴を母艦から完全に遮断
/projects/*
/projects/.*
!/projects/.gitkeep
!.gitignore

# キャッシュ・ログ・ツールバイナリ
/tools/bin/
/tools/reviewdog/
tools/.cache/*
*.log
__pycache__/
*.pyc
.venv/
.aider*
EOF

# 4. 衛星台帳インデックスおよびメタデータディレクトリの初期化 (PM-026/027 対応)
mkdir -p metadata/projects projects
cat > metadata/.project-registry.json << 'EOF'
{
  "version": "1.0",
  "projects": {}
}
EOF
touch metadata/projects/.gitkeep projects/.gitkeep
git add .gitignore metadata/ projects/.gitkeep
git commit -m "chore: initialize second-brain OS base structure"
```

### Step 3: Python 仮想環境・新OSSスタックおよび Reviewdog の構築

```bash
cd ~/second-brain

# 1. uv による Python 仮想環境の初期化と新OSSスタックの導入
uv venv
source .venv/bin/activate  # Windows (PowerShell) の場合: .venv\Scripts\Activate.ps1
uv pip install langgraph litellm aider-chat ruff pytest pytest-json-report

# 2. Reviewdog のインストール
# Linux / macOS の場合:
bash scripts/linux/setup_reviewdog.sh
tools/bin/reviewdog -version

# Windows Native の場合 (PowerShell):
.\scripts\windows\setup_reviewdog.ps1

# 3. ruff 設定ファイル (ruff.toml) の配置
cat << 'EOF' > ruff.toml
line-length = 100
target-version = "py310"

[lint]
select = ["E", "F", "W", "I", "N", "B"]
ignore = ["E501"]
EOF
```

### Step 4: プロンプトテンプレートの配置確認
```bash
# プロンプトテンプレートの配置確認
ls -l tools/templates/
# -> planner.md, coder.md, reviewer.md が存在することを確認
```

---

## 4. 動作検証スクリプトと診断コマンド

構築完了後、環境全体が正常に機能しているかを検証するための診断テストを実行する。

### 4.1 モジュールインポートおよび単体スクリプト健全性テスト
```bash
cd ~/second-brain
source .venv/bin/activate

# 1. LangGraph / LiteLLM / Aider コンポーネントインポートテスト
python -c "import langgraph; import litellm; print('✓ LangGraph & LiteLLM loaded successfully')"
python -c "from tools.llm_client import call_llm; print('✓ llm_client.py initialized')"
python -c "from tools.aider_runner import run_aider; print('✓ aider_runner.py loaded')"

# 2. スコアリングとブロッカー検知スクリプトのドライラン
python tools/score-issues.py
python tools/check-blockers.py
```

---

## 5. OS別最適化および Windows Native / WSL2 セットアップガイド

### 5.1 Windows Native 環境向け最適化設定 (PowerShell)

Windows Native 環境で動作させる場合は、以下の Git および PowerShell 設定が必須となる。

1. **Git 改行コードバグ対策 (`autocrlf` 設定):**
   Aider による差分適用時に CRLF / LF 混在で diff が爆発することを防ぐため、必ず `input` を設定する。
   ```powershell
   git config --global core.autocrlf input
   ```

2. **PowerShell 文字化け対策 ($PROFILE への UTF-8 永続設定):**
   日本語パスや Reviewdog の出力文字化けを防止するため、PowerShell プロファイル (`$PROFILE`) へ UTF-8 永続設定を追加する。

   **設定コマンド (重複防止アトミック追記):**
   ```powershell
   if (!(Test-Path $PROFILE)) { New-Item -Type File -Path $PROFILE -Force }
   $utf8Cmd = '$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()'
   if (!(Select-String -Path $PROFILE -Pattern "UTF8Encoding" -Quiet)) {
       Add-Content -Path $PROFILE -Value "`n$utf8Cmd" -Encoding utf8
       Write-Host "✓ $PROFILE に UTF-8 永続設定を追加しました。" -ForegroundColor Green
   } else {
       Write-Host "✓ $PROFILE には既に UTF-8 永続設定が存在します。" -ForegroundColor Yellow
   }
   ```

   **新規 PowerShell セッションでの確認手順:**
   新しい PowerShell ウィンドウを起動し、以下を実行して出力エンコーディングが UTF-8 であることを確認する。
   ```powershell
   $OutputEncoding.EncodingName
   # 期待される出力: Unicode (UTF-8)
   ```

### 5.2 WSL2 環境向けパフォーマンス最適化 (Linux)
WSL2 環境で構築する場合は、NTFS クロスアクセスによる速度低下を防ぐため、必ず WSL2 内部の Linux 仮想ディスク (`/home/<username>/second-brain`) 上にリポジトリを配置すること。

---

## 6. 定常自動バッチ・バックグラウンドワーカーの構成

朝の優先度スコアリングや自動ブロッカー検知を確実に行うための自動化登録手順を規定する。

### 6.1 Linux / WSL2 環境向け (systemd)
`~/.config/systemd/user/second-brain-batch.service` およびタイマーユニットを作成し、`systemctl --user enable --now second-brain-batch.timer` を実行する。

### 6.2 Windows Native 環境向け (Task Scheduler)
Windows Native 環境では PowerShell から `Register-ScheduledTask` コマンドを用いて日次ジョブを登録する。

```powershell
# 毎朝 07:00 に score-issues.py と check-blockers.py を自動実行するタスク登録
$Action = New-ScheduledTaskAction -Execute "uv" -Argument "run python tools/score-issues.py" -WorkingDirectory "$Home\second-brain"
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
Register-ScheduledTask -TaskName "SecondBrainDailyScoring" -Action $Action -Trigger $Trigger -Description "Second Brain OS Daily Scoring Job"
```

---

## 7. 全環境診断・健全性検証スクリプト (`verify_environment.py`)

構築作業完了後、全層（Ollama API, Aider, Reviewdog, Ruff, Pytest, LangGraph）の動作状況を一括診断するスクリプトの実装仕様である。

> **Rev.4.8 注記**: 以下のスクリプト例は【現行】構成の診断である。【移行設計】agy への移行後は、(1) Ollama API のチェックは JEV のために引き続き必要（据え置き）、(2) `aider` コマンドのチェックは Aider の退役（Issue #128）まで必要、(3) **`agy` の実行ファイルの解決と認証状態のチェックを追加する**。なお、実運用の診断は `tools/doctor.py` が担っており、本節のスクリプトは仕様例である。`agy` が未導入でも他のチェックの結果を隠さないため、agy のチェックは `FAIL` で即時終了せず、`WARN` として報告する設計とする（実装は Issue #119 以降で別途決める）。

```python
#!/usr/bin/env python3
"""Second Brain OS (Rev.4.3) 環境健全性診断スクリプト"""

import os
import sys
import subprocess
import urllib.request
import json


def print_result(check_name: str, passed: bool, msg: str = ""):
    icon = "✓" if passed else "✗"
    status = "PASS" if passed else "FAIL"
    print(f"[{icon}] {status} | {check_name} {': ' + msg if msg else ''}")
    if not passed:
        sys.exit(1)


def main():
    print("=== Second Brain OS Full Environment Diagnostic ===")

    # 1. Python バージョンチェック
    py_ver = sys.version_info
    print_result(
        "Python Version >= 3.10",
        py_ver.major == 3 and py_ver.minor >= 10,
        f"{py_ver.major}.{py_ver.minor}",
    )

    # 2. Ollama API アクセスチェック
    try:
        with urllib.request.urlopen("http://localhost:11434/api/version", timeout=3) as res:
            data = json.loads(res.read().decode())
            print_result("Ollama API Server Running", True, f"v{data.get('version')}")
    except Exception as e:
        print_result("Ollama API Server Running", False, str(e))

    # 3. 新OSSスタック (Aider, Reviewdog, Ruff, Pytest) コマンドチェック
    for tool, cmd_flag in [
        ("aider", "--version"),
        ("reviewdog", "-version"),
        ("ruff", "--version"),
        ("pytest", "--version"),
    ]:
        try:
            out = subprocess.check_output([tool, cmd_flag], stderr=subprocess.STDOUT, text=True)
            print_result(f"Tool '{tool}' Available", True, out.splitlines()[0].strip())
        except Exception as e:
            print_result(f"Tool '{tool}' Available", False, str(e))

    # 4. LangGraph / LiteLLM Python パッケージインポートチェック
    try:
        import langgraph
        import litellm
        import pytest_jsonreport

        print_result(
            "Python OSS Packages (LangGraph, LiteLLM, etc.)", True, "Imported successfully"
        )
    except ImportError as e:
        print_result("Python OSS Packages", False, f"ImportError: {e}")

    # 5. 台帳インデックス構造チェック
    reg_path = "metadata/.project-registry.json"
    print_result("Project Registry File Exists", os.path.exists(reg_path), reg_path)

    print("=== All Diagnostics Passed Successfully! ===")


if __name__ == "__main__":
    main()
```
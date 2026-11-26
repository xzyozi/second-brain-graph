# 環境構築仕様書（システム前提要件・マルチモデル配置・セットアップガイド）
**agy（現行）／JEV用Ollama（据え置き）× LangGraph × Reviewdog 実行環境仕様**

| 項目     | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号 | SBOS-ENV-001                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 版数     | Rev.5.0（`pyproject.toml` / `uv sync`・`tools/doctor.py`・`config/prompt.yaml`・GitHub CLI・多言語ツール要件へ整合）                                                                                                                                                                                                                                                                                                                                                                                                              |
| 改訂日   | 2026年11月27日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 作成日   | 2026年7月27日                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| 対象読者 | インフラエンジニア / システム管理者 / 開発環境構築担当エンジニア                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、[SBOS-DD-004](SBOS-DD-004_Aider%E7%B5%B1%E5%90%88%E4%BB%95%E6%A7%98.md)、[SBOS-DD-005](SBOS-DD-005_Backend_GPU%E3%83%AA%E3%83%BC%E3%82%B9%E4%BB%95%E6%A7%98.md)、[SBOS-DD-006](SBOS-DD-006_%E5%93%81%E8%B3%AA%E3%82%B2%E3%83%BC%E3%83%88_%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC%E4%BB%95%E6%A7%98.md)、[SBOS-DD-007](SBOS-DD-007_%E6%B0%B8%E7%B6%9A%E5%8C%96_%E6%8E%92%E4%BB%96%E5%88%B6%E5%BE%A1%E4%BB%95%E6%A7%98.md)、SBOS-OP-001（運用詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. ハードウェア・システム前提要件

> **現行構成**: planner / coder / reviewer はagyで動作する。agy経路ではGPUは不要だが、インターネット接続とagy認証が必要である。
> - JEVは据え置きのため、Ollamaと軽量モデル（既定 `qwen2.5:0.5b`）は必要である。
> - Aider、llama-server、旧local profileはruntimeから退役し、旧資産は `legacy/local_llm/` と archive tag に保存する。

本システムは、現行はローカルマシンの計算リソースで稼働する。以下のハードウェア・ソフトウェア要件を満たす必要がある。

### 1.1 推奨ハードウェア要件（GPU VRAM 割り当て）【JEV / 旧ローカル構成向け参考】
現行の planner / coder / reviewer は `agy` を利用するためローカル GPU VRAM を必要としない。以下の GPU 要件は JEV（軽量モデル `qwen2.5:0.5b` 程度）のみであれば最小要件以下でも稼働可能であり、旧ローカル LLM 資産を復元・比較検証する場合の参考値として保持する。

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
- **GitHub CLI (`gh`):** GitHub Issues SSOT 取得、ラベル同期、PR 作成および `ci_watch_node` による CI 監視のために必須（`gh auth status` で認証済みであること）
- **Ollama:** JEV（`tools/backends/jev_adapter.py`, `tools/screen_issues.py`）を使う場合のみ必要。Version 0.3.0 以上（OpenAI互換REST API `/v1` が `localhost:11434` で有効）
- **agy（Antigravity CLI）:** 現行LLM runtime。非対話（ヘッドレス）実行、認証済み、PATHまたは `agy_client` の既知パスから解決可能であること。認証情報の中身は記録しない。
- **Node.js / npm・Rust / cargo（任意）:** TypeScript / JavaScript または Rust サテライトで `npm test` / `cargo test` や Mermaid CI 検証（`.github/scripts/validateMermaidMarkdown.mjs`）を実行する場合に必要。
- **Aider CLI:** runtimeには不要。旧資産の復旧・比較検証を行う場合だけ `legacy/local_llm/` または archive tag から別途復元する。

---

## 2. モデル配置管理仕様 (`config/models.yaml`)

> **訂正（Rev.4.8）**: Rev.4.7 までは SSOT を `config/models.json` と記載していたが、`tools/workspace/config_loader.py` が読み込むのは **`config/models.yaml` のみ**である（SBOS-DD-005 §2）。`models.json` は旧版のコピーであり、扱いは Issue #128 で決める。以下の §2.2 の JSON 例は、構造の説明用の旧形式であり、実際の設定の書式は `models.yaml`（`backend_execution.profiles` / `routes`）を正とする。

### 2.1 一元管理モデル設定方針
本システムでは、ドキュメントやモジュールコード内に具体的なモデル名を直接記述・ハードコードせず、すべて **`config/models.yaml`** にて一元管理（Single Source of Truth: SSOT）する。

ユーザー環境でダウンロード済み・利用可能な Ollama モデル (`ollama list`) を確認し、`config/models.yaml` に動的に割り当てる。

agyへの移行後は、LLMの実行先を `backend_execution.routes` が指すprofileで解決する。agy profile（`backend: agy`）にはモデルパスやOpenAI endpointを持たない。Ollamaの設定はJEV用に限り有効である。

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

各モジュール（`tools/backends/llm_client.py`、`tools/backends/agy_runner.py`等）は `tools/workspace/config_loader.py` 経由で設定を参照する。Aiderの旧CLI設定はlegacy/archiveの資産としてのみ保持する。

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

### Step 3: Python 仮想環境・依存スタック (`uv sync`) および Reviewdog の構築

```bash
cd ~/second-brain-graph

# 1. pyproject.toml / uv.lock に基づく Python 仮想環境と開発用依存の同期
uv sync --extra dev

# 2. Reviewdog のインストール (任意依存: 未導入時はスキップ)
# Linux / macOS の場合:
bash scripts/linux/setup_reviewdog.sh
tools/bin/reviewdog -version

# Windows Native の場合 (PowerShell):
.\scripts\windows\setup_reviewdog.ps1
```

### Step 4: プロンプト SSOT および設定ファイルの確認
```bash
# プロンプト SSOT とモデル・ワーカー設定の確認
ls -l config/models.yaml config/prompt.yaml config/nightly_worker.toml
# -> tools/core/prompt_harness.py が config/prompt.yaml を解決する
```

---

## 4. 動作検証スクリプトと診断コマンド

構築完了後、環境全体が正常に機能しているかを検証するための診断テストを実行する。

### 4.1 モジュールインポートおよび健全性テスト
```bash
cd ~/second-brain-graph

# 1. LangGraph / agy / 多言語検証基盤のインポートテスト
uv run python -c "import langgraph; from tools.backends.llm_client import call_llm; from tools.backends.agy_runner import run_agy_edit; from tools.lang import get_verifier; print('✓ Core modules loaded successfully')"

# 2. サテライト受入態勢・環境診断とスコアリングの実行
uv run python tools/doctor.py --all
uv run python tools/score_issues.py

# 3. 静的解析・型検査・単体テスト
uv run ruff check .
uv run mypy .
uv run pytest
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
Windows Native 環境では PowerShell から `Register-ScheduledTask` コマンドを用いて日次ジョブを登録する（または `tools/nightly_task_worker.py --loop` の常駐ループを利用する）。

```powershell
# 毎朝 07:00 に tools/score_issues.py を自動実行するタスク登録
$Action = New-ScheduledTaskAction -Execute "uv" -Argument "run python tools/score_issues.py" -WorkingDirectory "$Home\second-brain-graph"
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
Register-ScheduledTask -TaskName "SecondBrainDailyScoring" -Action $Action -Trigger $Trigger -Description "Second Brain OS Daily Scoring Job"
```

---

## 7. 全環境診断・健全性検証 (`tools/doctor.py`)

環境および登録済みサテライトの受入態勢（`metadata/.project-registry.json`, `docs/project.json`, レガシー `tasks.md` / `docs/issues/` 不在確認, 言語別実行環境, `.gitignore`, GitHub Issues SSOT 疎通, 標準ラベル, Reviewdog）は、実装済みの [`tools/doctor.py`](../../tools/doctor.py) を用いて一括診断・自動修復する。

```bash
# 全登録サテライトを一括診断
uv run python tools/doctor.py --all

# 特定サテライトを診断し不足設定を自動修復
uv run python tools/doctor.py <PROJECT_KEY> --fix
```
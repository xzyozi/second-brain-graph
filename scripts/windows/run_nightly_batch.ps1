# ==============================================================================
# scripts/windows/run_nightly_batch.ps1
# Windows タスクスケジューラ用 自律夜間バッチ実行ラッパースクリプト
# ==============================================================================

[CmdletBinding()]
param (
    [string]$ConfigPath = "config/nightly_worker.toml",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# 母艦リポジトリのルートパスをスクリプト位置から自動解決
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path "$ScriptDir\..\..").Path
Set-Location $RepoRoot

# ログディレクトリの作成
$LogDir = Join-Path $RepoRoot "logs\nightly"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Today = Get-Date -Format "yyyyMMdd"
$LogFile = Join-Path $LogDir "batch_$Today.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Add-Content -Path $LogFile -Value "[$Timestamp] ===== 自律夜間バッチ起動 ====="

$ArgsList = @("run", "python", "tools/nightly_task_worker.py", "--config", $ConfigPath)
if ($DryRun) {
    $ArgsList += "--dry-run"
}

try {
    # uv run で自律ワーカースクリプトを実行
    & uv @ArgsList 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ExitCode = $LASTEXITCODE
    $EndTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$EndTimestamp] ===== バッチ終了 (ExitCode: $ExitCode) ====="
    exit $ExitCode
}
catch {
    $ErrMsg = $_.Exception.Message
    $EndTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$EndTimestamp] [ERROR] 実行例外: $ErrMsg"
    exit 1
}

# ==============================================================================
# scripts/windows/register_task_scheduler.ps1
# Windows タスクスケジューラへの自律夜間バッチ登録・解除支援スクリプト
# ==============================================================================

[CmdletBinding()]
param (
    [Parameter(ParameterSetName = "Register")]
    [switch]$Register,

    [Parameter(ParameterSetName = "Register")]
    [string]$Time = "03:00",

    [Parameter(ParameterSetName = "Unregister")]
    [switch]$Unregister,

    [Parameter(ParameterSetName = "Status")]
    [switch]$Status
)

$TaskName = "SecondBrainGraph_NightlyTaskWorker"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerScript = (Resolve-Path "$ScriptDir\run_nightly_batch.ps1").Path

if ($Unregister) {
    Write-Host "タスクスケジューラから '$TaskName' を削除します..." -ForegroundColor Yellow
    schtasks.exe /Delete /TN $TaskName /F
    Write-Host "削除が完了しました。" -ForegroundColor Green
    exit 0
}

if ($Status) {
    Write-Host "タスクスケジューラの状態確認: '$TaskName'" -ForegroundColor Cyan
    schtasks.exe /Query /TN $TaskName /FO LIST /V
    exit 0
}

if ($Register -or ($PSCmdlet.ParameterSetName -eq "Register")) {
    Write-Host "タスクスケジューラに登録中..." -ForegroundColor Cyan
    Write-Host "  タスク名: $TaskName"
    Write-Host "  実行時刻: 毎日 $Time"
    Write-Host "  スクリプト: $RunnerScript"

    $Action = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`""

    # schtasks でカレントユーザー権限で登録 (管理者権限不要)
    $SchArgs = @(
        "/Create",
        "/TN", $TaskName,
        "/TR", $Action,
        "/SC", "DAILY",
        "/ST", $Time,
        "/F"
    )

    $Proc = Start-Process -FilePath "schtasks.exe" -ArgumentList $SchArgs -Wait -NoNewWindow -PassThru
    if ($Proc.ExitCode -eq 0) {
        Write-Host "タスクスケジューラへの登録が正常完了しました！" -ForegroundColor Green
        Write-Host "確認コマンド: powershell -File scripts/windows/register_task_scheduler.ps1 -Status" -ForegroundColor Gray
        Write-Host "解除コマンド: powershell -File scripts/windows/register_task_scheduler.ps1 -Unregister" -ForegroundColor Gray
    } else {
        Write-Host "タスクスケジューラへの登録に失敗しました (ExitCode: $($Proc.ExitCode))" -ForegroundColor Red
        exit 1
    }
}

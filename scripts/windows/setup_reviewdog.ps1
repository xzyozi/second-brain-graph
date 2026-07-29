# Reviewdog Automated Git Clone & Setup Script (PowerShell for Windows)
Param (
    [string]$CloneDir = "$PSScriptRoot\..\..\tools\reviewdog"
)

$ErrorActionPreference = "Stop"
Write-Host "=== Setting up Windows Environment & Reviewdog ===" -ForegroundColor Cyan

# 0. Ensure git core.autocrlf setting (PM-012)
Write-Host "Setting git core.autocrlf to 'input'..." -ForegroundColor Cyan
git config --global core.autocrlf input
Write-Host "✓ Git core.autocrlf configured to input." -ForegroundColor Green

# 1. Check PowerShell UTF-8 OutputEncoding status without modifying $PROFILE (PM-015)
Write-Host "`nChecking PowerShell UTF-8 encoding status..." -ForegroundColor Cyan
if ($OutputEncoding.EncodingName -like "*UTF-8*") {
    Write-Host "✓ PowerShell UTF-8 output encoding is active ($($OutputEncoding.EncodingName))." -ForegroundColor Green
} else {
    Write-Host "[!] PowerShell current output encoding is '$($OutputEncoding.EncodingName)'." -ForegroundColor Yellow
    Write-Host "To permanently enable UTF-8 for Reviewdog and Python scripts, add the following line to your `$PROFILE:" -ForegroundColor Yellow
    Write-Host '`$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()' -ForegroundColor Yellow
    Write-Host "(See docs/design/04_環境構築仕様書_SBOS-ENV-001.md §5.1 for full instructions)" -ForegroundColor Gray
}

# 2. Check existing git clone
Write-Host "`nChecking Reviewdog source repository..." -ForegroundColor Cyan
if (Test-Path $CloneDir) {
    Write-Host "Reviewdog repository already cloned at: $CloneDir" -ForegroundColor Yellow
} else {
    Write-Host "Cloning Reviewdog from https://github.com/reviewdog/reviewdog.git..." -ForegroundColor Cyan
    git clone https://github.com/reviewdog/reviewdog.git $CloneDir
    Write-Host "Successfully cloned Reviewdog repository." -ForegroundColor Green
}

Write-Host "Reviewdog source files are ready at: $CloneDir" -ForegroundColor Green

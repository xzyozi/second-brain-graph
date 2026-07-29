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

# 1. Check existing git clone
if (Test-Path $CloneDir) {
    Write-Host "Reviewdog repository already cloned at: $CloneDir" -ForegroundColor Yellow
} else {
    Write-Host "Cloning Reviewdog from https://github.com/reviewdog/reviewdog.git..." -ForegroundColor Cyan
    git clone https://github.com/reviewdog/reviewdog.git $CloneDir
    Write-Host "Successfully cloned Reviewdog repository." -ForegroundColor Green
}

Write-Host "Reviewdog source files are ready at: $CloneDir" -ForegroundColor Green

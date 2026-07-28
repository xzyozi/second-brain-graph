# Reviewdog Automated Git Clone & Setup Script (PowerShell for Windows)
Param (
    [string]$CloneDir = "$PSScriptRoot\..\tools\reviewdog"
)

$ErrorActionPreference = "Stop"
Write-Host "=== Setting up Reviewdog via Git Clone ===" -ForegroundColor Cyan

# 1. Check existing git clone
if (Test-Path $CloneDir) {
    Write-Host "Reviewdog repository already cloned at: $CloneDir" -ForegroundColor Yellow
} else {
    Write-Host "Cloning Reviewdog from https://github.com/reviewdog/reviewdog.git..." -ForegroundColor Cyan
    git clone https://github.com/reviewdog/reviewdog.git $CloneDir
    Write-Host "Successfully cloned Reviewdog repository." -ForegroundColor Green
}

Write-Host "Reviewdog source files are ready at: $CloneDir" -ForegroundColor Green

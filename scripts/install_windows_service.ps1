<#
.SYNOPSIS
Installs Amadeus-AI as a background Windows Service using NSSM (Non-Sucking Service Manager).

.DESCRIPTION
This script downloads NSSM if Not present, registers the Amadeus-AI Uvicorn server as a 
persistent background service that starts on boot, and ensures it runs silently.

.NOTES
Run this script as Administrator.
#>

$ErrorActionPreference = "Stop"

# Define Service Details
$ServiceName = "AmadeusAI_Daemon"
$ProjectRoot = (Get-Item -Path ".\").FullName
$DistExe = Join-Path $ProjectRoot "dist\amadeus\amadeus.exe"

# 1. Check for Admin Rights
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-Not $isAdmin) {
    Write-Host "Elevating to Administrator..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-File `"$PSCommandPath`""
    Exit
}

Write-Host "=== Amadeus Windows Daemon Service Installation ===" -ForegroundColor Cyan

# 2. Check if Compiled Exe exists
if (-Not (Test-Path $DistExe)) {
    Write-Host "Error: Compiled executable not found at $DistExe." -ForegroundColor Red
    Write-Host "Please run 'python scripts\build_windows.py' first to build the executable." -ForegroundColor Red
    Exit
}

# 3. Download NSSM if needed
$NssmDir = Join-Path $ProjectRoot "scripts\nssm"
$NssmExe = Join-Path $NssmDir "win64\nssm.exe"

if (-Not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM (Service Manager)..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $NssmDir | Out-Null
    $NssmZip = Join-Path $NssmDir "nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip
    Expand-Archive -Path $NssmZip -DestinationPath $NssmDir -Force
    $ExtractedFolder = Get-ChildItem -Path $NssmDir -Directory | Where-Object { $_.Name -like "nssm-*" } | Select-Object -First 1
    Move-Item -Path "$($ExtractedFolder.FullName)\win64" -Destination $NssmDir -Force
    Remove-Item $NssmZip
    Remove-Item $ExtractedFolder.FullName -Recurse -Force
}

# 4. Remove existing service if it exists
$serviceExists = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($serviceExists) {
    Write-Host "Stopping and removing existing $ServiceName service..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force
    & $NssmExe remove $ServiceName confirm
}

# 5. Register the Service via NSSM
Write-Host "Registering compiled Amadeus-AI as a background service..." -ForegroundColor Green
& $NssmExe install $ServiceName $DistExe
& $NssmExe set $ServiceName AppDirectory $ProjectRoot
& $NssmExe set $ServiceName Description "Amadeus-AI Windows Daemon Backend"
& $NssmExe set $ServiceName AppStdout (Join-Path $ProjectRoot "data\logs\amadeus_service_stdout.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $ProjectRoot "data\logs\amadeus_service_error.log")

# 6. Ensure Logs directory exists
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\logs") | Out-Null

# 7. Start the Service
Write-Host "Starting the J.A.R.V.I.S. Engine..." -ForegroundColor Cyan
Start-Service -Name $ServiceName

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "✅ The Amadeus-AI Daemon is now running in the background!" -ForegroundColor Green
Write-Host "   API is available at http://127.0.0.1:8000" -ForegroundColor White
Write-Host "   Logs are stored in $ProjectRoot\data\logs\" -ForegroundColor White
Write-Host "   To view or stop it, open 'Services.msc' and look for '$ServiceName'" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green

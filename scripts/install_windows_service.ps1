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
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$UvicornExe = Join-Path $VenvPath "Scripts\uvicorn.exe"

# 1. Check for Admin Rights
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-Not $isAdmin) {
    Write-Host "Elevating to Administrator..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-File `"$PSCommandPath`""
    Exit
}

Write-Host "=== J.A.R.V.I.S. Protocol Initiation (Amadeus Windows Daemon) ===" -ForegroundColor Cyan

# 2. Check if Python Venv exists
if (-Not (Test-Path $PythonExe)) {
    Write-Host "Error: Virtual environment not found at $VenvPath." -ForegroundColor Red
    Write-Host "Please run 'uv sync' or 'pip install -e .' first." -ForegroundColor Red
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
Write-Host "Registering Amadeus-AI as a background service..." -ForegroundColor Green
& $NssmExe install $ServiceName $UvicornExe
& $NssmExe set $ServiceName AppParameters "src.api.server:app --host 127.0.0.1 --port 8000 --workers 1"
& $NssmExe set $ServiceName AppDirectory $ProjectRoot
& $NssmExe set $ServiceName Description "Amadeus-AI (J.A.R.V.I.S) Background Daemon"
& $NssmExe set $ServiceName AppStdout (Join-Path $ProjectRoot "logs\amadeus_daemon.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $ProjectRoot "logs\amadeus_daemon_error.log")

# 6. Ensure Logs directory exists
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null

# 7. Start the Service
Write-Host "Starting the J.A.R.V.I.S. Engine..." -ForegroundColor Cyan
Start-Service -Name $ServiceName

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "✅ The Amadeus-AI Daemon is now running in the background!" -ForegroundColor Green
Write-Host "   API is available at http://127.0.0.1:8000" -ForegroundColor White
Write-Host "   Logs are stored in $ProjectRoot\logs\" -ForegroundColor White
Write-Host "   To view or stop it, open 'Services.msc' and look for '$ServiceName'" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green

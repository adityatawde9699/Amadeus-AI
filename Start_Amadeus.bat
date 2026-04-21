@echo off
echo ====================================================
echo    Amadeus AI - Quick Start (v3.1.0)
echo ====================================================
echo.

REM Check for .env file
if not exist .env (
    echo [!] ERROR: .env file not found.
    echo     Please run Setup_Amadeus.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting the AI assistant...
echo.
docker-compose up -d

if %errorlevel% neq 0 (
    echo [!] ERROR: Failed to start. Is Docker Desktop running?
) else (
    echo.
    echo ====================================================
    echo    RUNNING! Open the assistant here:
    echo    http://localhost:8000/docs
    echo    http://localhost:8000/health
    echo ====================================================
)

echo.
pause

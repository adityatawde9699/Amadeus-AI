@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo    Amadeus AI - First Time Setup
echo    v3.1.0 — Semantic Router Edition
echo ====================================================

REM 1. Check for Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] ERROR: Docker Desktop is not installed or not running.
    echo.
    echo Please download and install Docker Desktop first:
    echo https://www.docker.com/products/docker-desktop/
    echo.
    echo Once installed, make sure it is RUNNING and try again.
    pause
    exit /b 1
)

REM 2. Create .env file
if not exist .env (
    echo [1/4] Setting up your configuration file...
    if exist .env.example (
        copy .env.example .env >nul
    ) else (
        echo [!] ERROR: .env.example not found!
        pause
        exit /b 1
    )

    echo.
    echo [2/4] Enter your AI API keys:
    set /p GROQ_KEY="   - GROQ_API_KEY (required, free at console.groq.com): "
    set /p GEMINI_KEY="   - GEMINI_API_KEY (optional, press Enter to skip): "

    echo.
    echo [3/4] Generating a secure SECRET_KEY for JWT authentication...
    REM Generate a random secret using Python (always available in the venv)
    for /f %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set SECRET_KEY=%%i
    if "!SECRET_KEY!"=="" (
        echo [!] WARNING: Could not auto-generate SECRET_KEY.
        set /p SECRET_KEY="   - Enter a SECRET_KEY manually (32+ random chars): "
    ) else (
        echo [OK] SECRET_KEY generated automatically.
    )

    REM Update .env file using PowerShell for reliable text replacement
    powershell -Command "(gc .env) -replace 'GROQ_API_KEY=your_groq_api_key_here', 'GROQ_API_KEY=!GROQ_KEY!' | Out-File -encoding utf8 .env"
    if not "!GEMINI_KEY!"=="" (
        powershell -Command "(gc .env) -replace 'GEMINI_API_KEY=your_gemini_api_key_here', 'GEMINI_API_KEY=!GEMINI_KEY!' | Out-File -encoding utf8 .env"
    )
    powershell -Command "(gc .env) -replace 'SECRET_KEY=change_me_to_a_long_random_string', 'SECRET_KEY=!SECRET_KEY!' | Out-File -encoding utf8 .env"

    echo.
    echo [!] SECURITY REMINDER:
    echo     - Do NOT commit your .env file to git — it is already gitignored.
    echo     - Do NOT set ALLOW_DEBUG_RESPONSES=true in production.
    echo     - Set POSTGRES_PASSWORD in .env before deploying to a server.
    echo.
    echo [OK] Configured .env successfully.
)

REM 4. Build and Start
echo.
echo [4/4] Starting the AI engine. This may take 5-10 minutes for the first time.
echo.
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo.
    echo [!] ERROR: Something went wrong during the build.
    echo Check if Docker Desktop is open and has enough memory (4 GB+ recommended).
) else (
    echo.
    echo ====================================================
    echo    SUCCESS! Amadeus AI is now running.
    echo ====================================================
    echo.
    echo    API Docs:      http://localhost:8000/docs
    echo    Health check:  http://localhost:8000/health
    echo.
    echo    To build the workspace search index (optional):
    echo    python scripts/index_workspace.py
    echo.
)

pause

@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo    Amadeus AI - First Time Setup (Office Users)
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
    echo [1/3] Setting up your configuration file...
    if exist .env.example (
        copy .env.example .env >nul
    ) else (
        echo [!] ERROR: .env.example not found! 
        pause
        exit /b 1
    )
    
    echo.
    echo [2/3] Please enter your AI API keys (you can get these for free online):
    set /p GROQ_KEY="   - Enter your GROQ_API_KEY: "
    set /p GEMINI_KEY="   - Enter your GEMINI_API_KEY (optional, press Enter to skip): "

    REM Update .env file using PowerShell for reliable text replacement
    powershell -Command "(gc .env) -replace 'GROQ_API_KEY=your_groq_api_key_here', 'GROQ_API_KEY=!GROQ_KEY!' | Out-File -encoding utf8 .env"
    if not "!GEMINI_KEY!"=="" (
        powershell -Command "(gc .env) -replace 'GEMINI_API_KEY=your_gemini_api_key_here', 'GEMINI_API_KEY=!GEMINI_KEY!' | Out-File -encoding utf8 .env"
    )
    echo [SUCCESS] Configured .env with your keys.
)

REM 3. Build and Start
echo.
echo [3/3] Starting the AI engine. This may take 5-10 minutes for the first time.
echo.
docker-compose up -d --build

if %errorlevel% neq 0 (
    echo.
    echo [!] ERROR: Something went wrong during the build. 
    echo Check if Docker Desktop is open and has enough memory.
) else (
    echo.
    echo ====================================================
    echo    SUCCESS! Amadeus AI is now running.
    echo ====================================================
    echo.
    echo You can use the assistant by opening this address in your browser:
    echo http://localhost:8000/docs
    echo.
)

pause

@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo    Amadeus AI Background Daemon Launcher
echo ====================================================
echo.

set "DIST_EXE=dist\amadeus\amadeus.exe"

REM 1. Check if the executable exists
if not exist "%DIST_EXE%" (
    echo [ERROR] Could not find the compiled executable at %DIST_EXE%.
    echo Please run 'python scripts\build_windows.py' first.
    pause
    exit /b 1
)

REM 2. Check if .env exists
if not exist ".env" (
    echo [WARNING] No .env file found!
    
    if exist ".env.example" (
        echo Copying .env.example to .env...
        copy .env.example .env >nul
        echo Opening .env for configuration...
        start notepad.exe .env
        echo.
        echo Please fill in the required API keys in the opened file.
        echo Save and close Notepad, then press any key here to continue...
        pause >nul
    ) else (
        echo [ERROR] Neither .env nor .env.example was found.
        echo Please obtain the environment file structure.
        pause
        exit /b 1
    )
)

REM 3. Read .env file to verify critical values 
set "HAS_SECRET=0"
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if "%%A"=="SECRET_KEY" (
        set "VAL=%%B"
        REM Remove leading spaces and quotes
        if not "!VAL!"=="" if not "!VAL!"=="your_secret_key_here" set "HAS_SECRET=1"
    )
)

if "!HAS_SECRET!"=="0" (
    echo [WARNING] SECRET_KEY appears to be missing or default in .env!
    echo Generating a temporary secret just to allow startup...
    echo You should configure this properly for production.
    echo.
)

REM 4. Launch the binary
echo [OK] Pre-flight checks passed. Launching Amadeus daemon...
echo.
echo Logs are being written to data\logs\amadeus.log
echo To stop the daemon, use Task Manager or run 'taskkill /IM amadeus.exe /F'
echo.

start "" "%DIST_EXE%"

echo Amadeus started in the background. You may close this window.
timeout /t 5 >nul
exit /b 0

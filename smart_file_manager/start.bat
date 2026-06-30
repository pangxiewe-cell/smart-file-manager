@echo off
setlocal enabledelayedexpansion

echo.
echo ================================================
echo   Smart File Manager - Quick Start
echo ================================================
echo.

cd /d "%~dp0"

echo [CHECK] Python virtual environment...
if not exist ".venv\Scripts\activate.bat" (
    echo     First run: creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo     [ERROR] Failed to create venv. Make sure Python is installed.
        pause
        exit /b 1
    )
    echo     Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
    echo.
    echo     [DONE] Dependencies installed.
    echo.
) else (
    echo     Virtual environment found, skipping install.
)

echo.
echo [CHECK] config.py...
if not exist "config.py" (
    echo     config.py not found!
    echo     Copying from template...
    copy config_example.py config.py >nul
    echo.
    echo     Please open config.py and fill in your API Key.
    echo     Opening config.py in Notepad now...
    notepad config.py
    echo.
    echo     Press any key after saving config.py to continue...
    pause
)

echo.
echo [START] Launching Smart File Manager...
echo     URL: http://localhost:7860
echo     Press Ctrl+C to stop.
echo.
.venv\Scripts\python main.py

pause

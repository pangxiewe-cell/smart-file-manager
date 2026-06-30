@echo off
setlocal enabledelayedexpansion

set SRC=C:\Users\MECHREVO\WorkBuddy\2026-06-17-16-23-40
set DST=D:\smart-file-manager

echo.
echo ================================================
echo   Smart File Manager - Migrate to D Drive
echo ================================================
echo.

echo [1/5] Creating target directory...
if exist "%DST%" (
    echo     Directory already exists, skipping.
) else (
    mkdir "%DST%"
    echo     Created: %DST%
)

echo.
echo [2/5] Cloning Git repo with full history...
git clone "%SRC%" "%DST%"
if %errorlevel% neq 0 (
    echo     [WARN] git clone failed, falling back to xcopy...
    xcopy /E /I /H /Y "%SRC%\smart_file_manager" "%DST%\smart_file_manager\"
    xcopy /E /I /H /Y "%SRC%\.codebuddy" "%DST%\.codebuddy\" 2>nul
    copy /Y "%SRC%\smart_file_manager_steps.md" "%DST%\" 2>nul
    copy /Y "%SRC%\.gitignore" "%DST%\" 2>nul
    echo     Files copied manually.
)

echo.
echo [3/5] Setting remote origin to GitHub SSH...
cd /d "%DST%"
git remote set-url origin git@github.com:pangxiewe-cell/smart-file-manager.git
echo     Remote set to: git@github.com:pangxiewe-cell/smart-file-manager.git

echo.
echo [4/5] Copying extra docs...
if exist "%SRC%\PPT.md" (
    copy /Y "%SRC%\PPT.md" "%DST%\"
)
for %%f in ("%SRC%\*.md") do (
    copy /Y "%%f" "%DST%\" >nul
    echo     Copied: %%~nxf
)

echo.
echo [5/5] Verifying...
echo.
echo   Target directory contents:
dir "%DST%" /B
echo.
echo   Git log:
cd /d "%DST%"
git log --oneline -5
echo.
echo   Git remote:
git remote -v

echo.
echo ================================================
echo   Migration complete!
echo   New path: %DST%
echo.
echo   Next steps:
echo   1. cd D:\smart-file-manager\smart_file_manager
echo   2. python -m venv .venv
echo   3. .venv\Scripts\activate
echo   4. pip install -r requirements.txt
echo   5. copy config_example.py config.py
echo   6. Edit config.py to fill in your API Key
echo   7. python main.py
echo ================================================
echo.
pause

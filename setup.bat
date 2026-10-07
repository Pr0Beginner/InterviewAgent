@echo off
setlocal

cd /d "%~dp0"

echo [INFO] Preparing Interview Assistant environment...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_env.ps1"
set "SETUP_EXIT_CODE=%ERRORLEVEL%"

if not "%SETUP_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Environment setup failed. Review the message above and retry.
    pause
    exit /b %SETUP_EXIT_CODE%
)

echo.
echo [OK] Environment is ready. Run start.bat to launch Interview Assistant.
pause
endlocal

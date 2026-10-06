@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project virtual environment was not found.
    echo Run: python -m venv .venv
    echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_app.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"

if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Interview Assistant failed to start.
    pause
    exit /b %APP_EXIT_CODE%
)

endlocal

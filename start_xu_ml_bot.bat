@echo off
setlocal

echo.
echo === Flipped XAUUSD ML bot ===

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] py.exe not found. Install Python and ensure py.exe is on PATH.
    exit /b 1
)

echo Bootstrapping environment...
py -3 bootstrap_env.py --profile xu-ml
if errorlevel 1 (
    echo [ERROR] Failed to bootstrap Python environment.
    exit /b 1
)

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Could not find %PYTHON_EXE%.
    exit /b 1
)

call .venv\Scripts\activate
if errorlevel 1 (
    echo [ERROR] Failed to activate .venv
    exit /b 1
)

echo Launching run_xu_ml_bot.py (Ctrl+C to stop) ...
"%PYTHON_EXE%" run_xu_ml_bot.py %*

endlocal

@echo off
REM ============================================================
REM LLM-Keyring startup script for Windows
REM ============================================================

setlocal
title LLM-Keyring

REM ---- 1. Locate Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python 3.9+ is not installed or not on PATH.
    echo.
    echo Install Python from: https://www.python.org/downloads/
    echo   IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM ---- 2. Check Python version ----
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Detected Python %PYVER%

REM ---- 3. Install dependencies if missing ----
python -c "import fastapi" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Installing dependencies...
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo Try manually: python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM ---- 4. Launch ----
echo.
echo Starting LLM-Keyring...
echo.
python main.py

pause
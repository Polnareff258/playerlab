@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  PlayerLab V1.3.3 - one-click launcher (Windows)
REM  1. finds a Python with demoparser2
REM  2. starts the local UI+API server
REM  3. opens the browser automatically
REM ============================================================
cd /d "%~dp0"

set "PORT=8123"
if not "%1"=="" set "PORT=%1"

REM ---- 1. locate python (python3 preferred, fall back to python) ----
set "PY="
for %%P in (python3 python) do (
    where %%P >nul 2>nul
    if !errorlevel!==0 (
        set "PY=%%P"
        goto :found
    )
)
echo [PlayerLab] ERROR: no python3/python found on PATH.
echo           Install Python 3.11+ from https://www.python.org/downloads/
pause
exit /b 1

:found
echo [PlayerLab] using: %PY%

REM ---- 2. verify core dependency (demoparser2) ----
%PY% -c "import demoparser2" >nul 2>nul
if errorlevel 1 (
    echo [PlayerLab] missing demoparser2 - installing core deps...
    %PY% -m pip install demoparser2==0.42.0 pandas
)

REM ---- 3. ensure data directories ----
if not exist "data" mkdir "data"
if not exist "backtest" mkdir "backtest"

REM ---- 4. start server + open browser ----
echo [PlayerLab] starting UI+API on http://127.0.0.1:%PORT%  (Ctrl+C to stop)
pushd core
%PY% -m playerlab.cli api --host 127.0.0.1 --port %PORT% --open
popd

pause

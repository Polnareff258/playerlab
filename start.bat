@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  PlayerLab - one-click launcher (Windows)
REM  1. finds a Python (3.11+)
REM  2. installs missing core deps (demoparser2, pandas) and optional
REM     geometry deps (awpy)
REM  3. creates missing data dirs, initializes the DB if absent
REM  4. auto-downloads missing map geometry assets (.nav + .tri)
REM  5. starts the local UI+API server and opens the browser
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

REM ---- 2. ensure data directories ----
if not exist "data" mkdir "data"
if not exist "backtest" mkdir "backtest"
if not exist "data\maps" mkdir "data\maps"
if not exist "data\analyses" mkdir "data\analyses"

REM ---- 3. core dependency: demoparser2 + pandas ----
%PY% -c "import demoparser2, pandas" >nul 2>nul
if errorlevel 1 (
    echo [PlayerLab] missing core deps: demoparser2 / pandas - installing...
    %PY% -m pip install demoparser2==0.42.0 pandas
    if errorlevel 1 (
        echo [PlayerLab] ERROR: pip install failed. Check network / proxy.
        pause
        exit /b 1
    )
)

REM ---- 4. DB initialization (creates schema on first run) ----
if not exist "data\playerlab.sqlite" (
    echo [PlayerLab] no database found - initializing...
    pushd core
    %PY% -m playerlab.cli list >nul 2>nul
    popd
)

REM ---- 5. optional geometry deps: awpy (for LOS/nav analysis) ----
%PY% -c "import awpy" >nul 2>nul
if errorlevel 1 (
    echo [PlayerLab] awpy not found - installing optional geometry backend...
    %PY% -m pip install awpy
)

REM ---- 6. map geometry assets (.nav + .tri) ----
REM      auto-download from the awpy mirror if missing
pushd core
%PY% -c "import playerlab.cli" >nul 2>nul
%PY% ..\scripts\setup_geometry_assets.py --check >nul 2>nul
popd
set "MAPS_READY=0"
if exist "data\maps\de_dust2.nav" if exist "data\maps\de_dust2.tri" set "MAPS_READY=1"
if "!MAPS_READY!"=="0" (
    echo [PlayerLab] map geometry assets missing - downloading from awpy mirror...
    pushd core
    %PY% ..\scripts\setup_geometry_assets.py --auto
    popd
)

REM ---- 7. start server + open browser ----
echo [PlayerLab] starting UI+API on http://127.0.0.1:%PORT%  (Ctrl+C to stop)
pushd core
%PY% -m playerlab.cli api --host 127.0.0.1 --port %PORT% --open
popd

pause

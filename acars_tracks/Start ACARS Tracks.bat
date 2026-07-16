@echo off
REM ============================================================================
REM  ACARS Tracks - one-click launcher for Windows
REM  Double-click this file to start the map. The first run sets up a small
REM  private Python environment (needs internet); later runs start quickly.
REM ============================================================================
setlocal
cd /d "%~dp0"
title ACARS Tracks

echo.
echo   ACARS flight-track + sounding map
echo   ---------------------------------
echo.

REM --- find Python -----------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo   Python was not found on this PC.
    echo.
    echo   Please install Python 3 from:  https://www.python.org/downloads/
    echo   IMPORTANT: on the first install screen, tick
    echo       "Add python.exe to PATH"
    echo   then run this file again.
    echo.
    pause
    exit /b 1
)

REM --- create a private environment the first time ---------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   Setting up for first use ^(this happens only once^)...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo   Could not create the Python environment. See any message above.
        pause
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

REM --- install packages the first time --------------------------------------
if not exist ".venv\.deps_ok" (
    echo   Installing required packages ^(first run only, needs internet^)...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   Package install failed. Check your internet connection and retry.
        pause
        exit /b 1
    )
    REM optional nicer sounding renderer - best effort, never blocks startup
    echo   Trying optional sounding renderer ^(pyMeteo^)...
    "%VENV_PY%" -m pip install -r requirements-optional.txt
    echo ok> ".venv\.deps_ok"
)

REM --- run -------------------------------------------------------------------
echo.
echo   Starting... your web browser will open in a moment.
echo   Keep THIS window open while you use the map. Close it to stop.
echo.
"%VENV_PY%" server.py %*

echo.
echo   The map server has stopped.
pause
endlocal

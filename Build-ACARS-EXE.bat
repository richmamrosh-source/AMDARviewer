@echo off
REM ============================================================================
REM  Build a standalone ACARS Tracks app  (Windows)
REM
REM  Run this ONCE on a Windows PC that has Python. It produces a shareable zip:
REM       dist\ACARS-Tracks.zip
REM  Anyone can unzip that on a Windows PC (no Python needed) and double-click
REM  ACARS-Tracks\ACARS-Tracks.exe to run it.
REM
REM  Why a FOLDER/zip instead of one .exe?  A single-file .exe unpacks itself
REM  every time it runs, and antivirus tools (and Google Drive) often mistake
REM  that behavior for malware and show a scary "infected" warning. The
REM  one-folder build below does NOT self-unpack, so it is far less likely to be
REM  falsely flagged. See DISTRIBUTING.md for the full story and what to tell the
REM  people you share it with.
REM
REM  The build takes several minutes; the unzipped app is large (a few hundred MB)
REM  because it bundles Python, numpy, matplotlib and the NetCDF libraries.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Build ACARS Tracks app

echo.
echo   Building a standalone ACARS-Tracks app
echo   ======================================
echo.

REM --- find Python -----------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
    echo   Python was not found. Install it from https://www.python.org/downloads/
    echo   ^(tick "Add python.exe to PATH"^) and run this again.
    pause
    exit /b 1
)

REM --- environment with app deps + build tools -------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   Creating build environment...
    %PY% -m venv .venv
    if errorlevel 1 ( echo   Could not create environment. & pause & exit /b 1 )
)
set "VENV_PY=.venv\Scripts\python.exe"

echo   Installing packages (needs internet, first time may take a while)...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo   Package install failed. & pause & exit /b 1 )
REM optional nicer renderer - bundled into the app only if it installs
"%VENV_PY%" -m pip install -r requirements-optional.txt
REM use the LATEST PyInstaller - newer bootloaders trip fewer false positives.
REM If an antivirus is still stubborn, try pinning a known-cleaner version
REM instead: replace the next line with   pip install pyinstaller==5.13.2
"%VENV_PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 ( echo   Could not install PyInstaller. & pause & exit /b 1 )

REM --- fetch + verify Leaflet locally so the built app needs no internet for it -
echo Vendoring the map library (Leaflet) locally...
"%VENV_PY%" vendor_leaflet.py

REM --- bundle pyMeteo only if it is actually installed ------------------------
set "PM_FLAGS="
"%VENV_PY%" -c "import pymeteo" >nul 2>nul && set "PM_FLAGS=--collect-all pymeteo --collect-all h5py"


echo.
echo   Running PyInstaller... (this is the slow part)
echo.
REM  --onedir  : one-folder build (does NOT self-unpack -> far fewer AV flags)
REM  --noupx   : never UPX-compress (UPX packing is a top false-positive cause)
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onedir --noupx --name ACARS-Tracks ^
    --add-data "static;static" ^
    --collect-all matplotlib ^
    --collect-all netCDF4 ^
    --collect-submodules cftime ^
    --collect-data certifi ^
    %PM_FLAGS% ^
    server.py

if errorlevel 1 (
    echo.
    echo   The build failed. Scroll up to see the error.
    pause
    exit /b 1
)

REM --- zip the folder so it is easy (and safer) to share ---------------------
echo.
echo   Packaging into a shareable zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Test-Path 'dist\ACARS-Tracks.zip') { Remove-Item 'dist\ACARS-Tracks.zip' -Force }; Compress-Archive -Path 'dist\ACARS-Tracks' -DestinationPath 'dist\ACARS-Tracks.zip'"

echo.
echo   ============================================================
echo   Done!
echo.
echo   To RUN it yourself:
echo       dist\ACARS-Tracks\ACARS-Tracks.exe   (double-click)
echo.
echo   To SHARE it with others:
echo       send  dist\ACARS-Tracks.zip
echo       they unzip it, open the ACARS-Tracks folder, and
echo       double-click ACARS-Tracks.exe
echo.
echo   If their antivirus or Google Drive still warns, see the
echo   "Sharing" section in DISTRIBUTING.md - it is a known false
echo   alarm for bundled Python apps and explains what to do.
echo   ============================================================
echo.
pause
endlocal

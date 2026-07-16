@echo off
REM ============================================================================
REM  Build a standalone ACARS Tracks app with NUITKA  (Windows)
REM
REM  Nuitka *compiles* your Python into a real native program instead of just
REM  bundling it. Antivirus engines treat the result like any normal app, so it
REM  is the best free way to stop the "this file may be a virus" false alarms.
REM
REM  Use this if the regular PyInstaller build (Build-ACARS-EXE.bat) keeps getting
REM  flagged on people's machines. It produces the same kind of shareable zip:
REM       build_nuitka\ACARS-Tracks.zip
REM  Recipients unzip it, open the ACARS-Tracks folder, and double-click
REM  ACARS-Tracks.exe.
REM
REM  HEADS UP:
REM   * The FIRST build is slow (it actually compiles - can take 10-30 minutes).
REM   * Nuitka needs a C compiler. With the flag below it will offer to download
REM     a small one (MinGW) automatically the first time - just let it.
REM   * This app uses numpy/matplotlib/netCDF4, which are the trickier libraries
REM     for any packager. If the build stops with an error, copy the last ~20
REM     lines and send them over - it is usually a one-line flag fix.
REM ============================================================================
setlocal
cd /d "%~dp0"
title Build ACARS Tracks (Nuitka)

echo.
echo   Building ACARS-Tracks with Nuitka (compiled, AV-friendly)
echo   =========================================================
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

REM --- reuse / create the build environment -----------------------------------
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
"%VENV_PY%" -m pip install -r requirements-optional.txt
"%VENV_PY%" -m pip install --upgrade nuitka
if errorlevel 1 ( echo   Could not install Nuitka. & pause & exit /b 1 )

REM fetch + verify Leaflet locally so the built app needs no internet for it
echo Vendoring the map library (Leaflet) locally...
"%VENV_PY%" vendor_leaflet.py

REM --- bundle pyMeteo only if it is actually installed ------------------------
set "PM_FLAGS="
"%VENV_PY%" -c "import pymeteo" >nul 2>nul && set "PM_FLAGS=--include-package=pymeteo --include-package-data=pymeteo --include-package=h5py"


echo.
echo   Compiling with Nuitka... (this is the slow part - be patient)
echo.
"%VENV_PY%" -m nuitka ^
    --standalone ^
    --assume-yes-for-downloads ^
    --output-dir=build_nuitka ^
    --output-filename=ACARS-Tracks.exe ^
    --company-name="ACARS Tracks" ^
    --product-name="ACARS Tracks" ^
    --file-version=1.0.0 ^
    --include-data-dir=static=static ^
    --include-package=netCDF4 ^
    --include-package-data=netCDF4 ^
    --include-package=cftime ^
    --include-package-data=certifi ^
    --include-package-data=matplotlib ^
    --nofollow-import-to=tkinter ^
    --nofollow-import-to=PyQt5 ^
    --nofollow-import-to=PyQt6 ^
    --nofollow-import-to=PySide2 ^
    --nofollow-import-to=PySide6 ^
    --nofollow-import-to=wx ^
    %PM_FLAGS% ^
    server.py

if errorlevel 1 (
    echo.
    echo   The build failed. Scroll up, copy the last ~20 lines, and send them
    echo   over - Nuitka errors on these libraries are usually a quick flag fix.
    pause
    exit /b 1
)

REM --- tidy the output folder name + zip it for sharing ----------------------
echo.
echo   Packaging into a shareable zip...
if exist "build_nuitka\ACARS-Tracks" rmdir /s /q "build_nuitka\ACARS-Tracks"
move "build_nuitka\server.dist" "build_nuitka\ACARS-Tracks" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Test-Path 'build_nuitka\ACARS-Tracks.zip') { Remove-Item 'build_nuitka\ACARS-Tracks.zip' -Force }; Compress-Archive -Path 'build_nuitka\ACARS-Tracks' -DestinationPath 'build_nuitka\ACARS-Tracks.zip'"

echo.
echo   ============================================================
echo   Done!
echo.
echo   To RUN it yourself:
echo       build_nuitka\ACARS-Tracks\ACARS-Tracks.exe   (double-click)
echo.
echo   To SHARE it (e.g. upload to itch.io):
echo       build_nuitka\ACARS-Tracks.zip
echo.
echo   See DISTRIBUTING.md for hosting + antivirus notes.
echo   ============================================================
echo.
pause
endlocal

@echo off
REM ============================================================================
REM  ACARS Tracks - OFFLINE DEMO launcher
REM  Same as the normal launcher but uses built-in synthetic data, so it does
REM  not need the live weather feed. (An internet connection is still needed
REM  for the map's background tiles.)
REM ============================================================================
setlocal
cd /d "%~dp0"
call "Start ACARS Tracks.bat" --demo
endlocal

@echo off
rem ============================================================
rem  Laomushi TTS - desktop GUI launcher
rem
rem  run_gui.bat            start the GUI (no console window)
rem  run_gui.bat --console   keep a console window for troubleshooting
rem  setup.bat              choose the GPT-SoVITS folder (once)
rem
rem  The GPT-SoVITS folder comes from config.local.txt (one line),
rem  which setup.bat or the GUI's "Settings" button writes.
rem ============================================================
title Laomushi TTS GUI
cd /d "%~dp0"
setlocal

set "GSV_HOME="
call :read_config
if not defined GSV_HOME if defined LAOMUSHI_GSV_HOME set "GSV_HOME=%LAOMUSHI_GSV_HOME%"

if not exist "%GSV_HOME%\runtime\python.exe" (
    echo [SETUP] GPT-SoVITS folder is not configured yet.
    call "%~dp0setup.bat"
    set "GSV_HOME="
    call :read_config
)

if not exist "%GSV_HOME%\runtime\python.exe" (
    echo [ERROR] No usable GPT-SoVITS folder.
    echo         Expected: %%GSV_HOME%%\runtime\python.exe
    echo         Run setup.bat, or edit config.local.txt by hand.
    pause
    exit /b 1
)

set "TTS_DEVICE=cuda"

if /i "%~1"=="--console" (
    "%GSV_HOME%\runtime\python.exe" "%~dp0app.py" %2 %3 %4 %5 %6
    echo.
    echo [GUI exited] press any key to close...
    pause >nul
) else (
    start "Laomushi TTS" "%GSV_HOME%\runtime\pythonw.exe" "%~dp0app.py" %*
)
exit /b 0

:read_config
if not exist "%~dp0config.local.txt" exit /b 0
for /f "usebackq delims=" %%i in ("%~dp0config.local.txt") do (
    if not defined GSV_HOME set "GSV_HOME=%%i"
)
exit /b 0

@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8:backslashreplace"
set "COC_LDPLAYER_DIR=E:\LDPlayer\LDPlayer14"
set "PYTHON=%~dp0.venv311\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Python environment not found: "%PYTHON%"
    echo Run the project setup first, then retry.
    pause
    exit /b 1
)

fltmc >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator permission for LDPlayer control...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYTHON%' -ArgumentList '-u launcher_local.py' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

"%PYTHON%" -u launcher_local.py
if errorlevel 1 pause

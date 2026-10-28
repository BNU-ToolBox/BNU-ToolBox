@echo off
setlocal
cd /d "%~dp0"

if exist "runtime\pythonw.exe" (
    start "" "runtime\pythonw.exe" "app\main.py" %*
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app\main.py" %*
) else (
    echo BNU-ToolBox runtime not found.
    exit /b 1
)

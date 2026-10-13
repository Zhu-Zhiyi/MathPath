@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo MathPath: virtual environment not found. See README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -B -X utf8 launch.py
if errorlevel 1 (
    echo MathPath could not start. If port 8000 is already used, stop the earlier server first.
    pause
)

@echo off
cd /d "%~dp0"
echo ========================================
echo   Timetable System - Starting...
echo ========================================
echo.

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found! Please install Python from python.org
    pause
    exit /b 1
)

echo [OK] Python found: 
python --version

REM Install Flask if missing
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Installing Flask...
    pip install flask
) else (
    echo [OK] Flask is installed
)

REM Add firewall rule (admin not required for this)
echo.
echo Starting server...
echo Open http://127.0.0.1:5000 in your browser
echo Press Ctrl+C to stop
echo ========================================
echo.
python app.py
pause

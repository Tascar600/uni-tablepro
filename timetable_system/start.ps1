Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Timetable System Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Set-Location -LiteralPath $PSScriptRoot

# Check Python
try {
    $v = python --version
    Write-Host "[OK] $v" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    Write-Host "Install from: https://www.python.org/downloads/"
    Read-Host "Press Enter to exit"
    exit
}

# Check Flask
try {
    python -c "import flask" 2>$null
    Write-Host "[OK] Flask is installed" -ForegroundColor Green
} catch {
    Write-Host "[INFO] Installing Flask..." -ForegroundColor Yellow
    pip install flask
}

# Add firewall rule silently
netsh advfirewall firewall add rule name="Timetable System" dir=in action=allow protocol=TCP localport=5000 2>$null

Write-Host "`n[STARTING] Server on http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop`n" -ForegroundColor Gray

python app.py

Read-Host "`nServer stopped. Press Enter to exit"

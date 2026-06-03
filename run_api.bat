@echo off
REM ============================================================
REM ScanStruct API Server Launcher
REM ============================================================
cd /d "%~dp0"

echo ========================================
echo  ScanStruct API Server
echo ========================================

if not exist ".env" (
    copy .env.example .env > nul
    echo Created .env from .env.example
)

.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8900 --log-level info

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] API server exited with code %ERRORLEVEL%
)

pause

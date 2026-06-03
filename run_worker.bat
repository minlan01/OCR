@echo off
REM ============================================================
REM ScanStruct Celery Worker Launcher
REM ============================================================
cd /d "%~dp0"

echo ========================================
echo  ScanStruct Celery Worker
echo ========================================

.venv\Scripts\python.exe -m celery -A worker.celery_app worker --loglevel=info --pool=threads --concurrency=2 -Q scanstruct

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Celery worker exited with code %ERRORLEVEL%
)

pause

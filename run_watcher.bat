@echo off
REM ============================================================
REM ScanStruct File Watcher Launcher
REM ============================================================
cd /d "%~dp0"

echo ========================================
echo  ScanStruct File Watcher
echo ========================================

if not exist "scan_input" mkdir scan_input
if not exist "scan_error" mkdir scan_error
if not exist "scan_archive" mkdir scan_archive

.venv\Scripts\python.exe -m services.scan_in.watcher

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] File watcher exited with code %ERRORLEVEL%
)

pause

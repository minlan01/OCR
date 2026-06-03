@echo off
REM ============================================================
REM ScanStruct Docker 一键停止
REM ============================================================
cd /d "%~dp0"

echo ========================================
echo  ScanStruct Docker 停止
echo ========================================

set "DOCKER_PATH=D:\Docker\resources\bin;C:\Program Files\Docker\cli-plugins"
set "PATH=%DOCKER_PATH%;%PATH%"

docker compose --env-file .env.docker down

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Docker 停止失败
    pause
    exit /b 1
)

echo.
echo ScanStruct 已停止。
pause

@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Starting local backend and frontend...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backend\tools\start-local.ps1" %*
if errorlevel 1 (
  echo Startup failed. See the message above and data\logs\startup logs.
  pause
  exit /b 1
)
echo Services are ready. You can close this window.
exit /b 0

@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-pixiv-app-api-first-sample.ps1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo One-page App API sample failed with exit code %exit_code%.
pause
exit /b %exit_code%


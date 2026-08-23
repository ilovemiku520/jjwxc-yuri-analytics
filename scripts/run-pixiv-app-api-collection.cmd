@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-pixiv-app-api-collection.ps1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Pixiv App API collection failed with exit code %exit_code%.
pause
exit /b %exit_code%

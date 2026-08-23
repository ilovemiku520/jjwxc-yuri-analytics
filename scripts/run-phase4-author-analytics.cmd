@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-phase4-author-analytics.ps1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Phase 4 author analytics failed with exit code %exit_code%.
exit /b %exit_code%

@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-publication-review.ps1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo External-publication review failed with exit code %exit_code%.
exit /b %exit_code%

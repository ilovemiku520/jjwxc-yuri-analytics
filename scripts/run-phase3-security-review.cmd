@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-phase3-security-review.ps1" %*
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Phase 3 security review failed with exit code %exit_code%.
exit /b %exit_code%

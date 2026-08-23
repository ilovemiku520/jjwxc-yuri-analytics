@echo off
setlocal
set "PYURI_ENABLE_NETWORK=false"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-live-one-request-preflight-smoke.ps1"
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" echo Live one-request offline preflight failed with exit code %exitCode%.
exit /b %exitCode%

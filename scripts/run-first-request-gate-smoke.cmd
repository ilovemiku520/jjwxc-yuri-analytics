@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-first-request-gate-smoke.ps1"
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" echo First-request gate smoke test failed with exit code %exitCode%.
exit /b %exitCode%

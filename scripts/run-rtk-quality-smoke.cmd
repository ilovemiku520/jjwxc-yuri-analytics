@echo off
setlocal
set "PYURI_ENABLE_NETWORK=false"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-rtk-quality-smoke.ps1"
exit /b %ERRORLEVEL%

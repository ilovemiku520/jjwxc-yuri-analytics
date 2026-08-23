@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-session-preflight-smoke.ps1"
exit /b %errorlevel%

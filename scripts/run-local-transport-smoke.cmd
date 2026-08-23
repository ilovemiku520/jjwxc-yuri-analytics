@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local-transport-smoke.ps1"
exit /b %errorlevel%

@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-first-sample-dry-run-smoke.ps1"
exit /b %errorlevel%

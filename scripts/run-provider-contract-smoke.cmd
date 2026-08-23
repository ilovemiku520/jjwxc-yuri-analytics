@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-provider-contract-smoke.ps1"
exit /b %errorlevel%

@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-parallel-modules-smoke.ps1"
exit /b %errorlevel%

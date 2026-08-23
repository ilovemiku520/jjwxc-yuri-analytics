@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-concurrent-pipeline-smoke.ps1"
exit /b %errorlevel%

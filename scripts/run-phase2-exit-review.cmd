@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-phase2-exit-review.ps1" %*
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" echo Phase 2 exit review failed with exit code %exitCode%.
exit /b %exitCode%

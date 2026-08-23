@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-jjwxc-public-probe.ps1" %*
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo JJWXC public metadata probe failed with exit code %exit_code%.
exit /b %exit_code%

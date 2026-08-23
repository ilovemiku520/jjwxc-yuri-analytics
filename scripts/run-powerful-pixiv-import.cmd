@echo off
setlocal
if "%~1"=="" (
  echo Drag one Powerful Pixiv Downloader JSON export onto this file.
  echo Do not provide a password, Cookie, token, browser profile, image, or novel body.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-powerful-pixiv-import.ps1" -ExportPath "%~1"
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" echo Offline import did not become candidate-ready.
pause
exit /b %exitCode%

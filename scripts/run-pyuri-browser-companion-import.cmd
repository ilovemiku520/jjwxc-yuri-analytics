@echo off
setlocal
if "%~1"=="" (
  echo Drag one JSON exported by the Yuri Cultural Index browser companion onto this file.
  echo Do not provide a Pixiv password, Cookie, token, browser profile, or image file.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-pyuri-browser-companion-import.ps1" -ExportPath "%~1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Browser companion import failed with exit code %exit_code%.
pause
exit /b %exit_code%

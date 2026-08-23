@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-pixiv-browser.ps1"
if errorlevel 1 (
  echo.
  echo Pixiv browser startup failed.
  pause
)
endlocal

@echo off
setlocal
if "%~1"=="" (
  echo Drag a folder containing Yuri Cultural Index browser-companion JSON files onto this file.
  echo The batch is limited to 25 files and 10 MB total.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-pyuri-browser-companion-batch-import.ps1" -ExportDirectory "%~1"
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Browser companion batch import failed with exit code %exit_code%.
pause
exit /b %exit_code%

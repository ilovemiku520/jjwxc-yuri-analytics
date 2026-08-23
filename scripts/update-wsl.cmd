@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-wsl.ps1"
set "setup_exit=%errorlevel%"
echo.
if not "%setup_exit%"=="0" (
  echo WSL update failed with exit code %setup_exit%.
) else (
  echo WSL update completed. Close and reopen Docker Desktop.
)
pause
exit /b %setup_exit%

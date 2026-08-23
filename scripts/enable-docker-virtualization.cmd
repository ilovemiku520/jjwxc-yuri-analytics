@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-docker-virtualization.ps1"
set "setup_exit=%errorlevel%"
echo.
if not "%setup_exit%"=="0" (
  echo Docker virtualization setup failed with exit code %setup_exit%.
) else (
  echo Docker virtualization setup completed. Restart Windows before retrying Docker Desktop.
)
pause
exit /b %setup_exit%

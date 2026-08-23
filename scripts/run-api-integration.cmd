@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-api-integration.ps1"
set "integration_exit=%errorlevel%"
echo.
if not "%integration_exit%"=="0" (
  echo API container integration failed with exit code %integration_exit%.
) else (
  echo API container integration completed successfully.
)
pause
exit /b %integration_exit%

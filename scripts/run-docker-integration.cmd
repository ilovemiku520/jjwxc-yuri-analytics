@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-docker-integration.ps1"
set "integration_exit=%errorlevel%"
echo.
if not "%integration_exit%"=="0" (
  echo Docker/PostgreSQL integration failed with exit code %integration_exit%.
) else (
  echo Docker/PostgreSQL offline integration completed successfully.
)
pause
exit /b %integration_exit%

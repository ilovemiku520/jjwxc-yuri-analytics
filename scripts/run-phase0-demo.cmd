@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-phase0-demo.ps1"
set "demo_exit=%errorlevel%"
echo.
if not "%demo_exit%"=="0" (
  echo Phase 0 demonstration failed with exit code %demo_exit%.
) else (
  echo Phase 0 demonstration completed successfully.
)
pause
exit /b %demo_exit%

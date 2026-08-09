@echo off
rem If FPS shows "--" forever, a leftover ETW trace session is holding the
rem present providers. This clears them. Takes a second, changes nothing else.
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Clearing leftover PresentMon trace sessions...
logman stop FPSMonitorDiag -ets 2>nul
logman stop FPSMonitorLive -ets 2>nul
echo.
echo Remaining sessions with our names (should be none):
logman query -ets | findstr /I "FPSMonitor"
echo.
echo Done. Start FPS Monitor again.
pause

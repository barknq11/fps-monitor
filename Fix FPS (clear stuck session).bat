@echo off
rem Run this if FPS shows "--" forever, or a rebuild says a file is in use.
rem Two things can be left behind when the app is killed rather than closed:
rem   * an orphaned PresentMon.exe still holding its ETW trace session
rem   * the trace session itself
rem Both are cleared here. Nothing else is changed.
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Stopping orphaned PresentMon processes...
taskkill /IM PresentMon.exe /F 2>nul
if %errorlevel% equ 0 (echo   stopped) else (echo   none were running)

echo.
echo Clearing leftover trace sessions...
logman stop FPSMonitorDiag -ets 2>nul
logman stop FPSMonitorLive -ets 2>nul

echo.
echo Remaining sessions with our names (should be none):
logman query -ets | findstr /I "FPSMonitor"

echo.
echo Done. Start FPS Monitor again.
pause

@echo off
rem One-shot diagnostic. Asks for Administrator, records how PresentMon
rem delivers its output for 20 seconds, then writes logs\presentmon_diag.txt
rem Nothing is installed and nothing is left running.
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo   Make sure a game is running and rendering BEFORE this starts.
echo   Capturing for 20 seconds...
echo.
python "%~dp0tools\capture_presentmon.py"
echo.
pause

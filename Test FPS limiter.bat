@echo off
rem Verifies the RTSS frame limiter end to end, elevated.
rem Only writes to a throwaway profile name, then removes it.
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

python "%~dp0tools\selftest_limiter.py"

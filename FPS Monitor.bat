@echo off
rem Launches FPS Monitor with no console window.
rem run.py asks for Administrator so PresentMon (FPS) and CPU temperature work.
cd /d "%~dp0"
start "" pythonw.exe "%~dp0run.py"

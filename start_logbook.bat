@echo off
rem Starts the Experiment logbook on port 8766 and opens it in the browser. Close this window to stop it.
cd /d "%~dp0"
set PYTHONUTF8=1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8766 " ^| findstr LISTENING') do (
  echo Stopping the previous logbook instance (process %%p^) ...
  taskkill /PID %%p /F >nul 2>&1
)
uv run shiny run logbook/app.py --port 8766 --launch-browser
pause

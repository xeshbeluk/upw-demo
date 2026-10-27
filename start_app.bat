@echo off
rem Starts the dashboard on port 8765 and opens it in the browser. Close this window to stop it.
rem If an earlier copy of the app is still running on that port, it is stopped first.
cd /d "%~dp0"
set PYTHONUTF8=1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765 " ^| findstr LISTENING') do (
  echo Stopping the previous app instance (process %%p^) ...
  taskkill /PID %%p /F >nul 2>&1
)
uv run shiny run app/app.py --port 8765 --launch-browser
pause

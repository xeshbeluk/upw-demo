@echo off
rem Puts the Experiment logbook back to the demo starting state (deletes uploads, events and saved plots made since).
cd /d "%~dp0"
set PYTHONUTF8=1
echo This deletes everything in logbook_data and rebuilds the demo state.
pause
uv run python -m logbook.seed
pause

@echo off
rem One-time setup: installs packages, generates the demo data, builds the warehouse, makes one report.
cd /d "%~dp0"
set PYTHONUTF8=1
where uv >nul 2>nul
if errorlevel 1 (
  echo uv was not found. Install it first, e.g.:  winget install --id=astral-sh.uv -e
  echo then close this window, open a new one and run setup.bat again.
  pause
  exit /b 1
)
echo [1/6] Installing packages ...
uv sync || goto :err
echo [2/6] Generating demo data ...
uv run python scripts/generate_upw_data.py --out data || goto :err
echo [3/6] Ingest + dbt build ...
uv run python -m pipeline.run || goto :err
echo [4/6] Weekly report ...
uv run python -m pipeline.report --latest || goto :err
echo [5/6] Experiment logbook: demo instrument files ...
uv run python scripts/generate_logbook_samples.py --out data/logbook_usb || goto :err
echo [6/6] Experiment logbook: demo state ...
uv run python -m logbook.seed || goto :err
echo.
echo Done. Start the monitoring app with start_app.bat, the experiment logbook with start_logbook.bat
pause
exit /b 0
:err
echo.
echo Something failed - scroll up for the first error message.
pause
exit /b 1

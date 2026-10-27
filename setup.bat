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
echo [1/4] Installing packages ...
uv sync || goto :err
echo [2/4] Generating demo data ...
uv run python scripts/generate_upw_data.py --out data || goto :err
echo [3/4] Ingest + dbt build ...
uv run python -m pipeline.run || goto :err
echo [4/4] Weekly report ...
uv run python -m pipeline.report --latest || goto :err
echo.
echo Done. Start the app with start_app.bat
pause
exit /b 0
:err
echo.
echo Something failed - scroll up for the first error message.
pause
exit /b 1

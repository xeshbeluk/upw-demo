"""
Entry point for hosting (Posit Connect Cloud, shinyapps.io): select THIS file as the primary file.

The generated data and the warehouse are not stored in the repository (too large for GitHub).
On the first start of a fresh server this file builds them: generate demo data -> ingest + dbt build
-> two weekly reports. That takes about a minute; later starts reuse the warehouse.

Locally you can keep using:  uv run shiny run app/app.py --launch-browser
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "warehouse" / "upw.duckdb"


def _run(*args: str) -> None:
    print("[startup]", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


if not DB.exists():
    _run("scripts/generate_upw_data.py", "--out", "data")
    _run("-m", "pipeline.run")
    _run("-m", "pipeline.report", "--latest")
    _run("-m", "pipeline.report", "--week", "2026-W02")      # the silica early-warning story

# load app/app.py under another module name (this file is already called "app")
_spec = importlib.util.spec_from_file_location("upw_app", ROOT / "app" / "app.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
app = _mod.app

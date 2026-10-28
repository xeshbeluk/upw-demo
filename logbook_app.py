"""
Hosting entry point for the Experiment logbook (Posit Connect Cloud: select THIS file as the primary file).

On a fresh server the demo is built first (fictional instrument files + pre-filled logbook, ~30 s).
Uploads and events made on a hosted copy are lost when the server restarts.

Locally use:  uv run shiny run logbook/app.py --port 8766 --launch-browser   (or start_logbook.bat)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "logbook_data" / "logbook.duckdb").exists():
    if not (ROOT / "data" / "logbook_usb").exists():
        subprocess.run([sys.executable, "scripts/generate_logbook_samples.py", "--out", "data/logbook_usb"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "logbook.seed"], cwd=ROOT, check=True)

sys.path.insert(0, str(ROOT))
from logbook.app import app  # noqa: E402,F401

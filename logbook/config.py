"""Paths for the Experiment logbook. Everything lives below logbook_data/ (not in git)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LB_DIR = ROOT / "logbook_data"
DB_PATH = LB_DIR / "logbook.duckdb"
RAW_DIR = LB_DIR / "raw"            # every uploaded file, kept unchanged
PLOTS_DIR = LB_DIR / "plots"        # saved PNG/PDF plots
USB_DIR = ROOT / "data" / "logbook_usb"   # demo: what is on the 'USB stick'

"""Project paths and plant settings. Everything is resolved relative to the repository root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
DB_PATH = ROOT / "warehouse" / "upw.duckdb"
DBT_DIR = ROOT / "dbt"
SEEDS = DBT_DIR / "seeds"
REPORTS = ROOT / "reports" / "weekly"
PLANT_TZ = "Europe/Zurich"        # the monitoring system exports local wall-clock time

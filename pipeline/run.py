"""
Pipeline entry point.

    uv run python -m pipeline.run                    # ingest new files, then dbt build (seeds, models, tests)
    uv run python -m pipeline.run --full-refresh     # reload every raw file from scratch
    uv run python -m pipeline.run --skip-ingest      # only rebuild models (e.g. after editing a reference table)
    uv run python -m pipeline.run --only diary        # ingest one source, then dbt build
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from .config import DB_PATH, DBT_DIR, SEEDS
from .db import connect
from .ingest import diary, readings

SOURCES = {"readings": readings, "diary": diary}


def run_dbt(args: list[str]) -> bool:
    os.environ["WATER_DB"] = str(DB_PATH)
    from dbt.cli.main import dbtRunner   # imported lazily: dbt is slow to import

    res = dbtRunner().invoke([*args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)])
    return bool(res.success)


def main() -> None:
    ap = argparse.ArgumentParser(description="UPW monitoring pipeline")
    ap.add_argument("--full-refresh", action="store_true", help="reload all raw files")
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--skip-dbt", action="store_true")
    ap.add_argument("--only", nargs="+", choices=list(SOURCES), help="ingest only these sources")
    a = ap.parse_args()

    if not a.skip_ingest:
        con = connect()
        try:
            for name, module in SOURCES.items():
                if a.only and name not in a.only:
                    continue
                t0 = time.time()
                print(f"Ingest: {name}")
                stats = module.ingest(con, full_refresh=a.full_refresh)
                print(f"  -> {stats}  ({time.time() - t0:.0f} s)")
        finally:
            con.close()          # dbt needs the DuckDB file lock

    if not a.skip_dbt:
        print("dbt build")
        ok = run_dbt(["build"])
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

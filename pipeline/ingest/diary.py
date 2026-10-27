"""Maintenance diary (Excel) -> landing.diary. One row per entry, text kept as written."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from ..config import PLANT_TZ, RAW
from .common import ingest_files
from .parsing import clean, parse_date
from .timeutil import localize

DDL = """
create table if not exists landing.diary (
    entry_date      date,
    time_raw        varchar,
    ts_local        timestamp,
    ts_utc          timestamp,
    unit_text       varchar,
    activity        varchar,
    technician      varchar,
    remark          varchar,
    parse_status    varchar,     -- ok | bad_date | bad_time
    source_file     varchar,
    file_row        integer,
    batch_id        varchar
)
"""

COLS = ["entry_date", "time_raw", "ts_local", "ts_utc", "unit_text", "activity", "technician", "remark",
        "parse_status", "source_file", "file_row", "batch_id"]

HEADERS = {"date": ["Datum", "Date"], "time": ["Zeit", "Time", "Uhrzeit"], "unit": ["Anlage", "Unit", "Equipment"],
           "activity": ["Tätigkeit", "Taetigkeit", "Activity"], "tech": ["Techniker", "Technician"],
           "remark": ["Bemerkung", "Remark", "Comment"]}


def pick(row, names):
    for n in names:
        if n in row.index and row[n] is not None and not (isinstance(row[n], float) and pd.isna(row[n])):
            return row[n]
    return None


def parse_time(x) -> dt.time | None:
    if x is None:
        return None
    if isinstance(x, dt.time):
        return x
    s = str(x).strip().replace(".", ":")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def parse_file(path: Path) -> tuple[pd.DataFrame, str, int]:
    raw = pd.read_excel(path, sheet_name=0, dtype=object)
    raw.columns = [str(c).strip() for c in raw.columns]
    rows = []
    for i, r in raw.iterrows():
        d, _ = parse_date(pick(r, HEADERS["date"]))
        t = parse_time(pick(r, HEADERS["time"]))
        status = "bad_date" if d is None else ("bad_time" if t is None else "ok")
        rows.append(dict(entry_date=d, time_raw=clean(pick(r, HEADERS["time"])),
                         ts_local=dt.datetime.combine(d, t) if status == "ok" else None,
                         unit_text=clean(pick(r, HEADERS["unit"])), activity=clean(pick(r, HEADERS["activity"])),
                         technician=clean(pick(r, HEADERS["tech"])), remark=clean(pick(r, HEADERS["remark"])),
                         parse_status=status, file_row=i + 2))
    df = pd.DataFrame(rows)
    df["ts_local"] = pd.to_datetime(df["ts_local"])
    df = df.sort_values("ts_local", kind="stable")
    utc, _ = localize(df["ts_local"], PLANT_TZ)
    df["ts_utc"] = utc
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    return df[[c for c in COLS if c not in ("source_file", "batch_id")]], "diary_xlsx", len(df)


def ingest(con, full_refresh: bool = False, log=print) -> dict:
    con.execute(DDL)
    files = sorted((RAW / "diary").glob("*.xlsx"))
    return ingest_files(con, "diary", "landing.diary", COLS, files, parse_file, full_refresh, log)

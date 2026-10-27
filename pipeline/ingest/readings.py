"""
Monitoring-system exports -> landing.readings (long format: one row per tag x timestamp).

Two folders, one table:
  raw/longterm/     monthly archive exports: 5-min values, ';' + decimal comma, a title line,
                    a header line with tag names and a line with units; *.STATUS columns carry
                    the analyser status (0 ok, 1 calibration, 2 maintenance, 3 fault)
  raw/maintenance/  manual high-resolution exports around maintenance work: no units line,
                    either ',' + '.' or ';' + ',', any subset of tags

Both are read faithfully (source units, local time converted to UTC, resolution detected from the
data). Choosing between overlapping sources and masking analyser maintenance happens in dbt.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PLANT_TZ, RAW
from .common import ingest_files
from .timeutil import localize

DDL = """
create table if not exists landing.readings (
    source        varchar,     -- longterm | maintenance
    tag           varchar,     -- column header as exported (status columns end in .STATUS)
    ts_local      timestamp,
    ts_utc        timestamp,
    dst_repeat    boolean,
    raw_value     varchar,
    value_num     double,
    parse_status  varchar,     -- ok | missing | unparseable | bad_timestamp
    unit_raw      varchar,     -- from the units line (long-term exports only)
    resolution_s  integer,     -- sampling interval detected in the file
    source_file   varchar,
    file_row      integer,
    batch_id      varchar
)
"""

COLS = ["source", "tag", "ts_local", "ts_utc", "dst_repeat", "raw_value", "value_num", "parse_status",
        "unit_raw", "resolution_s", "source_file", "file_row", "batch_id"]

TS_HEADERS = ("Zeitstempel", "Timestamp", "Time", "Zeit", "Datum/Zeit")


def sniff(path: Path) -> tuple[int, str, bool]:
    """-> (header line index, separator, has units line)"""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        lines = [fh.readline() for _ in range(10)]
    for i, line in enumerate(lines):
        first = line.split(";")[0].split(",")[0].strip()
        if first in TS_HEADERS:
            sep = ";" if line.count(";") > line.count(",") else ","
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            has_units = nxt.startswith(sep) or nxt.split(sep)[0].strip() == ""
            return i, sep, has_units
    raise ValueError("no header line starting with a timestamp column")


def parse_file(path: Path, source: str) -> tuple[pd.DataFrame, str, int]:
    hdr, sep, has_units = sniff(path)
    wide = pd.read_csv(path, sep=sep, skiprows=hdr, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    wide.columns = [c.strip() for c in wide.columns]
    units = {}
    first_row = hdr + 2
    if has_units:
        units = {c: (wide.iloc[0][c].strip() or None) for c in wide.columns[1:]}
        wide = wide.iloc[1:].reset_index(drop=True)
        first_row += 1
    ts_col = wide.columns[0]
    raw_ts = wide[ts_col].str.strip()
    naive = pd.to_datetime(raw_ts, format="ISO8601" if "T" in raw_ts.iloc[0] else "%d.%m.%Y %H:%M:%S",
                           errors="coerce")
    utc, dst = localize(naive, PLANT_TZ)
    diffs = pd.Series(utc).diff().dt.total_seconds().dropna()
    resolution = int(diffs[diffs > 0].median()) if len(diffs) else None

    tags = list(wide.columns[1:])
    n, k = len(wide), len(tags)
    vals = wide[tags].to_numpy(dtype=object).T.reshape(-1)
    v = pd.Series(vals, dtype=object).astype(str).str.strip()
    s = v.str.replace(",", ".", regex=False) if sep == ";" else v
    num = pd.to_numeric(s, errors="coerce")
    bad_ts = np.tile(np.asarray(pd.isna(utc)), k)
    status = np.select([bad_ts, v.eq("").to_numpy(), num.isna().to_numpy()],
                       ["bad_timestamp", "missing", "unparseable"], default="ok")
    df = pd.DataFrame({
        "source": source,
        "tag": np.repeat(np.asarray(tags, dtype=object), n),
        "ts_local": np.tile(naive.to_numpy(), k),
        "ts_utc": np.tile(utc, k),
        "dst_repeat": np.tile(dst, k),
        "raw_value": v.to_numpy(dtype=object),
        "value_num": num.where(status == "ok").to_numpy(),
        "parse_status": status,
        "unit_raw": np.repeat(np.asarray([units.get(t) for t in tags], dtype=object), n),
        "resolution_s": resolution,
        "file_row": np.tile(np.arange(n) + first_row, k),
    })
    return df, f"{source} {resolution}s sep='{sep}'", n


def ingest(con, full_refresh: bool = False, log=print) -> dict:
    con.execute(DDL)
    stats = {}
    for source in ("longterm", "maintenance"):
        if full_refresh:                                  # both sources share one table: clear per source
            con.execute("delete from landing.readings where source = ?", [source])
            con.execute("delete from landing.load_log where source = ?", [source])
        files = sorted((RAW / source).glob("*.csv"))
        stats[source] = ingest_files(con, source, "landing.readings", COLS, files,
                                     lambda f, s=source: parse_file(f, s), False, log)
    return stats

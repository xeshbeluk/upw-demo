"""
Shared file-ingestion loop used by every source.

For each file: fingerprint it (SHA-1 of the bytes), skip it if that exact content was loaded
before (logged as 'duplicate_skipped' when it arrives under another name), otherwise parse it
and replace that file's rows in the landing table inside one transaction. Every outcome,
including failures, is written to landing.load_log.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path
from typing import Callable

import pandas as pd

from ..config import ROOT
from ..db import already_logged, loaded_path_for_hash, log_load

# parse_fn(path) -> (DataFrame with the table's columns except source_file/batch_id, dialect/layout label, rows_in)
ParseFn = Callable[[Path], "tuple[pd.DataFrame, str, int]"]


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_files(con, source: str, table: str, columns: list[str], files: list[Path], parse_fn: ParseFn,
                 full_refresh: bool = False, log=print) -> dict:
    if full_refresh:
        con.execute(f"delete from {table}")
        con.execute("delete from landing.load_log where source = ?", [source])
    batch = f"{source}-{dt.datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    stats = dict(files_seen=len(files), loaded=0, unchanged=0, duplicates=0, failed=0, rows=0)
    collist = ", ".join(columns)
    files = sorted(files, key=lambda p: (p.stat().st_mtime, p.name))   # arrival order: originals before re-sends

    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        digest = sha1(f)
        meta = dict(batch_id=batch, source=source, file_path=rel, file_sha1=digest, file_bytes=f.stat().st_size)
        if already_logged(con, rel, digest):
            stats["unchanged"] += 1
            continue
        prev = loaded_path_for_hash(con, digest)
        if prev is not None:
            log_load(con, **meta, status="duplicate_skipped", message=f"identical content to {prev}")
            stats["duplicates"] += 1
            log(f"  dup     {rel}  (identical to {prev})")
            continue
        in_tx = False
        try:
            df, dialect, rows_in = parse_fn(f)
            df["source_file"] = rel
            df["batch_id"] = batch
            con.begin()
            in_tx = True
            con.execute(f"delete from {table} where source_file = ?", [rel])
            con.register("_ingest_df", df)
            con.execute(f"insert into {table} ({collist}) select {collist} from _ingest_df")
            con.unregister("_ingest_df")
            log_load(con, **meta, dialect=dialect, rows_in=rows_in, values_loaded=len(df), status="loaded", message="")
            con.commit()
            in_tx = False
            stats["loaded"] += 1
            stats["rows"] += len(df)
            log(f"  loaded  {rel}  ({dialect}, {len(df):,} rows)")
        except Exception as e:  # keep going; the failure is visible in load_log
            if in_tx:
                con.rollback()
            log_load(con, **meta, status="failed", message=f"{type(e).__name__}: {e}")
            stats["failed"] += 1
            log(f"  FAILED  {rel}: {type(e).__name__}: {e}")
    return stats

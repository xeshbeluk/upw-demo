"""DuckDB connection + landing-zone DDL + load log helpers."""
from __future__ import annotations

import datetime as dt

import duckdb

from .config import DB_PATH

BASE_DDL = [
    "create schema if not exists landing",
    """
    create table if not exists landing.load_log (
        batch_id      varchar,
        source        varchar,
        file_path     varchar,
        file_sha1     varchar,
        file_bytes    bigint,
        dialect       varchar,
        rows_in       bigint,
        values_loaded bigint,
        status        varchar,     -- loaded | failed | duplicate_skipped
        message       varchar,
        loaded_at     timestamp
    )
    """,
]


def connect() -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for stmt in BASE_DDL:
        con.execute(stmt)
    return con


def loaded_path_for_hash(con, file_sha1: str) -> str | None:
    """Path of a previously loaded file with identical content, or None."""
    row = con.execute(
        "select file_path from landing.load_log where file_sha1 = ? and status = 'loaded' limit 1", [file_sha1]
    ).fetchone()
    return row[0] if row else None


def already_logged(con, file_path: str, file_sha1: str) -> bool:
    """True if this exact path + content was already loaded or already recorded as a duplicate."""
    n = con.execute(
        "select count(*) from landing.load_log where file_path = ? and file_sha1 = ? "
        "and status in ('loaded', 'duplicate_skipped')", [file_path, file_sha1]
    ).fetchone()[0]
    return n > 0


def log_load(con, **kw) -> None:
    con.execute(
        """insert into landing.load_log
           (batch_id, source, file_path, file_sha1, file_bytes, dialect, rows_in, values_loaded, status, message, loaded_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [kw.get("batch_id"), kw.get("source"), kw.get("file_path"), kw.get("file_sha1"), kw.get("file_bytes"),
         kw.get("dialect"), kw.get("rows_in"), kw.get("values_loaded"), kw.get("status"), kw.get("message"),
         dt.datetime.now()],
    )

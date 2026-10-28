"""DuckDB storage for the logbook: experiments, file formats, uploaded files, measurements, events."""
from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import math
import re

import duckdb
import pandas as pd

from . import parsing
from .config import DB_PATH, RAW_DIR

SCHEMA = """
create table if not exists experiments (
    experiment_id varchar primary key, title varchar, description varchar, owner varchar,
    start_date date, status varchar, created_at timestamp);
create table if not exists layouts (
    layout_name varchar primary key, settings varchar, created_by varchar, created_at timestamp);
create sequence if not exists file_seq;
create table if not exists files (
    file_id integer primary key default nextval('file_seq'), experiment_id varchar, file_name varchar,
    sha1 varchar, layout_name varchar, status varchar, uploaded_by varchar, uploaded_at timestamp,
    rows_read integer, values_new integer, values_overlap integer, values_flagged integer,
    t_min timestamp, t_max timestamp, stored_path varchar);
create table if not exists parameters (
    experiment_id varchar, parameter varchar, unit varchar, primary key (experiment_id, parameter));
create table if not exists measurements (
    experiment_id varchar, parameter varchar, ts timestamp, value double, flag varchar, file_id integer);
create table if not exists event_categories (
    category varchar primary key, color varchar, default_style varchar, sort integer);
create sequence if not exists event_seq;
create table if not exists events (
    event_id integer primary key default nextval('event_seq'), experiment_id varchar,  -- null = all experiments
    start_ts timestamp, end_ts timestamp, label varchar, category varchar, style varchar, note varchar,
    created_by varchar, created_at timestamp, updated_at timestamp);
"""
STYLES = {"line": "Vertical line", "note": "Note (callout)", "shade": "Shaded period", "hidden": "Hidden"}
CATEGORIES = [  # category, colour, default display
    ("Filter change", "#2a78d6", "line"), ("CIP / cleaning", "#1baf7a", "shade"),
    ("Calibration", "#eda100", "line"), ("Set-point change", "#6250d6", "note"),
    ("Maintenance", "#eb6834", "line"), ("Plant event", "#e34948", "shade"),
    ("Sample taken", "#008300", "note"), ("Other", "#8a8985", "note"),
]

_con: duckdb.DuckDBPyConnection | None = None


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _con = duckdb.connect(str(DB_PATH))
        _con.execute(SCHEMA)
        if not _con.execute("select count(*) from event_categories").fetchone()[0]:
            _con.executemany("insert into event_categories values (?, ?, ?, ?)",
                             [(c, col, s, i) for i, (c, col, s) in enumerate(CATEGORIES)])
    return _con


def close() -> None:
    global _con
    if _con is not None:
        _con.close()
        _con = None


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    return con().execute(sql, params or []).df()


def default_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "demo-user"


# ---------------------------------------------------------------------------------------------- experiments
def experiments() -> pd.DataFrame:
    return q("""
        select e.experiment_id, e.title, e.owner, e.start_date, e.status,
               count(distinct f.file_id) filter (where f.status = 'imported') as files,
               coalesce(sum(f.values_new), 0) as values_stored,
               min(f.t_min) as data_from, max(f.t_max) as data_to, max(f.uploaded_at) as last_upload,
               e.description
        from experiments e left join files f using (experiment_id)
        group by all order by e.start_date desc""")


def add_experiment(code: str, title: str, owner: str, start: dt.date, description: str = "") -> str | None:
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,30}", code):
        return "Code: 3-30 characters, letters, digits, - or _"
    if not title.strip():
        return "Title is required"
    if q("select 1 from experiments where experiment_id = ?", [code]).shape[0]:
        return f"{code} already exists"
    con().execute("insert into experiments (experiment_id, title, description, owner, start_date, status, created_at) "
                  "values (?, ?, ?, ?, ?, 'running', now())",
                  [code, title.strip(), description.strip(), owner.strip(), start])
    return None


def parameters(exp: str) -> pd.DataFrame:
    return q("select parameter, unit from parameters where experiment_id = ? order by rowid", [exp])


def files(exp: str | None = None) -> pd.DataFrame:
    return q("select * from files" + (" where experiment_id = ?" if exp else "") + " order by uploaded_at desc, file_id desc",
             [exp] if exp else [])


def data_span(exp: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    r = q("select min(ts) a, max(ts) b from measurements where experiment_id = ?", [exp]).iloc[0]
    return None if pd.isna(r.a) else (pd.Timestamp(r.a), pd.Timestamp(r.b))


# ---------------------------------------------------------------------------------------------- layouts
def layouts() -> list[parsing.Layout]:
    df = q("select layout_name, settings from layouts order by created_at")
    return [parsing.Layout.from_dict({**json.loads(s), "name": n}) for n, s in zip(df.layout_name, df.settings)]


def save_layout(lay: parsing.Layout, user: str) -> str | None:
    if not lay.name.strip():
        return "Give the format a name"
    if not lay.date_col:
        return "Choose the timestamp column"
    con().execute("insert or replace into layouts values (?, ?, ?, now())",
                  [lay.name.strip(), json.dumps(lay.to_dict()), user])
    return None


# ---------------------------------------------------------------------------------------------- import
def sha1(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


def already_imported(exp: str, digest: str) -> str | None:
    r = q("select file_name from files where experiment_id = ? and sha1 = ? and status = 'imported'", [exp, digest])
    return None if r.empty else r.file_name.iloc[0]


def import_file(exp: str, file_name: str, raw: bytes, lay: parsing.Layout, user: str) -> dict:
    """Parse and store one file. Values already stored for the same parameter and timestamp
    (overlapping exports) are skipped, so the long-term series never contains duplicates."""
    c = con()
    digest = sha1(raw)
    now = dt.datetime.now().replace(microsecond=0)
    dup = already_imported(exp, digest)
    if dup:
        c.execute("insert into files (experiment_id, file_name, sha1, layout_name, status, uploaded_by, uploaded_at) "
                  "values (?, ?, ?, ?, 'duplicate', ?, ?)", [exp, file_name, digest, lay.name, user, now])
        return {"file": file_name, "status": "duplicate", "message": f"identical to '{dup}' - skipped"}
    long, stats = parsing.parse(raw, lay)
    path = RAW_DIR / exp / f"{now:%Y%m%d-%H%M%S}_{digest[:8]}_{file_name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    file_id = c.execute("insert into files (experiment_id, file_name, sha1, layout_name, status, uploaded_by, "
                        "uploaded_at, rows_read, t_min, t_max, stored_path) values (?, ?, ?, ?, 'imported', ?, ?, ?, ?, ?, ?) "
                        "returning file_id",
                        [exp, file_name, digest, lay.name, user, now, stats["rows"], long.ts.min(), long.ts.max(),
                         str(path)]).fetchone()[0]
    c.register("new_values", long)
    for p, u in long.drop_duplicates("parameter")[["parameter", "unit"]].values:   # keeps the file's column order
        c.execute("insert into parameters values (?, ?, ?) on conflict do nothing", [exp, p, u])
    before = c.execute("select count(*) from measurements where experiment_id = ?", [exp]).fetchone()[0]
    c.execute("""
        insert into measurements
        select ?, n.parameter, n.ts, n.value, n.flag, ?
        from (select distinct on (parameter, ts) * from new_values) n
        where not exists (select 1 from measurements m
                          where m.experiment_id = ? and m.parameter = n.parameter and m.ts = n.ts)""",
              [exp, file_id, exp])
    c.unregister("new_values")
    added = c.execute("select count(*) from measurements where experiment_id = ?", [exp]).fetchone()[0] - before
    flagged = int(long.flag.notna().sum())
    c.execute("update files set values_new = ?, values_overlap = ?, values_flagged = ? where file_id = ?",
              [added, len(long) - added, flagged, file_id])
    msg = f"{added:,} new values"
    if len(long) - added:
        msg += f", {len(long) - added:,} already stored (overlap with an earlier export) - skipped"
    if flagged:
        msg += f", {flagged:,} flagged by instrument status"
    if stats["bad_timestamps"]:
        msg += f", {stats['bad_timestamps']} rows with unreadable time skipped"
    return {"file": file_name, "status": "imported", "file_id": file_id, "message": msg,
            "t_min": long.ts.min(), "t_max": long.ts.max(), "new": added}


# ---------------------------------------------------------------------------------------------- data
def series(exp: str, params: list[str], t0, t1, include_flagged: bool = False, max_points: int = 3000) -> tuple[pd.DataFrame, str]:
    """Values for plotting. Long periods are averaged into time buckets (mean, min, max) so the
    browser gets at most ~max_points points per parameter; the label says which resolution was used."""
    if not params:
        return pd.DataFrame(columns=["ts", "parameter", "mean", "min", "max"]), ""
    marks = ",".join("?" * len(params))
    where = (f"experiment_id = ? and parameter in ({marks}) and ts between ? and ?"
             + ("" if include_flagged else " and flag is null"))
    args = [exp, *params, t0, t1]
    n = q(f"select max(c) from (select count(*) c from measurements where {where} group by parameter)", args).iloc[0, 0]
    if pd.isna(n) or not n:
        return pd.DataFrame(columns=["ts", "parameter", "mean", "min", "max"]), "no data"
    if n <= max_points:
        df = q(f"select ts, parameter, value as mean, null::double as min, null::double as max from measurements "
               f"where {where} order by ts", args)
        return df, "as recorded"
    span = (pd.Timestamp(t1) - pd.Timestamp(t0)).total_seconds()
    step = nice_step(span / max_points)
    df = q(f"""select time_bucket(interval '{step} seconds', ts) as ts, parameter, avg(value) as mean,
                      min(value) as min, max(value) as max
               from measurements where {where} group by all order by ts""", args)
    return df, f"averaged per {human_step(step)}"


def raw_values(exp: str, params: list[str], t0, t1, include_flagged: bool) -> pd.DataFrame:
    marks = ",".join("?" * len(params))
    return q(f"""select ts, parameter, value, flag from measurements
                 where experiment_id = ? and parameter in ({marks}) and ts between ? and ?
                 {'' if include_flagged else 'and flag is null'} order by ts""", [exp, *params, t0, t1])


STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]


def nice_step(sec: float) -> int:
    return next((s for s in STEPS if s >= sec), int(math.ceil(sec / 86400)) * 86400)


def human_step(sec: int) -> str:
    return f"{sec // 86400} day(s)" if sec >= 86400 and sec % 86400 == 0 else \
        f"{sec // 3600} h" if sec >= 3600 else f"{sec // 60} min"


# ---------------------------------------------------------------------------------------------- events
def categories() -> pd.DataFrame:
    return q("select * from event_categories order by sort")


def events(exp: str | None, t0=None, t1=None) -> pd.DataFrame:
    """Events of one experiment plus those valid for all experiments (experiment_id null)."""
    sql = """select e.*, c.color, coalesce(e.experiment_id, 'all experiments') as scope
             from events e left join event_categories c using (category) where true"""
    args = []
    if exp:
        sql += " and (e.experiment_id = ? or e.experiment_id is null)"
        args.append(exp)
    if t0 is not None:
        sql += " and coalesce(e.end_ts, e.start_ts) >= ? and e.start_ts <= ?"
        args += [t0, t1]
    return q(sql + " order by e.start_ts", args)


def save_event(event_id: int | None, exp: str | None, start: dt.datetime, end: dt.datetime | None, label: str,
               category: str, style: str, note: str, user: str) -> str | None:
    if not label.strip():
        return "Label is required"
    if end is not None and end <= start:
        return "End must be after start"
    if style == "shade" and end is None:
        return "A shaded period needs an end time"
    if event_id is None:
        con().execute("insert into events (experiment_id, start_ts, end_ts, label, category, style, note, created_by, "
                      "created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, now(), now())",
                      [exp, start, end, label.strip(), category, style, note.strip(), user])
    else:
        con().execute("update events set experiment_id = ?, start_ts = ?, end_ts = ?, label = ?, category = ?, "
                      "style = ?, note = ?, updated_at = now() where event_id = ?",
                      [exp, start, end, label.strip(), category, style, note.strip(), event_id])
    return None


def delete_event(event_id: int) -> None:
    con().execute("delete from events where event_id = ?", [event_id])

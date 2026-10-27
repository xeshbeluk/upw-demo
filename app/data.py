"""Read access to the UPW warehouse for the app (read-only; closed during rebuilds)."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.config import DB_PATH, REPORTS, SEEDS  # noqa: E402,F401

_con: duckdb.DuckDBPyConnection | None = None


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"{DB_PATH} not found - run the pipeline first")
        _con = duckdb.connect(str(DB_PATH), read_only=True)
    return _con


def close() -> None:
    global _con
    if _con is not None:
        _con.close()
        _con = None


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    return con().execute(sql, params or []).df()


# ------------------------------------------------------------------ catalogue
def tags() -> pd.DataFrame:
    return q("select t.*, u.unit_name, u.sequence from reference.tags t "
             "left join reference.process_units u using (unit_id) order by display_order")


def limits() -> pd.DataFrame:
    return q("select * from reference.spec_limits")


def data_range() -> tuple[dt.date, dt.date]:
    r = q("select min(local_date) as a, max(local_date) as b from marts.mart_daily").iloc[0]
    return pd.Timestamp(r.a).date(), pd.Timestamp(r.b).date()


# ------------------------------------------------------------------ overview
def latest_day_status() -> pd.DataFrame:
    """Last full day per key POU tag with its spec limits."""
    return q("""
        with last_day as (select max(local_date) - 1 as d from marts.mart_daily)
        select d.tag, t.description, t.unit, d.local_date, d.mean_value, d.min_value, d.max_value, d.completeness
        from marts.mart_daily d join reference.tags t using (tag), last_day
        where d.local_date = last_day.d and t.unit_id = 'POU' and d.tag <> 'UPW1.POU.TOC_B'
        order by t.display_order""")


def exceedances(since: dt.date | None = None) -> pd.DataFrame:
    return q("select * from marts.mart_spec_exceedances" + (" where cast(start_local as date) >= ?" if since else "")
             + " order by start_utc desc", [since] if since else [])


def trend_latest() -> pd.DataFrame:
    return q("""select t.*, g.description, g.unit from marts.mart_trend t join reference.tags g using (tag)
                where t.local_date = (select max(local_date) - 1 from marts.mart_trend)""")


def trend_episodes() -> pd.DataFrame:
    return q("select e.*, t.description, t.unit from marts.mart_trend_episodes e join reference.tags t using (tag) "
             "order by start_date desc")


def events(include_inspections: bool = False) -> pd.DataFrame:
    return q("select * from core.dim_event" + ("" if include_inspections else " where event_type <> 'inspection'")
             + " order by ts_utc desc")


# ------------------------------------------------------------------ trends
def series(tag_list: list[str], start: dt.date, end: dt.date, grain: str) -> pd.DataFrame:
    if not tag_list:
        return pd.DataFrame()
    marks = ",".join("?" * len(tag_list))
    if grain == "daily":
        return q(f"select tag, local_date as ts, mean_value, min_value, max_value from marts.mart_daily "
                 f"where tag in ({marks}) and local_date between ? and ? order by ts", [*tag_list, start, end])
    if grain == "hourly":
        return q(f"select tag, hour_local_start as ts, mean_value, min_value, max_value from marts.mart_hourly "
                 f"where tag in ({marks}) and cast(hour_local_start as date) between ? and ? order by ts",
                 [*tag_list, start, end])
    return q(f"select tag, ts_local as ts, value as mean_value, null as min_value, null as max_value "
             f"from core.fct_reading where source = 'longterm' and quality_flag = 'good' and tag in ({marks}) "
             f"and cast(ts_local as date) between ? and ? order by ts", [*tag_list, start, end])


# ------------------------------------------------------------------ event window
def window_data(tag_list: list[str], t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    """Readings in [t0, t1] (local time). Per tag, the high-resolution maintenance export is used
    where it covers the window, the 5-min archive elsewhere. Masked analyser values are excluded."""
    if not tag_list:
        return pd.DataFrame()
    marks = ",".join("?" * len(tag_list))
    df = q(f"""
        select tag, ts_local, value, source, resolution_s, quality_flag
        from core.fct_reading
        where tag in ({marks}) and ts_local between ? and ?
        order by tag, ts_local""", [*tag_list, t0.to_pydatetime(), t1.to_pydatetime()])
    if df.empty:
        return df
    hi = df[df.source == "maintenance"]
    if not hi.empty:                                        # replace archive values inside the high-res span
        spans = hi.groupby("tag").ts_local.agg(["min", "max"])
        keep = []
        for tag, g in df[df.source == "longterm"].groupby("tag"):
            if tag in spans.index:
                a, b = spans.loc[tag]
                g = g[(g.ts_local < a) | (g.ts_local > b)]
            keep.append(g)
        df = pd.concat(keep + [hi]).sort_values(["tag", "ts_local"])
    return df


def before_after(df: pd.DataFrame, t_event: pd.Timestamp, catalogue: pd.DataFrame, hold_min: int = 30) -> pd.DataFrame:
    """
    Per tag: level before the event, level after, worst value after, and recovery time =
    time until the value is back inside the normal band of the before-window (5th-95th percentile,
    widened by half the tag's min_relevant_change) and stays there for `hold_min` minutes.
    """
    rows = []
    good = df[df.quality_flag == "good"]
    for tag, g in good.groupby("tag"):
        t = catalogue.set_index("tag").loc[tag]
        before = g[g.ts_local < t_event].value
        after = g[g.ts_local >= t_event]
        if before.empty or after.empty:
            continue
        pad = t.min_relevant_change / 2
        lo, hi = before.quantile(0.05) - pad, before.quantile(0.95) + pad
        if t.bad_direction == "up":            # a drop is not a deviation (e.g. lower filter dP after a change)
            inside = (after.value <= hi).to_numpy()
        elif t.bad_direction == "down":
            inside = (after.value >= lo).to_numpy()
        else:
            inside = after.value.between(lo, hi).to_numpy()
        ts = after.ts_local.to_numpy()
        recovered_at = None
        run_start = None
        for i, ok in enumerate(inside):
            if ok:
                run_start = ts[i] if run_start is None else run_start
                if (ts[i] - run_start) >= np.timedelta64(hold_min, "m"):
                    recovered_at = run_start
                    break
            else:
                run_start = None
        worst = after.value.max() if t.bad_direction in ("up", "both") else after.value.min()
        tail = after[after.ts_local >= after.ts_local.max() - (after.ts_local.max() - after.ts_local.min()) / 4]
        rows.append({
            "tag": tag, "parameter": t.description, "unit": t.unit,
            "mean_before": before.mean(), "normal_band": f"{lo:.3g} - {hi:.3g}",
            "worst_after": worst, "mean_end_of_window": tail.value.mean(),
            "level_change": tail.value.mean() - before.mean(),
            "recovery": ("no deviation" if inside[:1].all() and recovered_at == ts[0]
                         else f"{(pd.Timestamp(recovered_at) - t_event).total_seconds() / 3600:.1f} h"
                         if recovered_at is not None else "not within window"),
            "resolution": "10 s" if (g.source == "maintenance").any() else "5 min",
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ analyser study
def analyzer_pairs() -> pd.DataFrame:
    return q("""
        with a as (select ts_utc, ts_local, value from core.fct_reading
                   where tag = 'UPW1.POU.TOC' and source = 'longterm' and quality_flag = 'good'),
             b as (select ts_utc, value from core.fct_reading
                   where tag = 'UPW1.POU.TOC_B' and source = 'longterm' and quality_flag = 'good')
        select a.ts_local, a.value as toc_a, b.value as toc_b from a join b using (ts_utc) order by 1""")


def analyzer_daily() -> pd.DataFrame:
    return q("select * from marts.mart_analyzer_comparison order by local_date")


# ------------------------------------------------------------------ health
def health() -> pd.DataFrame:
    return q("select * from marts.mart_data_health order by source")


def unclassified() -> pd.DataFrame:
    return q("select * from quality.qa_unclassified_events")


def masked_summary() -> pd.DataFrame:
    return q("""select tag, mask_reason, count(*) * 5 / 60.0 as hours
                from core.fct_reading where source = 'longterm' and quality_flag = 'masked'
                group by all order by tag, hours desc""")


def completeness() -> pd.DataFrame:
    return q("select tag, local_date, completeness from marts.mart_daily")


def load_log(n: int = 40) -> pd.DataFrame:
    return q(f"select loaded_at, source, status, file_path, values_loaded, message from landing.load_log "
             f"order by loaded_at desc limit {int(n)}")

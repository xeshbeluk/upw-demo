"""
Weekly UPW report: one self-contained HTML file per ISO week (charts embedded, no internet needed).

    uv run python -m pipeline.report --latest           # the last complete week in the data
    uv run python -m pipeline.report --week 2026-W12
    uv run python -m pipeline.report --all

Contents: headline status, spec / alert limit exceedances (maintenance-related ones separated),
trend deviations with "days to spec limit", charts of the affected parameters (8 weeks of
context), the week's diary events, and data quality (completeness, masked analyser time).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .config import DB_PATH, REPORTS  # noqa: E402

PLANT = "UPW1"
BLUE, ORANGE, RED, AMBER, GREY = "#2a78d6", "#eb6834", "#d03b3b", "#c98500", "#8a8985"
KEY_TAGS = ["UPW1.POU.TOC", "UPW1.POU.RES", "UPW1.POU.SIO2", "UPW1.POU.PART", "UPW1.POU.DO", "UPW1.POU.TEMP"]


# ------------------------------------------------------------------ data
class Week:
    def __init__(self, iso: str):
        y, w = iso.split("-W")
        self.iso = f"{int(y)}-W{int(w):02d}"
        self.start = dt.date.fromisocalendar(int(y), int(w), 1)
        self.end = self.start + dt.timedelta(days=6)

    def __str__(self):
        return f"{self.iso} ({self.start:%d %b} - {self.end:%d %b %Y})"


def q(con, sql, params=None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


def load(con, wk: Week) -> dict:
    s, e = wk.start, wk.end
    ctx_start = s - dt.timedelta(weeks=7)
    d = {}
    d["tags"] = q(con, "select * from reference.tags order by display_order")
    d["limits"] = q(con, "select * from reference.spec_limits")
    d["exc"] = q(con, """
        select tag, description, unit, severity, limit_type, limit_value, start_local, duration_min,
               minutes_beyond, peak_value, maintenance_related, related_event
        from marts.mart_spec_exceedances
        where cast(start_local as date) <= ? and cast(start_local + to_minutes(duration_min) as date) >= ?
        order by severity desc, start_local""", [e, s])
    d["trend"] = q(con, """
        select t.*, g.description, g.unit, g.bad_direction from marts.mart_trend t
        join reference.tags g using (tag)
        where t.local_date between ? and ? """, [s, e])
    d["daily"] = q(con, "select * from marts.mart_daily where local_date between ? and ?", [ctx_start, e])
    d["events"] = q(con, "select * from core.dim_event where cast(ts_local as date) between ? and ? "
                         "and event_type <> 'inspection' order by ts_local", [s, e])
    d["unclassified"] = q(con, "select * from quality.qa_unclassified_events where cast(ts_local as date) between ? and ?",
                          [s, e])
    d["ctx_events"] = q(con, "select * from core.dim_event where cast(ts_local as date) between ? and ? "
                             "and is_maintenance", [ctx_start, e])
    d["masked"] = q(con, """
        select tag, count(*) * 5 / 60.0 as masked_hours, any_value(mask_reason) as reason
        from core.fct_reading where source = 'longterm' and quality_flag = 'masked'
          and cast(ts_local as date) between ? and ? group by 1""", [s, e])
    return d


# ------------------------------------------------------------------ charts
def chart(d: dict, tag: str, wk: Week) -> str:
    t = d["tags"].set_index("tag").loc[tag]
    x = d["daily"][d["daily"].tag == tag].sort_values("local_date")
    fig, ax = plt.subplots(figsize=(7.6, 2.5), dpi=110)
    dates = pd.to_datetime(x.local_date)
    ax.fill_between(dates, x.min_value, x.max_value, color=BLUE, alpha=0.15, linewidth=0, label="daily min-max")
    ax.plot(dates, x.mean_value, color=BLUE, linewidth=1.8, label="daily mean")
    for _, l in d["limits"][d["limits"].tag == tag].iterrows():
        ax.axhline(l.limit_value, color=RED if l.severity == "spec" else AMBER, linewidth=1.2,
                   linestyle="-" if l.severity == "spec" else "--", label=f"{l.severity} {l.limit_value:g}")
    ax.axvspan(pd.Timestamp(wk.start), pd.Timestamp(wk.end) + pd.Timedelta(days=1), color=GREY, alpha=0.12, linewidth=0)
    for _, ev in d["ctx_events"].iterrows():
        if tag in str(ev.default_tags).split("|"):
            ax.axvline(pd.Timestamp(ev.ts_local), color=GREY, linewidth=1, linestyle=":")
            ax.text(pd.Timestamp(ev.ts_local), ax.get_ylim()[1], " " + ev.event_label, fontsize=7, color=GREY,
                    va="top", rotation=90)
    ax.set_title(f"{t.description} [{t.unit}]", loc="left", fontsize=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", color="#e7e6e2")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=7, loc="upper left", frameon=False, ncol=4)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------------ html
def fmt(v, digits=3):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    return f"{v:.{digits}g}" if isinstance(v, float) else str(v)


def table(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p class='muted'>None.</p>"
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(fmt(v) if not isinstance(v, str) else v)}</td>" for v in r) + "</tr>"
                   for r in df.itertuples(index=False))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def build(con, wk: Week) -> str:
    d = load(con, wk)
    exc = d["exc"]
    spec_real = exc[(exc.severity == "spec") & ~exc.maintenance_related]
    spec_maint = exc[(exc.severity == "spec") & exc.maintenance_related]
    alerts = exc[exc.severity == "alert"]
    trend = d["trend"]
    flagged = trend[trend.flag].sort_values("local_date").groupby("tag").tail(1)

    # headline
    if len(spec_real):
        status, cls = "Specification exceeded", "red"
    elif len(flagged) or len(alerts):
        status, cls = "Attention: trends or alert levels", "amber"
    else:
        status, cls = "All parameters within specification and normal range", "green"

    # weekly KPI table for the point of use
    dw = d["daily"][(pd.to_datetime(d["daily"].local_date).dt.date >= wk.start)]
    kpi = []
    for tag in KEY_TAGS:
        x = dw[dw.tag == tag]
        if x.empty:
            continue
        t = d["tags"].set_index("tag").loc[tag]
        lim = d["limits"][(d["limits"].tag == tag) & (d["limits"].severity == "spec")]
        kpi.append({"Parameter": t.description, "Unit": t.unit, "Mean": fmt(x.mean_value.mean()),
                    "Min": fmt(x.min_value.min()), "Max": fmt(x.max_value.max()),
                    "Spec": ", ".join(f"{'≤' if l.limit_type == 'max' else '≥'} {l.limit_value:g}" for l in lim.itertuples()),
                    "Data complete": f"{100 * x.completeness.mean():.0f} %"})
    kpi = pd.DataFrame(kpi)

    def exc_table(df):
        if df.empty:
            return df
        return pd.DataFrame({
            "Parameter": df.description, "Limit": [f"{'≤' if r.limit_type == 'max' else '≥'} {r.limit_value:g} {r.unit}"
                                                   for r in df.itertuples()],
            "Start": pd.to_datetime(df.start_local).dt.strftime("%a %d %b %H:%M"),
            "Duration": [f"{m / 60:.1f} h" for m in df.duration_min],
            "Time beyond": [f"{m / 60:.1f} h" for m in df.minutes_beyond],
            "Peak": [fmt(v) for v in df.peak_value], "Related event": df.related_event.fillna("")})

    trend_rows = []
    for r in flagged.itertuples():
        direction = "above" if r.deviation > 0 else "below"
        sentence = (f"{abs(r.deviation):.3g} {r.unit} {direction} its normal level ({r.baseline:.3g} {r.unit})")
        if pd.notna(r.days_to_spec):
            sentence += f"; at the current rate the spec limit is reached in about {max(r.days_to_spec, 0):.0f} day(s)"
        trend_rows.append({"Parameter": r.description, "Flagged on": r.local_date.strftime("%a %d %b"),
                           "Finding": sentence, "Trend per day": f"{r.slope_per_day:+.3g} {r.unit}"})
    trend_tbl = pd.DataFrame(trend_rows)

    chart_tags = list(dict.fromkeys(list(spec_real.tag) + list(flagged.tag) + list(alerts.tag) + list(spec_maint.tag)))[:6]
    charts = "".join(f"<img src='data:image/png;base64,{chart(d, t, wk)}' alt='{html.escape(t)}'>" for t in chart_tags)

    ev = d["events"]
    ev_tbl = pd.DataFrame({"When": pd.to_datetime(ev.ts_local).dt.strftime("%a %d %b %H:%M"), "Type": ev.event_label,
                           "Unit": ev.unit_name, "Entry": ev.activity, "By": ev.technician}) if len(ev) else pd.DataFrame()
    unc = d["unclassified"]
    unc_html = ("" if unc.empty else
                f"<p class='warn'>{len(unc)} diary entr{'y' if len(unc) == 1 else 'ies'} could not be classified "
                f"(not counted above): " + "; ".join(html.escape(a) for a in unc.activity) + "</p>")
    masked = d["masked"]
    masked_tbl = pd.DataFrame({"Tag": masked.tag, "Hours excluded": [f"{h:.1f}" for h in masked.masked_hours],
                               "Reason": masked.reason}) if len(masked) else pd.DataFrame()

    css = """
    body{font-family:Segoe UI,Inter,system-ui,sans-serif;color:#0b0b0b;max-width:900px;margin:24px auto;padding:0 16px;}
    h1{font-size:22px;margin-bottom:2px} h2{font-size:16px;margin-top:28px;border-bottom:1px solid #e7e6e2;padding-bottom:4px}
    .muted{color:#52514e} .status{padding:10px 14px;border-left:5px solid;margin:14px 0;font-weight:600}
    .red{border-color:#d03b3b;background:#fdeeee} .amber{border-color:#fab219;background:#fff8e6}
    .green{border-color:#0ca30c;background:#eef8ee} .warn{background:#fff8e6;padding:8px 10px}
    table{border-collapse:collapse;width:100%;font-size:13px} th,td{border-bottom:1px solid #e7e6e2;padding:5px 6px;text-align:left}
    th{color:#52514e;font-weight:600} img{width:100%;margin:6px 0}
    """
    n_hours = lambda df: f"{df.minutes_beyond.sum() / 60:.1f} h" if len(df) else "0 h"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{PLANT} weekly report {wk.iso}</title>
<style>{css}</style></head><body>
<h1>{PLANT} ultrapure water - weekly report</h1>
<div class='muted'>Week {html.escape(str(wk))} · generated {dt.datetime.now():%d %b %Y %H:%M} · demo data</div>
<div class='status {cls}'>{status}</div>
<p>Spec exceedances: <b>{len(spec_real)}</b> ({n_hours(spec_real)} beyond limit) ·
   during maintenance: <b>{len(spec_maint)}</b> ({n_hours(spec_maint)}) ·
   alert-level episodes: <b>{len(alerts)}</b> · trend deviations: <b>{len(flagged)}</b> ·
   maintenance / plant events: <b>{len(ev)}</b></p>
<h2>Point-of-use summary</h2>{table(kpi)}
<h2>Specification exceedances</h2>{table(exc_table(spec_real))}
<h2>Exceedances during maintenance work</h2>
<p class='muted'>Expected effects of the work (e.g. particles after a filter change). Shown so their duration can be checked.</p>
{table(exc_table(spec_maint))}
<h2>Alert-level episodes</h2>{table(exc_table(alerts))}
<h2>Trend deviations</h2>
<p class='muted'>Parameters whose smoothed level moved clearly away from their normal range in the unfavourable
direction, even if still within specification.</p>{table(trend_tbl)}
<h2>Charts (8 weeks, this week shaded)</h2>{charts or "<p class='muted'>No affected parameters.</p>"}
<h2>Maintenance and plant events</h2>{table(ev_tbl)}{unc_html}
<h2>Data quality</h2>
<p class='muted'>Analyser values during calibration, maintenance or faults are excluded from all statistics above.</p>
{table(masked_tbl)}
</body></html>"""


def weeks_in_data(con) -> list[str]:
    days = q(con, "select min(local_date) as a, max(local_date) as b from marts.mart_daily").iloc[0]
    out, d = [], pd.Timestamp(days.a).date()
    last = pd.Timestamp(days.b).date()
    while d + dt.timedelta(days=6 - d.weekday()) <= last:
        y, w, _ = d.isocalendar()
        if d.weekday() == 0 or not out:
            out.append(f"{y}-W{w:02d}")
        d += dt.timedelta(days=1)
    return sorted(set(out))


def write(con, iso: str) -> str:
    wk = Week(iso)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{PLANT}_{wk.iso}.html"
    path.write_text(build(con, wk), encoding="utf-8")
    return str(path)


def main():
    ap = argparse.ArgumentParser(description="Weekly UPW report")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--week", help="ISO week, e.g. 2026-W12")
    g.add_argument("--latest", action="store_true", help="last complete week in the data")
    g.add_argument("--all", action="store_true", help="every complete week in the data")
    a = ap.parse_args()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    weeks = weeks_in_data(con)
    todo = weeks if a.all else ([weeks[-1]] if a.latest else [a.week])
    for w in todo:
        print("written", write(con, w))


if __name__ == "__main__":
    main()

"""
UPW plant monitoring - demo app.

    uv run shiny run app/app.py --launch-browser

Pages: Overview · Trends · Event analysis (data around a maintenance event, before/after, Excel export)
· Analyser study · Weekly reports · Data health · Settings (fix diary classification, spec limits).
"""
from __future__ import annotations

import datetime as dt
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.offline  # noqa: E402
from shiny import App, reactive, render, req, ui  # noqa: E402

import charts  # noqa: E402
import data  # noqa: E402
import reference  # noqa: E402

WWW = Path(__file__).parent / "www"
WWW.mkdir(exist_ok=True)
if not (WWW / "plotly.min.js").exists():
    (WWW / "plotly.min.js").write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")

TAGS = data.tags()
TAG_LABEL = dict(zip(TAGS.tag, TAGS.description))
TAG_CHOICES = {}
for unit, g in TAGS.sort_values(["sequence", "display_order"]).groupby("unit_name", sort=False):
    TAG_CHOICES[unit] = dict(zip(g.tag, g.description))
FIRST_DAY, LAST_DAY = data.data_range()


def plot(fig) -> ui.HTML:
    return ui.HTML(fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True}))


def grid(df: pd.DataFrame, **kw):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M").str.replace(" 00:00", "", regex=False)
        elif pd.api.types.is_float_dtype(df[c]) or pd.api.types.is_integer_dtype(df[c]):
            whole = df[c].dropna().eq(df[c].dropna().round()).all() and df[c].abs().max() >= 1000
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:,.0f}" if whole else f"{v:.4g}")
    return render.DataGrid(df, width="100%", **kw)


def weeks() -> list[str]:
    out, d = [], FIRST_DAY
    while d + dt.timedelta(days=6 - d.weekday()) <= LAST_DAY:
        y, w, _ = d.isocalendar()
        out.append(f"{y}-W{w:02d}")
        d += dt.timedelta(days=7 - d.weekday())
    return out


CSS = ui.tags.style("""
:root { --ink:#0b0b0b; --muted:#52514e; --line:#e7e6e2; }
body { background:#f7f7f5; }
.navbar-brand { font-weight:600; }
.card { border:1px solid var(--line); box-shadow:none; }
.card-header { background:#fff; font-weight:600; border-bottom:1px solid var(--line); }
.lead-note { color:var(--muted); font-size:.92rem; margin:0 0 .6rem 0; }
.notice { border-left:4px solid #fab219; background:#fff8e6; padding:.6rem .9rem; margin-bottom:.8rem; white-space:pre-wrap; }
.notice.ok { border-left-color:#0ca30c; background:#eef8ee; } .notice.err { border-left-color:#d03b3b; background:#fdeeee; }
.bslib-value-box .value-box-value { font-size:1.8rem; }
iframe.report { width:100%; height:1400px; border:1px solid var(--line); background:#fff; }
""")

# ====================================================================== UI
overview = ui.nav_panel(
    "Overview",
    ui.output_ui("asof_note"),
    ui.layout_columns(
        ui.value_box("Spec exceedances, last 7 days", ui.output_text("vb_exc")),
        ui.value_box("Parameters drifting (trend)", ui.output_text("vb_trend")),
        ui.value_box("Maintenance events, last 30 days", ui.output_text("vb_events")),
        ui.value_box("Diary entries to classify", ui.output_text("vb_unclass")),
        fill=False,
    ),
    ui.layout_columns(
        ui.card(ui.card_header("Point of use - last full day"), ui.output_data_frame("pou_table")),
        ui.card(ui.card_header("Trend watch"),
                ui.p("Parameters whose level moved clearly away from normal in the unfavourable direction.",
                     class_="lead-note"),
                ui.output_data_frame("trend_watch")),
        col_widths=[6, 6],
    ),
    ui.card(ui.card_header("Recent spec and alert exceedances"), ui.output_data_frame("recent_exc")),
)

trends = ui.nav_panel(
    "Trends",
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_selectize("tr_tags", "Parameters", choices=TAG_CHOICES, multiple=True,
                               selected=["UPW1.POU.TOC", "UPW1.UV185.INTENSITY", "UPW1.RO1.PERM_TOC"]),
            ui.input_date_range("tr_dates", "Period", start=FIRST_DAY, end=LAST_DAY, min=FIRST_DAY, max=LAST_DAY),
            ui.input_radio_buttons("tr_grain", "Resolution", {"daily": "Daily", "hourly": "Hourly", "raw": "5 min"},
                                   selected="daily"),
            ui.input_checkbox("tr_events", "Show maintenance events", value=True),
            ui.p("5-min resolution is limited to 31 days.", class_="lead-note"),
            width=300,
        ),
        ui.output_ui("trend_charts"),
    ),
)

event = ui.nav_panel(
    "Event analysis",
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_radio_buttons("ev_mode", "Start from", {"event": "A diary event", "range": "A time range"}),
            ui.panel_conditional(
                "input.ev_mode === 'event'",
                ui.input_select("ev_type", "Event type", choices={}),
                ui.input_select("ev_id", "Event", choices={}),
            ),
            ui.panel_conditional(
                "input.ev_mode === 'range'",
                ui.input_date("ev_date", "Reference date", value=LAST_DAY - dt.timedelta(days=7)),
                ui.input_text("ev_time", "Reference time (HH:MM)", value="10:00"),
            ),
            ui.layout_columns(ui.input_numeric("ev_before", "Hours before", 24, min=1, max=24 * 60),
                              ui.input_numeric("ev_after", "Hours after", 24, min=1, max=24 * 60), col_widths=[6, 6]),
            ui.input_selectize("ev_tags", "Parameters", choices=TAG_CHOICES, multiple=True),
            ui.input_action_button("ev_go", "Load data", class_="btn-primary"),
            ui.download_button("ev_download", "Download Excel", class_="mt-2"),
            width=320,
        ),
        ui.output_ui("ev_header"),
        ui.card(ui.card_header("Before / after"),
                ui.p("Normal band = 5th-95th percentile before the event. Recovery = time until the value is back "
                     "in that band and stays there for 30 minutes. 10-s maintenance exports are used where they "
                     "exist, the 5-min archive elsewhere; analyser calibration periods are excluded.",
                     class_="lead-note"),
                ui.output_data_frame("ev_stats")),
        ui.output_ui("ev_charts"),
    ),
)

study = ui.nav_panel(
    "Analyser study",
    ui.card(ui.card_header("TOC analyser comparison at the point of use"),
            ui.p("Analyser B was installed next to analyser A for a comparison study. Both are compared on paired "
                 "5-minute values (calibration periods excluded): systematic offset (bias), spread of the "
                 "differences (limits of agreement) and drift over time.", class_="lead-note"),
            ui.output_ui("study_summary")),
    ui.layout_columns(ui.card(ui.output_ui("study_ba")), ui.card(ui.output_ui("study_drift")), col_widths=[6, 6]),
)

reports = ui.nav_panel(
    "Weekly reports",
    ui.layout_columns(
        ui.input_select("rp_week", "Week", choices=weeks(), selected=weeks()[-1]),
        ui.div(ui.input_action_button("rp_make", "Generate / refresh", class_="btn-primary"),
               ui.download_button("rp_download", "Download HTML", class_="ms-2"), style="padding-top:1.9rem"),
        col_widths=[3, 9],
    ),
    ui.output_ui("rp_view"),
)

health = ui.nav_panel(
    "Data health",
    ui.card(ui.card_header("Sources"),
            ui.p("Two export folders (5-min archive, 10-s maintenance exports) and the maintenance diary. "
                 "Identical files are recognised by content and skipped.", class_="lead-note"),
            ui.output_data_frame("h_sources")),
    ui.layout_columns(
        ui.card(ui.card_header("Analyser time excluded (calibration, maintenance, faults)"),
                ui.output_data_frame("h_masked")),
        ui.card(ui.card_header("Recent file loads"), ui.output_data_frame("h_log")),
        col_widths=[5, 7],
    ),
    ui.card(ui.output_ui("h_heatmap")),
)

settings = ui.nav_panel(
    "Settings",
    ui.layout_columns(
        ui.input_text("user", "Your name (for the change log)", value=reference.default_user()),
        ui.div(ui.input_action_button("rebuild", "Apply changes: rebuild warehouse", class_="btn-primary"),
               style="padding-top:1.9rem"),
        col_widths=[4, 8],
    ),
    ui.output_ui("msg"),
    ui.card(ui.card_header("Diary entries that could not be classified"),
            ui.p("These entries match no known keyword, so the event is missing from the analysis (and calibrations "
                 "would not be masked). Add a keyword once; every past and future entry using it is classified.",
                 class_="lead-note"),
            ui.output_data_frame("s_unclassified"),
            ui.layout_columns(ui.input_text("kw_text", "Keyword"), ui.input_select("kw_type", "Event type", choices={}),
                              col_widths=[6, 6]),
            ui.input_action_button("kw_add", "Add keyword", class_="btn-outline-primary", width="180px")),
    ui.card(ui.card_header("Specification and alert limits"),
            ui.p("Edit values in the table, then save and rebuild. All reports and checks use the limit valid "
                 "on each date (valid_from).", class_="lead-note"),
            ui.output_data_frame("s_limits"),
            ui.input_action_button("lim_save", "Save limits", class_="btn-outline-primary mt-2", width="180px")),
    ui.card(ui.card_header("Change log"), ui.output_data_frame("s_log")),
)

app_ui = ui.page_navbar(overview, trends, event, study, reports, health, settings,
                        title="UPW1 Monitoring", id="nav", fillable=False,
                        header=ui.TagList(ui.head_content(ui.tags.script(src="plotly.min.js")), CSS))


# ====================================================================== server
def server(input, output, session):
    version = reactive.value(0)
    message = reactive.value(None)
    window = reactive.value(None)          # (dataframe, t_event, title)

    @reactive.calc
    def events_all():
        version()
        return data.events()

    @reactive.calc
    def lims():
        version()
        return data.limits()

    # ------------------------------------------------------------ overview
    @render.ui
    def asof_note():
        return ui.p(f"Data up to {LAST_DAY:%d %b %Y}. 'Now' in this demo means the end of the data.", class_="lead-note")

    @render.text
    def vb_exc():
        version()
        e = data.exceedances(LAST_DAY - dt.timedelta(days=7))
        e = e[(e.severity == "spec") & ~e.maintenance_related]
        return str(len(e))

    @render.text
    def vb_trend():
        version()
        return str(int(data.trend_latest().flag.sum()))

    @render.text
    def vb_events():
        e = events_all()
        return str(int((pd.to_datetime(e.ts_local).dt.date >= LAST_DAY - dt.timedelta(days=30)).sum()))

    @render.text
    def vb_unclass():
        version()
        return str(len(data.unclassified()))

    @render.data_frame
    def pou_table():
        version()
        s = data.latest_day_status()
        lim = lims()
        lim = lim[lim.severity == "spec"]
        rows = []
        for r in s.itertuples():
            l = lim[lim.tag == r.tag]
            ok = None if l.empty else True
            for x in l.itertuples():
                ok &= (r.max_value <= x.limit_value) if x.limit_type == "max" else (r.min_value >= x.limit_value)
            rows.append({"Parameter": r.description, "Mean": r.mean_value, "Min": r.min_value, "Max": r.max_value,
                         "Unit": r.unit,
                         "Spec": ", ".join(f"{'≤' if x.limit_type == 'max' else '≥'} {x.limit_value:g}" for x in l.itertuples()),
                         "Status": "–" if ok is None else "✓ within spec" if ok else "▲ beyond spec"})
        return grid(pd.DataFrame(rows))

    @render.data_frame
    def trend_watch():
        version()
        t = data.trend_latest()
        t = t[t.flag]
        df = pd.DataFrame({"Parameter": t.description,
                           "Normal": [f"{v:.3g}" for v in t.baseline], "Now (smoothed)": [f"{v:.3g}" for v in t.ewma],
                           "Unit": t.unit,
                           "Days to spec (approx.)": [("" if pd.isna(v) else f"{max(v, 0):.0f}") for v in t.days_to_spec]})
        return grid(df)

    @render.data_frame
    def recent_exc():
        version()
        e = data.exceedances(LAST_DAY - dt.timedelta(days=60))
        df = pd.DataFrame({"Start": e.start_local, "Parameter": e.description, "Severity": e.severity,
                           "Limit": [f"{'≤' if r.limit_type == 'max' else '≥'} {r.limit_value:g} {r.unit}" for r in e.itertuples()],
                           "Hours": (e.duration_min / 60).round(1), "Peak": e.peak_value,
                           "During maintenance": np.where(e.maintenance_related, e.related_event, "")})
        return grid(df, height="320px")

    # ------------------------------------------------------------ trends
    @render.ui
    def trend_charts():
        version()
        sel = list(input.tr_tags())
        req(sel)
        d0, d1 = input.tr_dates()
        grain = input.tr_grain()
        if grain == "raw" and (d1 - d0).days > 31:
            return ui.div("5-min resolution is limited to 31 days - choose a shorter period or daily / hourly.",
                          class_="notice")
        df = data.series(sel, d0, d1, grain)
        ev = events_all()
        ev = ev[ev.is_maintenance & pd.to_datetime(ev.ts_local).dt.date.between(d0, d1)] if input.tr_events() else ev.iloc[0:0]
        out = []
        for tag in sel:
            t = TAGS.set_index("tag").loc[tag]
            g = df[df.tag == tag]
            evt = ev[ev.default_tags.str.contains(tag, regex=False)]
            fig = charts.trend_chart(g, t.description, t.unit, lims()[lims().tag == tag], evt, grain != "raw")
            out.append(ui.card(plot(fig), full_screen=True))
        return ui.TagList(*out)

    # ------------------------------------------------------------ event analysis
    @reactive.effect
    def _ev_types():
        e = events_all()
        types = e.groupby(["event_type", "event_label"]).size().reset_index()
        ui.update_select("ev_type", choices={"": "All types", **dict(zip(types.event_type, types.event_label))},
                         selected="filter_change")
        et = reference.read_seed("event_types")
        ui.update_select("kw_type", choices=dict(zip(et.event_type, et.label)))

    @reactive.effect
    def _ev_list():
        e = events_all()
        if input.ev_type():
            e = e[e.event_type == input.ev_type()]
        labels = pd.to_datetime(e.ts_local).dt.strftime("%Y-%m-%d %H:%M") + " · " + e.event_label + " · " + e.activity
        ui.update_select("ev_id", choices=dict(zip(e.event_id, labels)))

    @reactive.effect
    def _ev_defaults():
        req(input.ev_mode() == "event", input.ev_id())
        e = events_all().set_index("event_id").loc[input.ev_id()]
        ui.update_numeric("ev_before", value=float(e.window_before_h))
        ui.update_numeric("ev_after", value=float(e.window_after_h))
        ui.update_selectize("ev_tags", selected=[t for t in str(e.default_tags).split("|") if t])

    @reactive.effect
    @reactive.event(input.ev_go)
    def _ev_load():
        if input.ev_mode() == "event":
            req(input.ev_id())
            e = events_all().set_index("event_id").loc[input.ev_id()]
            t_event = pd.Timestamp(e.ts_local)
            title = f"{e.event_label} · {e.unit_name or ''} · {t_event:%a %d %b %Y %H:%M}"
            info = f"Diary: “{e.activity}” ({e.technician})" + (f" · {e.remark}" if e.remark else "")
        else:
            try:
                t = dt.datetime.strptime(input.ev_time().strip(), "%H:%M").time()
            except ValueError:
                message.set(("err", "Time must be HH:MM"))
                return
            t_event = pd.Timestamp(dt.datetime.combine(input.ev_date(), t))
            title, info = f"Custom window around {t_event:%a %d %b %Y %H:%M}", ""
        tags = list(input.ev_tags())
        if not tags:
            ui.notification_show("Choose at least one parameter.", type="warning")
            return
        t0 = t_event - pd.Timedelta(hours=float(input.ev_before() or 24))
        t1 = t_event + pd.Timedelta(hours=float(input.ev_after() or 24))
        df = data.window_data(tags, t0, t1)
        window.set(dict(df=df, t_event=t_event, t0=t0, t1=t1, title=title, info=info, tags=tags))

    @render.ui
    def ev_header():
        w = window()
        if w is None:
            return ui.div("Choose an event (or a time range) and parameters, then 'Load data'.", class_="notice")
        n_hi = (w["df"].source == "maintenance").sum() if len(w["df"]) else 0
        n_mask = (w["df"].quality_flag == "masked").sum() if len(w["df"]) else 0
        return ui.card(ui.h5(w["title"]), ui.p(w["info"], class_="lead-note"),
                       ui.p(f"Window {w['t0']:%d %b %H:%M} - {w['t1']:%d %b %H:%M} · {len(w['df']):,} values "
                            f"({n_hi:,} from 10-s maintenance exports; {n_mask:,} excluded as analyser calibration/fault)",
                            class_="lead-note"))

    @reactive.calc
    def ev_summary():
        w = window()
        req(w is not None and len(w["df"]))
        return data.before_after(w["df"], w["t_event"], TAGS)

    @render.data_frame
    def ev_stats():
        s = ev_summary()
        return grid(s.drop(columns=["tag"]).rename(columns={
            "parameter": "Parameter", "unit": "Unit", "mean_before": "Mean before", "normal_band": "Normal band",
            "worst_after": "Worst after", "mean_end_of_window": "Mean at end", "level_change": "Level change",
            "recovery": "Recovery", "resolution": "Data"}))

    @render.ui
    def ev_charts():
        w = window()
        req(w is not None and len(w["df"]))
        s = ev_summary().set_index("tag")
        out = []
        for tag in w["tags"]:
            g = w["df"][w["df"].tag == tag]
            if g.empty:
                continue
            t = TAGS.set_index("tag").loc[tag]
            band = None
            if tag in s.index:
                lo, hi = (float(x) for x in s.loc[tag, "normal_band"].split(" - "))
                band = (lo, hi)
            out.append(ui.card(plot(charts.window_chart(g, t.description, t.unit, w["t_event"],
                                                        lims()[lims().tag == tag], band)), full_screen=True))
        return ui.TagList(*out)

    @render.download_button(filename=lambda: f"UPW1_window_{window()['t_event']:%Y%m%d_%H%M}.xlsx" if window() else "UPW1_window.xlsx")
    def ev_download():
        w = window()
        req(w is not None and len(w["df"]))
        good = w["df"][w["df"].quality_flag == "good"]
        wide = good.pivot_table(index="ts_local", columns="tag", values="value", aggfunc="mean").reset_index()
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            pd.DataFrame({"item": ["window", "reference time", "from", "to", "note"],
                          "value": [w["title"], str(w["t_event"]), str(w["t0"]), str(w["t1"]),
                                    "local plant time; analyser calibration periods excluded"]}).to_excel(
                xw, sheet_name="info", index=False)
            ev_summary().to_excel(xw, sheet_name="before_after", index=False)
            wide.to_excel(xw, sheet_name="data", index=False)
            w["df"].to_excel(xw, sheet_name="data_long_with_source", index=False)
        yield buf.getvalue()

    # ------------------------------------------------------------ analyser study
    @reactive.calc
    def pairs():
        version()
        return data.analyzer_pairs()

    @render.ui
    def study_summary():
        p = pairs()
        req(len(p))
        diff = p.toc_b - p.toc_a
        d = data.analyzer_daily()
        x = (pd.to_datetime(d.local_date) - pd.to_datetime(d.local_date).min()).dt.days.to_numpy()
        slope = np.polyfit(x, d.mean_diff.to_numpy(), 1)[0] * 30 if len(d) > 5 else float("nan")
        corr = np.corrcoef(p.toc_a, p.toc_b)[0, 1]
        rel = (diff / p.toc_a).median() * 100
        return ui.layout_columns(
            ui.value_box("Paired values", f"{len(p):,}", ui.p(f"{p.ts_local.min():%d %b} - {p.ts_local.max():%d %b %Y}")),
            ui.value_box("Bias (B - A)", f"{diff.mean():+.3f} ppb", ui.p(f"median {rel:+.1f} % of A")),
            ui.value_box("95 % limits of agreement", f"{diff.mean() - 1.96 * diff.std():+.2f} .. {diff.mean() + 1.96 * diff.std():+.2f}",
                         ui.p("ppb")),
            ui.value_box("Drift of B vs A", f"{slope:+.3f} ppb/month", ui.p(f"correlation r = {corr:.3f}")),
            fill=False)

    @render.ui
    def study_ba():
        return plot(charts.agreement_chart(pairs()))

    @render.ui
    def study_drift():
        version()
        return plot(charts.drift_chart(data.analyzer_daily()))

    # ------------------------------------------------------------ weekly reports
    def report_path(week: str) -> Path:
        return data.REPORTS / f"UPW1_{week}.html"

    last_click = {"n": 0}                    # plain dict: remembers which button click was already handled

    @render.ui
    def rp_view():
        # Generation happens inside this output (not in a separate effect with its own progress bar),
        # so the browser only ever sees one output updating - no race between the two.
        clicks = input.rp_make()
        week = input.rp_week()
        if clicks > last_click["n"]:
            last_click["n"] = clicks
            data.close()                     # the report opens its own read-only connection
            ok, log = reference.run_report(week)
            if not ok:
                return ui.div("Report failed:\n" + log[-800:], class_="notice err")
        path = report_path(week)
        if not path.exists():
            return ui.div("No report for this week yet - click 'Generate / refresh'.", class_="notice")
        return ui.tags.iframe(srcdoc=path.read_text(encoding="utf-8"), class_="report")

    @render.download_button(filename=lambda: f"UPW1_{input.rp_week()}.html")
    def rp_download():
        path = report_path(input.rp_week())
        req(path.exists())
        yield path.read_bytes()

    # ------------------------------------------------------------ data health
    @render.data_frame
    def h_sources():
        version()
        return grid(data.health())

    @render.data_frame
    def h_masked():
        version()
        m = data.masked_summary()
        m["hours"] = m.hours.round(1)
        return grid(m, height="300px")

    @render.data_frame
    def h_log():
        version()
        return grid(data.load_log(), height="300px")

    @render.ui
    def h_heatmap():
        version()
        return plot(charts.completeness_heatmap(data.completeness(), TAG_LABEL))

    # ------------------------------------------------------------ settings
    @render.ui
    def msg():
        m = message()
        return ui.div(m[1], class_=f"notice {m[0]}") if m else None

    @render.data_frame
    def s_unclassified():
        version()
        u = data.unclassified()
        return grid(u[["resolution_status", "ts_local", "unit_text", "activity", "technician"]], selection_mode="row")

    @reactive.effect
    def _prefill_kw():
        sel = s_unclassified.data_view(selected=True)
        if not sel.empty:
            ui.update_text("kw_text", value=str(sel.activity.iloc[0]).split()[0])

    @reactive.effect
    @reactive.event(input.kw_add)
    def _kw_add():
        err = reference.add_event_keyword(input.kw_text(), input.kw_type(), input.user() or "unknown")
        message.set(("err", f"Keyword not added: {err}") if err else
                    ("ok", f"Keyword '{input.kw_text()}' -> {input.kw_type()} saved. Click 'Apply changes' to rebuild."))

    @render.data_frame
    def s_limits():
        version()
        return render.DataGrid(reference.read_seed("spec_limits"), editable=True, width="100%", height="420px")

    @reactive.effect
    @reactive.event(input.lim_save)
    def _lim_save():
        errors = reference.save_spec_limits(s_limits.data_view(), input.user() or "unknown")
        if errors == ["nothing changed"]:
            message.set(("err", "Nothing changed."))
        elif errors:
            message.set(("err", "Limits not saved:\n" + "\n".join(errors)))
        else:
            message.set(("ok", "Limits saved. Click 'Apply changes' to rebuild."))

    @reactive.effect
    @reactive.event(input.rebuild)
    def _rebuild():
        with ui.Progress() as p:
            p.set(0.3, message="Rebuilding the warehouse (about 30 s) ...")
            data.close()
            ok, log = reference.rebuild()
        version.set(version() + 1)
        message.set(("ok" if ok else "err", ("Rebuild finished.\n" if ok else "Rebuild FAILED.\n") + log))

    @render.data_frame
    def s_log():
        version(); message()
        return grid(reference.change_log(), height="220px")


app = App(app_ui, server, static_assets=WWW)

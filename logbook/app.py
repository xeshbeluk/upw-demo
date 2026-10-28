"""
Experiment logbook - demo app.

    uv run shiny run logbook/app.py --port 8766 --launch-browser

Experiments · Upload (instrument exports, formats learned once) · Plot & export (any period, PNG / PDF / Excel)
· Events (filter changes, CIPs, notes ... drawn as line, note or shaded period) · Saved plots
"""
from __future__ import annotations

import base64
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.offline  # noqa: E402
from shiny import App, reactive, render, req, ui  # noqa: E402

from logbook import parsing, service, store  # noqa: E402
from logbook.config import USB_DIR  # noqa: E402
from logbook.seed import LEAVE_FOR_DEMO  # noqa: E402

WWW = Path(__file__).parent / "www"
WWW.mkdir(exist_ok=True)
if not (WWW / "plotly.min.js").exists():
    (WWW / "plotly.min.js").write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")


def plot(fig) -> ui.HTML:
    return ui.HTML(fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True}))


def grid(df: pd.DataFrame, **kw):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%d.%m.%Y %H:%M").fillna("")
        elif pd.api.types.is_float_dtype(df[c]) or pd.api.types.is_integer_dtype(df[c]):
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:,.0f}" if float(v).is_integer() else f"{v:.4g}")
    return render.DataGrid(df, width="100%", **kw)


def img(data: bytes) -> ui.Tag:
    return ui.tags.img(src="data:image/png;base64," + base64.b64encode(data).decode(), style="width:100%")


def parse_time(text: str) -> dt.time | None:
    for f in ("%H:%M", "%H:%M:%S", "%H.%M"):
        try:
            return dt.datetime.strptime((text or "").strip(), f).time()
        except ValueError:
            pass
    return None


def experiment_choices() -> dict:
    e = store.experiments()
    return dict(zip(e.experiment_id, e.experiment_id + " · " + e.title))


CSS = ui.tags.style("""
:root { --ink:#0b0b0b; --muted:#52514e; --line:#e7e6e2; }
body { background:#f7f7f5; }
.navbar-brand { font-weight:600; }
.card { border:1px solid var(--line); box-shadow:none; }
.card-header { background:#fff; font-weight:600; border-bottom:1px solid var(--line); }
.lead-note { color:var(--muted); font-size:.92rem; margin:0 0 .6rem 0; }
.notice { border-left:4px solid #fab219; background:#fff8e6; padding:.6rem .9rem; margin-bottom:.8rem; white-space:pre-wrap; }
.notice.ok { border-left-color:#0ca30c; background:#eef8ee; } .notice.err { border-left-color:#d03b3b; background:#fdeeee; }
.topbar { background:#fff; border-bottom:1px solid var(--line); padding:.6rem 1rem .1rem 1rem; margin:-.5rem -1rem 1rem -1rem; }
pre.rawfile { background:#fbfbfa; border:1px solid var(--line); padding:.5rem; font-size:.78rem; max-height:260px; overflow:auto; }
.notice.list { white-space:normal; }
.btn-row > * { margin-right:.5rem; margin-bottom:.4rem; }
""")

# ====================================================================== UI
p_experiments = ui.nav_panel(
    "Experiments",
    ui.card(ui.card_header("Experiments"),
            ui.p("Click a row to open the experiment. All other pages work on the experiment chosen at the top.",
                 class_="lead-note"),
            ui.output_data_frame("exp_table"),
            ui.div(ui.input_action_button("exp_new", "New experiment", class_="btn-outline-primary"), class_="btn-row")),
    ui.output_ui("exp_detail"),
)

p_upload = ui.nav_panel(
    "Upload",
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_file("up_files", "Instrument export files (.csv, .txt)", multiple=True,
                          accept=[".csv", ".CSV", ".txt", ".TXT", ".dat", ".DAT"], button_label="Choose files ..."),
            ui.p("Files of a known format are recognised by their column header. A new format is set up once; "
                 "the original files are archived unchanged. Data already stored (overlapping exports) is skipped.",
                 class_="lead-note"),
            ui.hr(),
            ui.p(ui.strong("Demo: files on the 'USB stick'")),
            ui.p("Not uploaded yet - download one and upload it here.", class_="lead-note"),
            ui.input_select("demo_file", None, choices=sorted(LEAVE_FOR_DEMO)),
            ui.download_button("demo_dl", "Download demo file", class_="btn-sm"),
            width=330, open="open"),
        ui.output_ui("up_status"),
        ui.output_ui("up_setup"),
        ui.output_ui("up_result"),
    ),
)

p_plot = ui.nav_panel(
    "Plot & export",
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_selectize("pe_params", "Parameters", choices=[], multiple=True),
            ui.input_radio_buttons("pe_mode", "Period", {"range": "From - to", "event": "Around an event"}),
            ui.panel_conditional(
                "input.pe_mode === 'range'",
                ui.layout_columns(ui.input_date("pe_d0", "From", format="dd.mm.yyyy"),
                                  ui.input_text("pe_t0", "Time", "00:00"), col_widths=[7, 5]),
                ui.layout_columns(ui.input_date("pe_d1", "To", format="dd.mm.yyyy"),
                                  ui.input_text("pe_t1", "Time", "23:59"), col_widths=[7, 5]),
                ui.input_action_link("pe_all", "whole experiment"),
            ),
            ui.panel_conditional(
                "input.pe_mode === 'event'",
                ui.input_select("pe_event", "Event", choices={}),
                ui.layout_columns(ui.input_numeric("pe_hb", "Hours before", 24, min=1),
                                  ui.input_numeric("pe_ha", "Hours after", 72, min=1), col_widths=[6, 6]),
            ),
            ui.input_checkbox_group("pe_cats", "Show events", choices=[]),
            ui.input_checkbox("pe_flagged", "Include values flagged by the instrument (calibration, error)", False),
            ui.input_action_button("pe_show", "Show plot", class_="btn-primary"),
            ui.hr(),
            ui.p(ui.strong("Download this plot")),
            ui.div(ui.download_button("pe_png", "PNG", class_="btn-sm"), ui.download_button("pe_pdf", "PDF", class_="btn-sm"),
                   ui.download_button("pe_xlsx", "Excel", class_="btn-sm"), class_="btn-row"),
            ui.input_text("pe_name", "Save to plot library as", placeholder="e.g. CIP 3 recovery"),
            ui.input_action_button("pe_save", "Save plot", class_="btn-outline-primary btn-sm"),
            width=340, open="open"),
        ui.output_ui("pe_chart"),
    ),
)

p_events = ui.nav_panel(
    "Events",
    ui.card(ui.card_header("Events"),
            ui.p("Filter changes, cleanings, calibrations, set-point changes, remarks ... Events marked 'all experiments' "
                 "(e.g. a plant shutdown) appear on every experiment's plots. Choose per event how it is drawn.",
                 class_="lead-note"),
            ui.div(ui.input_action_button("ev_add", "+ Add event", class_="btn-primary"),
                   ui.input_action_button("ev_edit", "Edit selected", class_="btn-outline-secondary"),
                   ui.input_action_button("ev_del", "Delete selected", class_="btn-outline-danger"), class_="btn-row"),
            ui.output_data_frame("ev_table")),
)

p_library = ui.nav_panel(
    "Saved plots",
    ui.card(ui.card_header("Plot library"),
            ui.p("Updated automatically after every upload (long-term plot, plot of each new file) and when you save "
                 "a plot. Files are kept in logbook_data/plots.", class_="lead-note"),
            ui.output_data_frame("lib_table"),
            ui.div(ui.download_button("lib_png", "Download PNG", class_="btn-sm"),
                   ui.download_button("lib_pdf", "Download PDF", class_="btn-sm"), class_="btn-row")),
    ui.output_ui("lib_preview"),
)

topbar = ui.div(ui.layout_columns(
    ui.input_select("exp", "Experiment", choices=experiment_choices()),
    ui.input_text("user", "Your name (stored with uploads and events)", value=store.default_user()),
    col_widths=[6, 4]), class_="topbar")

app_ui = ui.page_navbar(p_experiments, p_upload, p_plot, p_events, p_library, title="Experiment logbook", id="nav",
                        fillable=False,
                        header=ui.TagList(ui.head_content(ui.tags.script(src="plotly.min.js")), CSS, topbar))


# ====================================================================== server
def server(input, output, session):
    version = reactive.value(0)          # bumped after every change to the stored data
    pending = reactive.value([])         # analysed upload files waiting for import
    results = reactive.value(None)       # last import results
    view = reactive.value(None)          # current Plot & export view
    editing = reactive.value(None)       # event_id being edited (None = new)

    def bump():
        version.set(version() + 1)

    def user() -> str:
        return (input.user() or "unknown").strip()

    # ------------------------------------------------------------ experiments
    @reactive.calc
    def exps():
        version()
        return store.experiments()

    @render.data_frame
    def exp_table():
        e = exps()
        df = e[["experiment_id", "title", "owner", "start_date", "files", "values_stored", "data_from", "data_to",
                "last_upload"]].rename(columns={"experiment_id": "Code", "title": "Title", "owner": "Owner",
                                                "start_date": "Start", "files": "Files", "values_stored": "Values",
                                                "data_from": "Data from", "data_to": "Data to", "last_upload": "Last upload"})
        df["Start"] = pd.to_datetime(df["Start"]).dt.strftime("%d.%m.%Y")
        return grid(df, selection_mode="row")

    @reactive.effect
    def _pick_exp():
        sel = exp_table.data_view(selected=True)
        if not sel.empty:
            ui.update_select("exp", selected=sel["Code"].iloc[0])

    @render.ui
    def exp_detail():
        version()
        exp = input.exp()
        req(exp)
        e = exps().set_index("experiment_id").loc[exp]
        lt = service.longterm_view(exp)
        chart = plot(service.plotly(lt)) if lt else ui.div("No data uploaded yet.", class_="notice")
        return ui.TagList(
            ui.card(ui.card_header(f"{exp} · {e.title}"),
                    ui.p(e.description or "", class_="lead-note"),
                    ui.p(f"Owner: {e.owner} · started {pd.Timestamp(e.start_date):%d.%m.%Y} · status: {e.status}",
                         class_="lead-note"),
                    chart, full_screen=True),
            ui.card(ui.card_header("Uploaded files"), ui.output_data_frame("exp_files")))

    @render.data_frame
    def exp_files():
        version()
        f = store.files(input.exp())
        f = f[["uploaded_at", "file_name", "status", "layout_name", "values_new", "values_overlap", "values_flagged",
               "t_min", "t_max", "uploaded_by"]].rename(columns={
                   "uploaded_at": "Uploaded", "file_name": "File", "status": "Status", "layout_name": "Format",
                   "values_new": "New values", "values_overlap": "Overlap skipped", "values_flagged": "Flagged",
                   "t_min": "Data from", "t_max": "Data to", "uploaded_by": "By"})
        return grid(f, height="360px")

    @reactive.effect
    @reactive.event(input.exp_new)
    def _exp_modal():
        ui.modal_show(ui.modal(
            ui.layout_columns(ui.input_text("ne_code", "Code", placeholder="EXP-2026-11"),
                              ui.input_date("ne_start", "Start date", format="dd.mm.yyyy"), col_widths=[6, 6]),
            ui.input_text("ne_title", "Title", width="100%"),
            ui.input_text("ne_owner", "Owner", value=user()),
            ui.input_text_area("ne_desc", "Description / question", width="100%", rows=3),
            ui.output_ui("ne_msg"),
            title="New experiment", easy_close=True,
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("ne_save", "Create", class_="btn-primary"))))

    ne_error = reactive.value("")

    @render.ui
    def ne_msg():
        return ui.div(ne_error(), class_="notice err") if ne_error() else None

    @reactive.effect
    @reactive.event(input.ne_save)
    def _exp_save():
        err = store.add_experiment(input.ne_code(), input.ne_title(), input.ne_owner(), input.ne_start(), input.ne_desc())
        if err:
            ne_error.set(err)
            return
        ne_error.set("")
        ui.modal_remove()
        bump()
        ui.update_select("exp", choices=experiment_choices(), selected=input.ne_code().strip().upper())

    # ------------------------------------------------------------ upload
    @render.download_button(filename=lambda: input.demo_file())
    def demo_dl():
        yield (USB_DIR / input.demo_file()).read_bytes()

    def analyse(files: list[dict]) -> list[dict]:
        known = store.layouts()
        out = []
        for f in files:
            dup = store.already_imported(input.exp(), f["sha"])
            lay = parsing.find_layout(f["raw"], known)
            f = {**f, "layout": lay,
                 "state": "duplicate" if dup else "known" if lay else "new",
                 "detail": f"already uploaded as '{dup}'" if dup else (f"format: {lay.name}" if lay else "new format - set up below")}
            out.append(f)
        return out

    @reactive.effect
    @reactive.event(input.up_files)
    def _received():
        files = []
        for f in input.up_files() or []:
            raw = Path(f["datapath"]).read_bytes()
            files.append({"name": f["name"], "raw": raw, "sha": store.sha1(raw), "size": len(raw)})
        results.set(None)
        pending.set(analyse(files))

    @reactive.effect
    @reactive.event(input.exp)
    def _reanalyse():
        if pending():
            pending.set(analyse(pending()))

    @render.ui
    def up_status():
        p = pending()
        if not p:
            return ui.div("Choose one or several export files (left). They are checked first - nothing is stored "
                          "until you click Import.", class_="notice") if results() is None else None
        df = pd.DataFrame({"File": [f["name"] for f in p], "Size": [f"{f['size'] / 1e6:.1f} MB" for f in p],
                           "Check": [f["detail"] for f in p]})
        n = sum(f["state"] == "known" for f in p)
        return ui.card(ui.card_header(f"Files to import into {input.exp()}"),
                       ui.HTML(df.to_html(index=False, classes="table table-sm")),
                       ui.div(ui.input_action_button("up_import", f"Import {n} recognised file(s)", class_="btn-primary",
                                                     disabled=n == 0),
                              ui.input_action_button("up_clear", "Clear list", class_="btn-outline-secondary"),
                              class_="btn-row"))

    @reactive.effect
    @reactive.event(input.up_clear)
    def _clear():
        pending.set([])

    def do_import(files: list[dict]) -> None:
        exp = input.exp()
        res = []
        with ui.Progress(min=0, max=len(files) + 1) as pr:
            for i, f in enumerate(files):
                pr.set(i, message=f"Importing {f['name']} ...")
                try:
                    res.append(store.import_file(exp, f["name"], f["raw"], f["layout"], user()))
                except Exception as e:  # noqa: BLE001 - show the problem, keep going with the other files
                    res.append({"file": f["name"], "status": "failed", "message": str(e)})
            pr.set(len(files), message="Updating plots ...")
            snaps = service.snapshots_after_upload(exp, res)
        done = {f["name"] for f in files}
        pending.set([f for f in pending() if f["name"] not in done])
        results.set({"res": res, "snaps": snaps})
        bump()

    @reactive.effect
    @reactive.event(input.up_import)
    def _import():
        do_import([f for f in pending() if f["state"] == "known"])

    @render.ui
    def up_result():
        r = results()
        if r is None:
            return None
        rows = [ui.tags.li(ui.strong(x["file"]), f" - {x['status']}: {x['message']}") for x in r["res"]]
        pics = [ui.div(ui.p(Path(p).name, class_="lead-note"), img(Path(p).read_bytes())) for p in r["snaps"]]
        ok = all(x["status"] != "failed" for x in r["res"])
        return ui.card(ui.card_header("Import result"), ui.div(ui.tags.ul(*rows, style="margin:0"), class_="notice list " + ("ok" if ok else "err")),
                       ui.p("Saved plots (also in 'Saved plots'):", class_="lead-note"), *pics)

    # --- new format set-up
    @reactive.calc
    def new_file():
        return next((f for f in pending() if f["state"] == "new"), None)

    @reactive.calc
    def guess():
        f = new_file()
        req(f)
        return parsing.sniff(f["raw"])

    @render.ui
    def up_setup():
        f = new_file()
        if f is None:
            return None
        lay, notes = guess()
        text, _ = parsing.decode(f["raw"])
        head = "\n".join(f"{i + 1:>3} | {ln}" for i, ln in enumerate(parsing.lines_of(text)[:16]))
        cols = lay.signature
        return ui.card(
            ui.card_header(f"New file format: {f['name']}"),
            ui.p("This layout has not been seen before. Check the settings (they were guessed from the file), "
                 "look at the preview, give the format a name and save it. Later files with the same columns are "
                 "recognised automatically.", class_="lead-note"),
            ui.div("\n".join(notes), class_="notice"),
            ui.layout_columns(
                ui.div(ui.p(ui.strong("Start of the file")), ui.tags.pre(head, class_="rawfile")),
                ui.div(
                    ui.input_text("nf_name", "Name of this format", value=Path(f["name"]).stem.split("_")[0] + " export"),
                    ui.layout_columns(
                        ui.input_select("nf_delim", "Separator", {k: v for k, v in parsing.DELIM_NAMES.items()},
                                        selected=lay.delimiter),
                        ui.input_select("nf_dec", "Decimal mark", {".": "point 1.5", ",": "comma 1,5"}, selected=lay.decimal),
                        ui.input_numeric("nf_header", "Header in line", lay.header_row + 1, min=1), col_widths=[4, 4, 4]),
                    ui.layout_columns(
                        ui.input_select("nf_date", "Time stamp column", cols, selected=lay.date_col or None),
                        ui.input_select("nf_time", "Separate time column", {"": "(none)", **{c: c for c in cols}},
                                        selected=lay.time_col), col_widths=[6, 6]),
                    ui.input_text("nf_fmt", "Time stamp format (e.g. %d.%m.%Y %H:%M:%S)", value=lay.datetime_format),
                    ui.layout_columns(
                        ui.input_select("nf_status", "Instrument status column", {"": "(none)", **{c: c for c in cols}},
                                        selected=lay.status_col),
                        ui.input_text("nf_ok", "Status values meaning OK", value=", ".join(lay.status_ok)), col_widths=[6, 6]),
                    ui.input_text("nf_prefix", "Prefix for parameter names (optional)", placeholder="e.g. Grab sample: "),
                ), col_widths=[6, 6]),
            ui.p(ui.strong("Preview with these settings")),
            ui.output_ui("nf_preview"),
            ui.div(ui.input_action_button("nf_save", "Save format and import this file", class_="btn-primary"),
                   class_="btn-row"))

    def current_layout() -> parsing.Layout:
        f = new_file()
        text, _ = parsing.decode(f["raw"])
        hdr = max(int(input.nf_header() or 1) - 1, 0)
        lines = parsing.lines_of(text)
        sig = parsing.split_header(lines[hdr], input.nf_delim()) if hdr < len(lines) else []
        return parsing.Layout(name=input.nf_name().strip(), delimiter=input.nf_delim(), decimal=input.nf_dec(),
                              header_row=hdr, date_col=input.nf_date() or "", time_col=input.nf_time() or "",
                              datetime_format=input.nf_fmt().strip(), status_col=input.nf_status() or "",
                              status_ok=[s.strip() for s in (input.nf_ok() or "").split(",") if s.strip()],
                              prefix=input.nf_prefix() or "", signature=sig)

    @reactive.effect
    def _nf_columns():
        """Separator or header line changed -> offer the columns of that header line."""
        req(new_file(), input.nf_delim(), input.nf_header())
        cols = current_layout().signature
        with reactive.isolate():
            d, t, s = input.nf_date(), input.nf_time(), input.nf_status()
        ui.update_select("nf_date", choices=cols, selected=d if d in cols else None)
        ui.update_select("nf_time", choices={"": "(none)", **{c: c for c in cols}}, selected=t if t in cols else "")
        ui.update_select("nf_status", choices={"": "(none)", **{c: c for c in cols}}, selected=s if s in cols else "")

    @render.ui
    def nf_preview():
        req(new_file(), input.nf_fmt())
        try:
            long, st = parsing.parse(new_file()["raw"], current_layout())
        except Exception as e:  # noqa: BLE001
            return ui.div(f"Cannot read the file with these settings: {e}", class_="notice err")
        if long.empty:
            return ui.div("No values could be read - check the time stamp column and format.", class_="notice err")
        wide = long.pivot_table(index="ts", columns="parameter", values="value", aggfunc="first").head(8)
        units = long.drop_duplicates("parameter").set_index("parameter").unit
        wide.columns = [f"{c} [{units[c]}]" if units[c] else c for c in wide.columns]
        msg = (f"{st['rows']:,} rows · {st['parameters']} parameters · {long.ts.min():%d.%m.%Y %H:%M} - "
               f"{long.ts.max():%d.%m.%Y %H:%M}" + (f" · {st['bad_timestamps']} rows with unreadable time" if st["bad_timestamps"] else "")
               + (f" · {int(long.flag.notna().sum())} values flagged" if long.flag.notna().any() else ""))
        wide.index.name = "time"
        return ui.TagList(ui.div(msg, class_="notice ok" if not st["bad_timestamps"] else "notice"),
                          ui.HTML(wide.reset_index().to_html(index=False, classes="table table-sm", float_format=lambda v: f"{v:.4g}")))

    @reactive.effect
    @reactive.event(input.nf_save)
    def _nf_save():
        lay = current_layout()
        try:
            long, _ = parsing.parse(new_file()["raw"], lay)
            assert not long.empty, "no values could be read"
        except Exception as e:  # noqa: BLE001
            ui.notification_show(f"Not saved: {e}", type="error")
            return
        err = store.save_layout(lay, user())
        if err:
            ui.notification_show(err, type="error")
            return
        f = {**new_file(), "layout": lay, "state": "known"}
        rest = analyse([x for x in pending() if x["name"] != f["name"]])    # other files of the same format are now known
        pending.set([f] + rest)
        do_import([f])

    # ------------------------------------------------------------ plot & export
    @reactive.effect
    def _pe_setup():
        version()
        exp = input.exp()
        req(exp)
        params = list(store.parameters(exp).parameter)
        ui.update_selectize("pe_params", choices=params, selected=params[:4])
        span = store.data_span(exp)
        if span:
            ui.update_date("pe_d0", value=span[0].date(), min=span[0].date(), max=span[1].date())
            ui.update_date("pe_d1", value=span[1].date(), min=span[0].date(), max=span[1].date())
        ev = store.events(exp)
        ui.update_select("pe_event", choices=dict(zip(ev.event_id.astype(str),
                                                      pd.to_datetime(ev.start_ts).dt.strftime("%d.%m.%Y %H:%M") + " · " + ev.label)))
        cats = list(store.categories().category)
        ui.update_checkbox_group("pe_cats", choices=cats, selected=cats)

    @reactive.effect
    @reactive.event(input.pe_all)
    def _pe_all():
        span = store.data_span(input.exp())
        if span:
            ui.update_date("pe_d0", value=span[0].date())
            ui.update_text("pe_t0", value=f"{span[0]:%H:%M}")
            ui.update_date("pe_d1", value=span[1].date())
            ui.update_text("pe_t1", value=f"{span[1] + pd.Timedelta(minutes=1):%H:%M}")

    @reactive.effect
    @reactive.event(input.pe_show)
    def _pe_build():
        exp, params = input.exp(), list(input.pe_params())
        if not params:
            ui.notification_show("Choose at least one parameter.", type="warning")
            return
        if input.pe_mode() == "event":
            ev = store.events(exp)
            row = ev[ev.event_id.astype(str) == input.pe_event()]
            if row.empty:
                ui.notification_show("Choose an event.", type="warning")
                return
            t = pd.Timestamp(row.start_ts.iloc[0])
            t0, t1 = t - pd.Timedelta(hours=input.pe_hb() or 24), t + pd.Timedelta(hours=input.pe_ha() or 72)
        else:
            a, b = parse_time(input.pe_t0()), parse_time(input.pe_t1())
            if a is None or b is None or input.pe_d0() is None or input.pe_d1() is None:
                ui.notification_show("Enter dates and times as HH:MM.", type="warning")
                return
            t0 = pd.Timestamp(dt.datetime.combine(input.pe_d0(), a))
            t1 = pd.Timestamp(dt.datetime.combine(input.pe_d1(), b))
            if t1 <= t0:
                ui.notification_show("'To' must be after 'From'.", type="warning")
                return
        view.set(service.build(service.View(exp, params, t0, t1, input.pe_flagged(), list(input.pe_cats()))))

    @render.ui
    def pe_chart():
        version()
        v = view()
        if v is None:
            return ui.div("Choose parameters and a period (or an event), then 'Show plot'. "
                          "The downloads use exactly what is shown.", class_="notice")
        if v.data.empty:
            return ui.div("No data in this period.", class_="notice")
        return ui.card(plot(service.plotly(v)), full_screen=True)

    def need_view():
        v = view()
        req(v is not None and not v.data.empty)
        return v

    @render.download_button(filename=lambda: f"{service.file_stem(view())}.png" if view() else "plot.png")
    def pe_png():
        yield service.png(need_view())

    @render.download_button(filename=lambda: f"{service.file_stem(view())}.pdf" if view() else "plot.pdf")
    def pe_pdf():
        yield service.pdf(need_view())

    @render.download_button(filename=lambda: f"{service.file_stem(view())}.xlsx" if view() else "data.xlsx")
    def pe_xlsx():
        with ui.Progress() as p:
            p.set(0.5, message="Writing Excel file ...")
            data = service.excel(need_view())
        yield data

    @reactive.effect
    @reactive.event(input.pe_save)
    def _pe_save():
        v = view()
        if v is None or v.data.empty:
            ui.notification_show("Show a plot first.", type="warning")
            return
        p = service.save_to_library(v, input.pe_name() or "plot")
        ui.notification_show(f"Saved as {p.name} (+ PDF) - see 'Saved plots'.", type="message")
        bump()

    # ------------------------------------------------------------ events
    @reactive.calc
    def ev_df():
        version()
        return store.events(input.exp())

    @render.data_frame
    def ev_table():
        e = ev_df()
        df = pd.DataFrame({"Start": e.start_ts, "End": e.end_ts, "Category": e.category, "Label": e.label,
                           "Drawn as": e["style"].map(store.STYLES), "Applies to": e.scope, "Note": e.note.fillna(""),
                           "Entered by": e.created_by})
        return grid(df, selection_mode="row", height="560px")

    def selected_event():
        sel = ev_table.cell_selection()["rows"]
        if not sel:
            ui.notification_show("Select an event in the table first.", type="warning")
            return None
        return ev_df().iloc[list(sel)[0]]

    def event_modal(e=None):
        cats = store.categories()
        start = pd.Timestamp(e.start_ts) if e is not None else pd.Timestamp.now().floor("min")
        end = pd.Timestamp(e.end_ts) if e is not None and pd.notna(e.end_ts) else None
        cat = e.category if e is not None else cats.category.iloc[0]
        style = e["style"] if e is not None else cats.set_index("category").loc[cat, "default_style"]
        scope = "all" if e is not None and pd.isna(e.experiment_id) else "exp"
        ui.modal_show(ui.modal(
            ui.input_radio_buttons("me_scope", "Applies to", {"exp": f"this experiment ({input.exp()})",
                                                              "all": "all experiments (plant-wide event)"},
                                   selected=scope, inline=True),
            ui.layout_columns(ui.input_select("me_cat", "Category", list(cats.category), selected=cat),
                              ui.input_text("me_label", "Label", value=e.label if e is not None else "",
                                            placeholder="e.g. Prefilter cartridge changed"), col_widths=[5, 7]),
            ui.layout_columns(ui.input_date("me_d0", "Date", value=start.date(), format="dd.mm.yyyy"),
                              ui.input_text("me_t0", "Time (HH:MM)", value=f"{start:%H:%M}"),
                              ui.input_checkbox("me_has_end", "Has an end (period)", value=end is not None),
                              col_widths=[4, 3, 5]),
            ui.panel_conditional("input.me_has_end",
                                 ui.layout_columns(ui.input_date("me_d1", "End date", value=(end or start).date(),
                                                                 format="dd.mm.yyyy"),
                                                   ui.input_text("me_t1", "End time", value=f"{(end or start):%H:%M}"),
                                                   col_widths=[4, 3])),
            ui.input_radio_buttons("me_style", "Show on plots as", store.STYLES, selected=style, inline=True),
            ui.input_text_area("me_note", "Note (optional)", value=(e.note or "") if e is not None else "",
                               width="100%", rows=2),
            ui.output_ui("me_msg"),
            title="Edit event" if e is not None else "Add event", easy_close=True, size="l",
            footer=ui.TagList(ui.modal_button("Cancel"), ui.input_action_button("me_save", "Save", class_="btn-primary"))))

    me_error = reactive.value("")

    @render.ui
    def me_msg():
        return ui.div(me_error(), class_="notice err") if me_error() else None

    @reactive.effect
    @reactive.event(input.ev_add)
    def _ev_add():
        editing.set(None)
        me_error.set("")
        event_modal()

    @reactive.effect
    @reactive.event(input.me_cat)
    def _cat_default_style():
        if editing() is None:          # new event: follow the category's usual display
            ui.update_radio_buttons("me_style", selected=store.categories().set_index("category").loc[input.me_cat(), "default_style"])

    @reactive.effect
    @reactive.event(input.ev_edit)
    def _ev_edit():
        e = selected_event()
        if e is not None:
            editing.set(int(e.event_id))
            me_error.set("")
            event_modal(e)

    @reactive.effect
    @reactive.event(input.me_save)
    def _ev_save():
        a = parse_time(input.me_t0())
        if a is None or input.me_d0() is None:
            me_error.set("Enter the date and the time as HH:MM")
            return
        start = dt.datetime.combine(input.me_d0(), a)
        end = None
        if input.me_has_end():
            b = parse_time(input.me_t1())
            if b is None or input.me_d1() is None:
                me_error.set("Enter the end date and time as HH:MM")
                return
            end = dt.datetime.combine(input.me_d1(), b)
        err = store.save_event(editing(), input.exp() if input.me_scope() == "exp" else None, start, end,
                               input.me_label(), input.me_cat(), input.me_style(), input.me_note(), user())
        if err:
            me_error.set(err)
            return
        ui.modal_remove()
        ui.notification_show("Event saved - it appears on all plots from now on.", type="message")
        bump()

    @reactive.effect
    @reactive.event(input.ev_del)
    def _ev_del():
        e = selected_event()
        if e is None:
            return
        editing.set(int(e.event_id))
        ui.modal_show(ui.modal(f"Delete '{e.label}' ({pd.Timestamp(e.start_ts):%d.%m.%Y %H:%M})?",
                               title="Delete event", easy_close=True,
                               footer=ui.TagList(ui.modal_button("Cancel"),
                                                 ui.input_action_button("ev_del_ok", "Delete", class_="btn-danger"))))

    @reactive.effect
    @reactive.event(input.ev_del_ok)
    def _ev_del_ok():
        store.delete_event(editing())
        ui.modal_remove()
        bump()

    # ------------------------------------------------------------ library
    @reactive.calc
    def lib():
        version()
        return service.library()

    @render.data_frame
    def lib_table():
        df = lib()[["experiment", "kind", "name", "updated"]].rename(
            columns={"experiment": "Experiment", "kind": "Kind", "name": "Plot", "updated": "Updated"})
        return grid(df, selection_mode="row", height="300px")

    def lib_selected() -> Path | None:
        sel = lib_table.cell_selection()["rows"]
        return Path(lib().path.iloc[list(sel)[0]]) if sel else None

    @render.ui
    def lib_preview():
        p = lib_selected()
        if p is None:
            return ui.div("Select a plot in the table to preview it.", class_="notice")
        return ui.card(ui.card_header(p.name), img(p.read_bytes()))

    @render.download_button(filename=lambda: lib_selected().name if lib_selected() else "plot.png")
    def lib_png():
        p = lib_selected()
        req(p)
        yield p.read_bytes()

    @render.download_button(filename=lambda: lib_selected().with_suffix(".pdf").name if lib_selected() else "plot.pdf")
    def lib_pdf():
        p = lib_selected()
        req(p)
        pdf = p.with_suffix(".pdf")
        if pdf.exists():
            yield pdf.read_bytes()
        else:                                    # auto-generated plots are PNG only - wrap the image in a PDF
            from logbook.plots import pdf_from_png
            yield pdf_from_png(p.read_bytes())


app = App(app_ui, server, static_assets=WWW)

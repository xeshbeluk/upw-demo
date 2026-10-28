"""Glue between storage and charts: a 'view' (experiment, parameters, period, events) and what can be made from it."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import plots, store
from .config import PLOTS_DIR


@dataclass
class View:
    exp: str
    params: list[str]
    t0: pd.Timestamp
    t1: pd.Timestamp
    include_flagged: bool = False
    categories: list[str] | None = None        # None = all categories
    data: pd.DataFrame | None = None
    resolution: str = ""
    units: dict | None = None
    events: pd.DataFrame | None = None
    title: str = ""
    subtitle: str = ""


def build(v: View, max_points: int = 3000) -> View:
    v.data, v.resolution = store.series(v.exp, v.params, v.t0, v.t1, v.include_flagged, max_points)
    v.units = dict(store.parameters(v.exp)[["parameter", "unit"]].values)
    ev = store.events(v.exp, v.t0, v.t1)
    if v.categories is not None:
        ev = ev[ev.category.isin(v.categories)]
    v.events = ev
    title = store.q("select title from experiments where experiment_id = ?", [v.exp])
    v.title = f"{v.exp} · {title.title.iloc[0] if len(title) else ''}"
    v.subtitle = (f"{v.t0:%d.%m.%Y %H:%M} – {v.t1:%d.%m.%Y %H:%M} · values {v.resolution}"
                  + (" · incl. flagged values" if v.include_flagged else "") + f" · {len(ev)} event(s)")
    return v


def plotly(v: View):
    return plots.chart(v.data, v.params, v.units, v.events, v.title, v.subtitle)


def info(v: View) -> dict:
    return {"experiment": v.title, "parameters": ", ".join(v.params), "from": f"{v.t0:%d.%m.%Y %H:%M}",
            "to": f"{v.t1:%d.%m.%Y %H:%M}", "plot": f"values {v.resolution}",
            "flagged values": "included" if v.include_flagged else "excluded (instrument status not OK)",
            "time": "local time as recorded by the instruments",
            "exported": f"{dt.datetime.now():%d.%m.%Y %H:%M}"}


def png(v: View) -> bytes:
    return plots.png_bytes(plots.figure(v.data, v.params, v.units, v.events, v.title, v.subtitle))


def pdf(v: View) -> bytes:
    return plots.pdf_bytes(v.data, v.params, v.units, v.events, v.title, v.subtitle, info(v))


EXCEL_MAX_ROWS = 150_000


def excel(v: View) -> bytes:
    """Data as recorded if it fits comfortably in Excel, otherwise averaged (stated in the info sheet)."""
    long = store.raw_values(v.exp, v.params, v.t0, v.t1, v.include_flagged)
    meta = info(v)
    if long.ts.nunique() > EXCEL_MAX_ROWS:
        step = store.nice_step((v.t1 - v.t0).total_seconds() / EXCEL_MAX_ROWS)
        long_g = long.assign(ts=long.ts.dt.floor(f"{step}s"))
        wide = long_g.pivot_table(index="ts", columns="parameter", values="value", aggfunc="mean")
        meta["data sheet"] = f"averaged per {store.human_step(step)} (period too long for Excel at full resolution)"
    else:
        wide = long.pivot_table(index="ts", columns="parameter", values="value", aggfunc="first")
        meta["data sheet"] = "values as recorded"
    wide = wide[[p for p in v.params if p in wide.columns]]
    wide.columns = [f"{c} [{v.units.get(c, '')}]" if v.units.get(c) else c for c in wide.columns]
    return plots.excel_bytes(wide.reset_index().rename(columns={"ts": "timestamp"}), long, v.events, meta, png(v))


def file_stem(v: View) -> str:
    return f"{v.exp}_{v.t0:%Y%m%d-%H%M}_{v.t1:%Y%m%d-%H%M}"


# ---------------------------------------------------------------------------------------------- plot library
def safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_")[:80] or "plot"


def save_to_library(v: View, name: str) -> Path:
    folder = PLOTS_DIR / v.exp / "saved"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{dt.datetime.now():%Y%m%d-%H%M}_{safe(name)}"
    (folder / f"{stem}.png").write_bytes(png(v))
    (folder / f"{stem}.pdf").write_bytes(pdf(v))
    return folder / f"{stem}.png"


def longterm_view(exp: str) -> View | None:
    span = store.data_span(exp)
    if span is None:
        return None
    params = list(store.parameters(exp).parameter)
    return build(View(exp, params, span[0], span[1]), max_points=1500)


def snapshots_after_upload(exp: str, results: list[dict]) -> list[Path]:
    """After an upload: one plot of each new file's period, and the updated long-term plot of the experiment."""
    out = []
    params = list(store.parameters(exp).parameter)
    for r in results:
        if r.get("status") != "imported" or not r.get("new"):
            continue
        v = build(View(exp, params, pd.Timestamp(r["t_min"]), pd.Timestamp(r["t_max"])), max_points=2000)
        p = PLOTS_DIR / exp / "uploads" / f"{v.t1:%Y%m%d}_{safe(Path(r['file']).stem)}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png(v))
        out.append(p)
    lt = longterm_view(exp)
    if lt is not None:
        p = PLOTS_DIR / exp / f"{exp}_long-term.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        lt.subtitle = f"long-term, all data · updated {dt.datetime.now():%d.%m.%Y %H:%M} · " + lt.subtitle
        p.write_bytes(png(lt))
        out.append(p)
    return out


def library() -> pd.DataFrame:
    rows = []
    for p in sorted(PLOTS_DIR.rglob("*.png")) if PLOTS_DIR.exists() else []:
        rel = p.relative_to(PLOTS_DIR)
        kind = {"saved": "saved by user", "uploads": "after upload"}.get(rel.parts[1] if len(rel.parts) > 2 else "",
                                                                          "long-term (auto-updated)")
        rows.append({"experiment": rel.parts[0], "kind": kind, "name": p.stem,
                     "updated": dt.datetime.fromtimestamp(p.stat().st_mtime).replace(microsecond=0),
                     "has_pdf": p.with_suffix(".pdf").exists(), "path": str(p)})
    df = pd.DataFrame(rows, columns=["experiment", "kind", "name", "updated", "has_pdf", "path"])
    return df.sort_values(["experiment", "updated"], ascending=[True, False]).reset_index(drop=True)

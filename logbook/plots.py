"""
Charts: one panel per parameter on a shared time axis, events drawn as
  line  - vertical line through all panels (a moment: filter change, calibration)
  note  - callout box above the chart pointing at the time (a remark, a set-point change)
  shade - shaded period through all panels (CIP, shutdown)
  hidden- stored but not drawn
Plotly for the app, matplotlib (same layout) for PNG / PDF files.
"""
from __future__ import annotations

import io
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4", "#008300", "#eda100", "#e34948"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e7e6e2"


def _short(s: str, n: int = 30) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def visible(events: pd.DataFrame) -> pd.DataFrame:
    return events[events["style"] != "hidden"] if len(events) else events


# ---------------------------------------------------------------------------------------------- plotly
def chart(data: pd.DataFrame, params: list[str], units: dict, events: pd.DataFrame, title: str,
          subtitle: str = "") -> go.Figure:
    rows = max(len(params), 1)
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.045 if rows > 1 else 0,
                        subplot_titles=[f"{p} [{units.get(p, '')}]" if units.get(p) else p for p in params])
    for i, p in enumerate(params, 1):
        g = data[data.parameter == p]
        color = SERIES[(i - 1) % len(SERIES)]
        if g["min"].notna().any():
            fig.add_trace(go.Scatter(x=g.ts, y=g["max"], mode="lines", line=dict(width=0), hoverinfo="skip",
                                     showlegend=False), row=i, col=1)
            fig.add_trace(go.Scatter(x=g.ts, y=g["min"], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor="rgba(42,120,214,0.13)", hoverinfo="skip", showlegend=False), row=i, col=1)
        sparse = len(g) < 300                       # e.g. weekly grab samples: show the points
        fig.add_trace(go.Scatter(x=g.ts, y=g["mean"], mode="lines+markers" if sparse else "lines",
                                 marker=dict(size=6, color=color), line=dict(color=color, width=1.6), name=p,
                                 showlegend=False, connectgaps=False,
                                 hovertemplate="%{y:.4g} " + units.get(p, "") + "<extra>" + _short(p, 24) + "</extra>"),
                      row=i, col=1)
        fig.update_yaxes(title_text=units.get(p, ""), row=i, col=1, gridcolor=GRID, zeroline=False)
    for k, e in enumerate(visible(events).itertuples()):
        x0 = pd.Timestamp(e.start_ts)
        x1 = pd.Timestamp(e.end_ts) if pd.notna(e.end_ts) else None
        label = _short(e.label)
        if e.style == "shade" and x1 is not None:
            fig.add_shape(type="rect", xref="x", yref="paper", x0=x0, x1=x1, y0=0, y1=1, fillcolor=e.color,
                          opacity=0.14, line_width=0, layer="below")
        if e.style in ("line", "shade"):
            fig.add_shape(type="line", xref="x", yref="paper", x0=x0, x1=x0, y0=0, y1=1,
                          line=dict(color=e.color, width=1.3, dash="dot" if e.style == "line" else "solid"))
            fig.add_annotation(x=x0, y=1, xref="x", yref="paper", text=label, showarrow=False, xanchor="left",
                               yanchor="bottom", yshift=4 + 13 * (k % 3), font=dict(size=10, color=e.color))
        if e.style == "note":
            fig.add_annotation(x=x0, y=1, xref="x", yref="paper", text=label, showarrow=True, arrowhead=2,
                               arrowcolor=e.color, ax=0, ay=-22 - 15 * (k % 3), bgcolor="white", bordercolor=e.color,
                               borderwidth=1, borderpad=2, font=dict(size=10, color=INK),
                               hovertext=f"{e.label}<br>{x0:%d %b %Y %H:%M}" + (f"<br>{e.note}" if e.note else ""))
    fig.update_layout(
        title=dict(text=f"{title}<br><sup style='color:{MUTED}'>{subtitle}</sup>", x=0, xanchor="left",
                   font=dict(size=15, color=INK)),
        height=150 + 210 * rows, margin=dict(l=60, r=20, t=125, b=30), hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(color=INK, size=12)),
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12, color=MUTED))
    for a in fig.layout.annotations[:rows]:            # subplot titles: left-aligned, dark
        a.update(x=0, xanchor="left", font=dict(size=12, color=INK))
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    return fig


# ---------------------------------------------------------------------------------------------- matplotlib
def figure(data: pd.DataFrame, params: list[str], units: dict, events: pd.DataFrame, title: str,
           subtitle: str = "", size: tuple[float, float] | None = None):
    rows = max(len(params), 1)
    head, band, foot = 0.75, 0.75, 0.45                     # inches: title block, event labels, x axis
    w, h = size or (11.7, head + band + foot + 1.9 * rows)
    fig, axes = plt.subplots(rows, 1, sharex=True, figsize=(w, h), squeeze=False)
    axes = axes[:, 0]
    fig.subplots_adjust(left=0.07, right=0.98, top=1 - (head + band) / h, bottom=foot / h, hspace=0.32)
    plt.rcParams.update({"font.size": 9})
    for i, (ax, p) in enumerate(zip(axes, params)):
        g = data[data.parameter == p]
        color = SERIES[i % len(SERIES)]
        if g["min"].notna().any():
            ax.fill_between(g.ts, g["min"], g["max"], color=color, alpha=0.15, lw=0)
        # break the line at gaps (more than 5 typical steps)
        s = g.set_index("ts")["mean"]
        if len(s) > 2:
            step = s.index.to_series().diff().median()
            s = s.reindex(s.index.union(s.index[s.index.to_series().diff() > 5 * step] - step / 2))
        ax.plot(s.index, s.values, color=color, lw=1.1, marker="o" if len(g) < 300 else None, ms=3)
        ax.set_title(f"{p} [{units.get(p, '')}]" if units.get(p) else p, loc="left", fontsize=9.5, color=INK)
        ax.grid(axis="y", color=GRID, lw=0.7)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(GRID)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED)
    ev = visible(events)
    for ax in axes:
        for e in ev.itertuples():
            x0 = pd.Timestamp(e.start_ts)
            if e.style == "shade" and pd.notna(e.end_ts):
                ax.axvspan(x0, pd.Timestamp(e.end_ts), color=e.color, alpha=0.15, lw=0)
            if e.style in ("line", "shade"):
                ax.axvline(x0, color=e.color, lw=1, ls=":" if e.style == "line" else "-")
    top = axes[0]
    tr = blended_transform_factory(top.transData, top.transAxes)
    for k, e in enumerate(ev.itertuples()):
        x0 = mdates.date2num(pd.Timestamp(e.start_ts))
        ax_h = top.get_position().height * h
        y = 1 + (0.08 + 0.2 * (k % 3)) / ax_h
        if e.style == "note":
            top.annotate(_short(e.label, 26), xy=(x0, 1.0), xycoords=tr, xytext=(x0, y + 0.06 / ax_h), textcoords=tr,
                         fontsize=7.5, ha="center", va="bottom", color=INK,
                         bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=e.color, lw=0.8),
                         arrowprops=dict(arrowstyle="-|>", color=e.color, lw=0.8))
        else:
            top.text(x0, y, " " + _short(e.label, 26), transform=tr, fontsize=7.5, color=e.color, va="bottom")
    loc = mdates.AutoDateLocator(minticks=4, maxticks=10)
    axes[-1].xaxis.set_major_locator(loc)
    axes[-1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    fig.text(0.01, 1 - 0.30 / h, title, ha="left", va="center", fontsize=12.5, color=INK, fontweight="bold")
    fig.text(0.01, 1 - 0.58 / h, subtitle, ha="left", va="center", fontsize=8.5, color=MUTED)
    return fig


def png_bytes(fig, dpi: int = 160) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def pdf_bytes(data, params, units, events, title, subtitle, info: dict) -> bytes:
    """Page 1: chart (A4 landscape). Page 2: what was exported and the event list."""
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = figure(data, params, units, events, title, subtitle, size=(11.69, 8.27))
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.04, 0.94, title, fontsize=13, fontweight="bold", color=INK)
        y = 0.89
        for k, v in info.items():
            fig.text(0.04, y, f"{k}:", fontsize=9, color=MUTED)
            fig.text(0.22, y, str(v), fontsize=9, color=INK)
            y -= 0.03
        y -= 0.02
        fig.text(0.04, y, "Events in this period", fontsize=11, fontweight="bold", color=INK)
        y -= 0.04
        for e in events.itertuples():
            when = f"{pd.Timestamp(e.start_ts):%d.%m.%Y %H:%M}" + (
                f" – {pd.Timestamp(e.end_ts):%d.%m.%Y %H:%M}" if pd.notna(e.end_ts) else "")
            fig.text(0.04, y, when, fontsize=8.5, color=INK)
            fig.text(0.30, y, f"{e.category}", fontsize=8.5, color=e.color)
            fig.text(0.44, y, textwrap.shorten(f"{e.label}" + (f" – {e.note}" if e.note else ""), 95),
                     fontsize=8.5, color=INK)
            y -= 0.028
            if y < 0.05:
                fig.text(0.04, y, "… (list truncated, see Excel export)", fontsize=8.5, color=MUTED)
                break
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)
    return buf.getvalue()


def excel_bytes(wide: pd.DataFrame, long: pd.DataFrame, events: pd.DataFrame, info: dict, png: bytes) -> bytes:
    from openpyxl.drawing.image import Image as XlImage

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"item": list(info), "value": [str(v) for v in info.values()]}).to_excel(xw, sheet_name="info", index=False)
        wide.to_excel(xw, sheet_name="data", index=False)
        ev = events[["start_ts", "end_ts", "category", "label", "note", "scope", "style", "created_by"]] if len(events) \
            else pd.DataFrame(columns=["start_ts", "end_ts", "category", "label", "note"])
        ev.to_excel(xw, sheet_name="events", index=False)
        if long is not None and long.flag.notna().any():
            long[long.flag.notna()].to_excel(xw, sheet_name="flagged_values", index=False)
        ws = xw.book.create_sheet("chart")
        img = XlImage(io.BytesIO(png))
        img.width, img.height = img.width * 0.55, img.height * 0.55
        ws.add_image(img, "A1")
        for name in ("info", "data", "events"):
            sh = xw.book[name]
            for col in sh.columns:
                sh.column_dimensions[col[0].column_letter].width = 22 if name != "info" else 40
    return buf.getvalue()


def pdf_from_png(png: bytes) -> bytes:
    """Put an existing PNG on an A4 landscape PDF page."""
    im = plt.imread(io.BytesIO(png), format="png")
    h, w = im.shape[:2]
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes((0.03, 0.03, 0.94, 0.94))
    ax.imshow(im)
    ax.set_aspect("equal")
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf", facecolor="white")
    plt.close(fig)
    return buf.getvalue()

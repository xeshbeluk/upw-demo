"""Plotly figures: one measure per chart, shared conventions (spec = red line, alert = amber dashed)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
RED, AMBER, GREY, INK, MUTED, GRID = "#d03b3b", "#c98500", "#8a8985", "#0b0b0b", "#52514e", "#e7e6e2"


def base(fig: go.Figure, title: str, y_title: str = "", height: int = 260) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=14, color=INK)),
        height=height, margin=dict(l=60, r=20, t=44, b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12, color=MUTED),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(color=INK, size=12)),  # readable on any fill
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(title=y_title, gridcolor=GRID, zeroline=False)
    return fig


def add_limits(fig: go.Figure, lim: pd.DataFrame) -> None:
    for _, l in lim.iterrows():
        fig.add_hline(y=l.limit_value, line_color=RED if l.severity == "spec" else AMBER,
                      line_dash="solid" if l.severity == "spec" else "dash", line_width=1.3,
                      annotation_text=f"{l.severity} {l.limit_value:g}", annotation_position="top left",
                      annotation_font_size=10, annotation_font_color=RED if l.severity == "spec" else AMBER)


def add_events(fig: go.Figure, events: pd.DataFrame) -> None:
    for _, e in events.iterrows():
        fig.add_vline(x=pd.Timestamp(e.ts_local), line_color=GREY, line_dash="dot", line_width=1)
        fig.add_annotation(x=pd.Timestamp(e.ts_local), y=1, yref="paper", text=e.event_label, showarrow=False,
                           textangle=-90, xanchor="right", yanchor="top", font=dict(size=9, color=GREY))


def trend_chart(df: pd.DataFrame, title: str, unit: str, lim: pd.DataFrame, events: pd.DataFrame,
                show_band: bool) -> go.Figure:
    fig = go.Figure()
    if show_band and df.min_value.notna().any():
        fig.add_trace(go.Scatter(x=df.ts, y=df.max_value, mode="lines", line=dict(width=0), hoverinfo="skip",
                                 showlegend=False))
        fig.add_trace(go.Scatter(x=df.ts, y=df.min_value, mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(42,120,214,0.15)", name="min-max", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=df.ts, y=df.mean_value, mode="lines", line=dict(color=SERIES[0], width=1.8),
                             name="mean" if show_band else "value", hovertemplate="%{y:.4g} " + unit + "<extra></extra>"))
    add_limits(fig, lim)
    add_events(fig, events)
    return base(fig, title, unit)


def window_chart(g: pd.DataFrame, title: str, unit: str, t_event: pd.Timestamp, lim: pd.DataFrame,
                 band: tuple[float, float] | None) -> go.Figure:
    fig = go.Figure()
    for src, color, name in (("longterm", SERIES[0], "5-min archive"), ("maintenance", SERIES[1], "10-s export")):
        s = g[(g.source == src) & (g.quality_flag == "good")][["ts_local", "value"]]
        if not s.empty:
            step = s.ts_local.diff()                      # break the line where data are missing
            gaps = s[step > 3 * step.median()]
            if len(gaps):
                s = pd.concat([s, pd.DataFrame({"ts_local": gaps.ts_local - step.median(), "value": np.nan})]
                              ).sort_values("ts_local")
            fig.add_trace(go.Scatter(x=s.ts_local, y=s.value, mode="lines", line=dict(color=color, width=1.6),
                                     name=name, hovertemplate="%{y:.4g} " + unit + "<extra></extra>"))
    if band:
        fig.add_hrect(y0=band[0], y1=band[1], fillcolor="rgba(12,163,12,0.08)", line_width=0, layer="below")
    fig.add_vline(x=t_event, line_color=INK, line_width=1.5)
    add_limits(fig, lim)
    return base(fig, title, unit, height=240)


def agreement_chart(p: pd.DataFrame) -> go.Figure:
    """Bland-Altman: difference (B - A) against the mean of both; bias and 95 % limits of agreement."""
    m = (p.toc_a + p.toc_b) / 2
    diff = p.toc_b - p.toc_a
    bias, sd = diff.mean(), diff.std()
    sample = p.sample(min(len(p), 4000), random_state=1).index
    fig = go.Figure(go.Scattergl(x=m[sample], y=diff[sample], mode="markers",
                                 marker=dict(size=4, color=SERIES[0], opacity=0.35), name="5-min pairs",
                                 hovertemplate="mean %{x:.3f} / diff %{y:.3f} ppb<extra></extra>"))
    for y, label, dash in ((bias, f"bias {bias:+.3f}", "solid"), (bias + 1.96 * sd, f"+1.96 SD {bias + 1.96 * sd:+.3f}", "dash"),
                           (bias - 1.96 * sd, f"-1.96 SD {bias - 1.96 * sd:+.3f}", "dash")):
        fig.add_hline(y=y, line_color=INK if dash == "solid" else GREY, line_dash=dash, annotation_text=label,
                      annotation_position="top right", annotation_font_size=10)
    fig = base(fig, "Agreement: B - A against the mean of A and B (Bland-Altman)", "B - A [ppb]", height=340)
    fig.update_xaxes(title="mean of A and B [ppb]")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def drift_chart(d: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=d.local_date, y=d.mean_diff, mode="lines+markers", line=dict(color=SERIES[0], width=1.8),
                               marker=dict(size=4), name="daily mean B - A",
                               hovertemplate="%{y:+.3f} ppb<extra></extra>"))
    if len(d) > 5:
        x = (pd.to_datetime(d.local_date) - pd.to_datetime(d.local_date).min()).dt.days.to_numpy()
        k, c = np.polyfit(x, d.mean_diff.to_numpy(), 1)
        fig.add_trace(go.Scatter(x=d.local_date, y=c + k * x, mode="lines", line=dict(color=SERIES[1], width=2, dash="dash"),
                                 name=f"trend {k * 30:+.3f} ppb / month"))
    return base(fig, "Difference over time (drift of B relative to A)", "B - A [ppb]", height=300)


def completeness_heatmap(df: pd.DataFrame, labels: dict) -> go.Figure:
    piv = df.pivot(index="tag", columns="local_date", values="completeness")
    piv = piv.loc[[t for t in labels if t in piv.index]][::-1]
    fig = go.Figure(go.Heatmap(z=piv.values, x=piv.columns, y=[labels[t] for t in piv.index], zmin=0, zmax=1,
                               colorscale=[[0, "#cde2fb"], [0.5, "#5598e7"], [1, "#0d366b"]], xgap=0, ygap=1,
                               colorbar=dict(title="complete", tickformat=".0%"),
                               hovertemplate="%{y}<br>%{x|%d %b %Y}: %{z:.0%}<extra></extra>"))
    return base(fig, "Data completeness per tag and day (good values / expected)", "", height=560)

"""
Trend-deviation detection per monitored tag, one row per tag and day.

Intuition: every day we ask "is this parameter, smoothed over the last few days, clearly away
from where it normally sits, in the direction that hurts?"
  baseline  = median of the daily values 7..35 days ago (a lagged window, so a slow creep
              does not drag its own baseline along)
  spread    = robust standard deviation (1.4826 x MAD) of the same window, with a floor
  ewma      = exponentially weighted moving average of the daily values (lambda = 0.3)
  z         = (ewma - baseline) / (spread * sqrt(lambda / (2 - lambda)))     <- EWMA control chart
  flag      = |z| > 3 in the bad direction AND the shift is larger than min_relevant_change
              (statistically clear AND large enough to matter to an engineer)
  days_to_spec = at the slope of the last 7 days, days until the spec limit is reached
                 (a straight-line projection: for accelerating curves such as resin breakthrough it is
                 an upper bound - the limit usually arrives sooner)
"""
import numpy as np
import pandas as pd

LAMBDA = 0.3
Z_LIMIT = 3.0


def model(dbt, session):
    dbt.config(materialized="table")
    daily = dbt.ref("mart_daily").df()
    tags = dbt.ref("tags").df()
    limits = dbt.ref("spec_limits").df()

    out = []
    for _, t in tags[tags.trend_monitor].iterrows():
        d = daily[daily.tag == t.tag].sort_values("local_date")
        if d.empty:
            continue
        stat = d.median_value if t.parameter == "PART" else d.mean_value          # particles: robust to spikes
        x = pd.Series(np.where(d.completeness >= 0.5, stat, np.nan), index=pd.to_datetime(d.local_date))
        x = x.asfreq("D")
        lagged = x.shift(7)
        baseline = lagged.rolling(28, min_periods=14).median()
        mad = lagged.rolling(28, min_periods=14).apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
        spread = np.maximum(1.4826 * mad, t.min_relevant_change / 4)
        ewma = x.ewm(alpha=LAMBDA, ignore_na=True).mean()
        z = (ewma - baseline) / (spread * np.sqrt(LAMBDA / (2 - LAMBDA)))
        dev = ewma - baseline
        sign = {"up": 1, "down": -1}.get(t.bad_direction)
        if sign is None:                                      # 'both'
            bad = (z.abs() > Z_LIMIT) & (dev.abs() >= t.min_relevant_change)
        else:
            bad = (sign * z > Z_LIMIT) & (sign * dev >= t.min_relevant_change)
        slope = x.rolling(7, min_periods=5).apply(
            lambda w: np.polyfit(np.arange(len(w))[~np.isnan(w)], w[~np.isnan(w)], 1)[0]
            if np.sum(~np.isnan(w)) >= 5 else np.nan, raw=True)

        def days_to(severity):
            lim = limits[(limits.tag == t.tag) & (limits.severity == severity)]
            res = pd.Series(np.nan, index=x.index)
            for _, l in lim.iterrows():
                toward = slope > 0 if l.limit_type == "max" else slope < 0
                inside = ewma < l.limit_value if l.limit_type == "max" else ewma > l.limit_value
                days = (l.limit_value - ewma) / slope
                res = res.where(~(toward & inside & (days <= 365)), days)
            return res

        frame = pd.DataFrame({
            "tag": t.tag, "local_date": x.index.date, "value": x.values, "baseline": baseline.values,
            "ewma": ewma.values, "z": z.values, "deviation": dev.values, "flag": bad.fillna(False).values,
            "slope_per_day": slope.values, "days_to_spec": days_to("spec").values,
            "days_to_alert": days_to("alert").values,
        })
        out.append(frame)
    return pd.concat(out, ignore_index=True)

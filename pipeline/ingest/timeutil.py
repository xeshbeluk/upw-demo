"""Local wall-clock time -> UTC, including the hour that occurs twice when clocks go back."""
from __future__ import annotations

import numpy as np
import pandas as pd


def localize(naive: pd.Series, tz: str) -> tuple[np.ndarray, np.ndarray]:
    """
    naive: local timestamps in file order. Returns (utc naive datetime64 array, dst_repeat bool array).
    The repeated autumn hour is resolved by order ('infer'): first pass = summer time, second = winter time.
    """
    idx = pd.DatetimeIndex(naive)
    dst = np.asarray(idx.duplicated(keep=False)) & ~np.asarray(idx.isna())
    try:
        aware = idx.tz_localize(tz, ambiguous="infer", nonexistent="NaT")
    except Exception:
        aware = idx.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    return aware.tz_convert("UTC").tz_localize(None).to_numpy(), dst

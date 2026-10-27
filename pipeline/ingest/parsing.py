"""Small, source-independent helpers for reading messy spreadsheet cells."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

DATE_FORMATS = ["%d.%m.%Y", "%Y/%m/%d", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"]


def to_float(x) -> float | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip().replace(" ", "").replace("'", "").replace("’", "")
    if "," in s and "." in s:          # 1.234,5 -> 1234.5
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(x) -> tuple[dt.date | None, dt.time | None]:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None, None
    if isinstance(x, (pd.Timestamp, dt.datetime)):
        t = x.time()
        return x.date(), (t if t != dt.time(0, 0) else None)
    if isinstance(x, dt.date):
        return x, None
    s = str(x).strip()
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date(), None
        except ValueError:
            pass
    return None, None


def clean(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = str(x).strip()
    return s or None

"""
Reading instrument exports whose format is not known in advance.

A *layout* describes one export format (separator, decimal mark, header line, timestamp column(s) and format,
optional status column). The first file of a new format is analysed by `sniff`, the user confirms or corrects
the guess once, and the layout is saved. Later files are recognised by their column header (`find_layout`).
"""
from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field

import pandas as pd

DELIMITERS = [";", "\t", ",", "|"]
NA_TOKENS = ["", "----", "---", "--", "-", "NaN", "nan", "NA", "n/a", "#N/A", "***", "Err", "OVER", "UNDER"]
DATETIME_FORMATS = ["%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
                    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                    "%d.%m.%y %H:%M:%S", "%d.%m.%y %H:%M"]
DATE_FORMATS = ["%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%y"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M"]
STATUS_WORDS = re.compile(r"status|state|flag|zustand|meldung|qualit", re.I)
UNIT_RE = re.compile(r"^(.*?)\s*[\[(]([^\])]*)[\])]\s*$")
DELIM_NAMES = {";": "semicolon ;", "\t": "tab", ",": "comma ,", "|": "pipe |"}


@dataclass
class Layout:
    name: str = ""
    delimiter: str = ";"
    decimal: str = "."
    header_row: int = 0                 # 0-based line number of the column header
    date_col: str = ""
    time_col: str = ""                  # empty if date and time are in one column
    datetime_format: str = "%Y-%m-%d %H:%M:%S"
    status_col: str = ""
    status_ok: list[str] = field(default_factory=list)
    prefix: str = ""                    # optional prefix for parameter names, e.g. "Grab sample: "
    signature: list[str] = field(default_factory=list)   # column names, used to recognise later files

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Layout":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------------------------- text
def decode(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding). Handles UTF-16 / UTF-8 BOMs, UTF-8 and Windows-1252."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "UTF-16"
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8"), "UTF-8"
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252"), "Windows-1252"


def lines_of(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_header(line: str, delim: str) -> list[str]:
    return [c.strip().strip('"') for c in line.split(delim)]


def read_table(text: str, lay: Layout, nrows: int | None = None) -> pd.DataFrame:
    body = "\n".join(lines_of(text)[lay.header_row:])
    df = pd.read_csv(io.StringIO(body), sep=lay.delimiter, dtype=str, keep_default_na=False, nrows=nrows,
                     skip_blank_lines=True, engine="python" if len(lay.delimiter) > 1 else "c")
    df.columns = [str(c).strip().strip('"') for c in df.columns]
    return df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]


def to_number(s: pd.Series, decimal: str) -> pd.Series:
    s = s.astype(str).str.strip().replace(NA_TOKENS, pd.NA)
    if decimal == ",":
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def split_unit(col: str) -> tuple[str, str]:
    m = UNIT_RE.match(col)
    return (m.group(1).strip(), m.group(2).strip()) if m else (col.strip(), "")


# ---------------------------------------------------------------------------------------------- sniff
def _fits(values: pd.Series, fmt: str) -> bool:
    v = values.dropna()
    v = v[v.str.strip() != ""]
    return len(v) > 0 and pd.to_datetime(v.str.strip(), format=fmt, errors="coerce").notna().all()


def sniff(raw: bytes) -> tuple[Layout, list[str]]:
    """Guess the layout of an unknown file. Returns the guess and notes for the user."""
    text, enc = decode(raw)
    lines = lines_of(text)[:300]
    notes = [f"Encoding: {enc}"]
    best = None
    for d in DELIMITERS:
        for i in range(min(80, max(len(lines) - 6, 0))):
            n = lines[i].count(d)
            if n < 1 or not re.search(r"[A-Za-zÄÖÜäöü]", lines[i]):
                continue
            nxt = [ln for ln in lines[i + 1:i + 8] if ln.strip()]
            if len(nxt) >= 3 and all(ln.count(d) == n for ln in nxt) and re.search(r"\d", nxt[0]):
                if best is None or n > best[0]:
                    best = (n, d, i)
                break
    if best is None:
        return Layout(), notes + ["Could not find a table in this file - please set the options by hand."]
    _, d, i = best
    lay = Layout(delimiter=d, header_row=i)
    if i:
        notes.append(f"{i} line(s) of header information before the table are skipped")
    df = read_table(text, lay, nrows=300)
    cols = list(df.columns)
    lay.signature = cols

    # decimal mark: a comma between digits in most cells of some column -> decimal comma
    if d != ",":
        comma = sum(df[c].str.fullmatch(r"\s*-?\d+,\d+\s*").mean() > 0.8 for c in cols)
        lay.decimal = "," if comma else "."
    # timestamp: one column, or a date column followed by a time column
    for j, c in enumerate(cols[:4]):
        fmt = next((f for f in DATETIME_FORMATS if _fits(df[c], f)), None)
        if fmt:
            lay.date_col, lay.datetime_format = c, fmt
            break
        dfmt = next((f for f in DATE_FORMATS if _fits(df[c], f)), None)
        if dfmt and j + 1 < len(cols):
            tfmt = next((f for f in TIME_FORMATS if _fits(df[cols[j + 1]], f)), None)
            if tfmt:
                lay.date_col, lay.time_col, lay.datetime_format = c, cols[j + 1], f"{dfmt} {tfmt}"
                break
    if not lay.date_col:
        notes.append("No timestamp column recognised - please choose it and enter the format.")
    elif lay.datetime_format.startswith(("%d/%m", "%m/%d")):
        other = lay.datetime_format.replace("%d/%m", "@").replace("%m/%d", "%d/%m").replace("@", "%m/%d")
        if _fits(df[lay.date_col] + ("" if not lay.time_col else " " + df[lay.time_col]), other):
            notes.append("Day/month order is ambiguous in this sample - please check the date format.")
    # status column: by name
    for c in cols:
        if STATUS_WORDS.search(c) and c not in (lay.date_col, lay.time_col):
            vals = df[c].str.strip().value_counts()
            lay.status_col, lay.status_ok = c, [vals.index[0]] if len(vals) else []
            notes.append(f"Status column '{c}': rows not '{lay.status_ok[0] if lay.status_ok else ''}' are kept "
                         f"but flagged (hidden in plots by default)")
            break
    num = [c for c in value_columns(df, lay)]
    txt = [c for c in cols if c not in num and c not in (lay.date_col, lay.time_col, lay.status_col)]
    notes.append(f"{len(num)} measured value column(s)" + (f"; ignored text columns: {', '.join(txt)}" if txt else ""))
    return lay, notes


def value_columns(df: pd.DataFrame, lay: Layout) -> list[str]:
    out = []
    for c in df.columns:
        if c in (lay.date_col, lay.time_col, lay.status_col):
            continue
        s = df[c].astype(str).str.strip()
        s = s[~s.isin(NA_TOKENS)]
        if len(s) and to_number(s, lay.decimal).notna().mean() >= 0.8:
            out.append(c)
    return out


# ---------------------------------------------------------------------------------------------- recognise + parse
def find_layout(raw: bytes, layouts: list[Layout]) -> Layout | None:
    """A saved layout matches if a line in the first 80 lines is exactly its column header."""
    text, _ = decode(raw)
    lines = lines_of(text)[:80]
    for lay in layouts:
        for i, ln in enumerate(lines):
            if ln.count(lay.delimiter) and split_header(ln, lay.delimiter) == lay.signature:
                return Layout.from_dict({**lay.to_dict(), "header_row": i})
    return None


def parse(raw: bytes, lay: Layout) -> tuple[pd.DataFrame, dict]:
    """Return long data (ts, parameter, unit, value, flag) and counts for the import summary."""
    text, _ = decode(raw)
    df = read_table(text, lay)
    missing = [c for c in (lay.date_col, lay.time_col, lay.status_col) if c and c not in df.columns]
    if missing:
        raise ValueError(f"column(s) not found: {', '.join(missing)}")
    stamp = df[lay.date_col].str.strip()
    if lay.time_col:
        stamp = stamp + " " + df[lay.time_col].str.strip()
    ts = pd.to_datetime(stamp, format=lay.datetime_format, errors="coerce")
    bad_ts = int(ts.isna().sum())
    flag = pd.Series(pd.NA, index=df.index, dtype="string")
    if lay.status_col:
        st = df[lay.status_col].str.strip()
        flag = st.where(~st.isin(lay.status_ok), other=st).where(~st.isin(lay.status_ok))
    parts = []
    for c in value_columns(df, lay):
        name, unit = split_unit(c)
        parts.append(pd.DataFrame({"ts": ts, "parameter": lay.prefix + name, "unit": unit,
                                   "value": to_number(df[c], lay.decimal), "flag": flag}))
    if not parts:
        raise ValueError("no numeric value columns found")
    long = pd.concat(parts, ignore_index=True)
    n_missing = int(long.value.isna().sum() - bad_ts * len(parts))
    long = long[long.ts.notna() & long.value.notna()]
    return long.reset_index(drop=True), {"rows": len(df), "bad_timestamps": bad_ts, "missing_values": max(n_missing, 0),
                                         "parameters": len(parts)}

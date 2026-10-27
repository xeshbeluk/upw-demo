"""Validated, logged edits to the reference tables (dbt/seeds/*.csv), then a warehouse rebuild."""
from __future__ import annotations

import datetime as dt
import getpass
import re
import subprocess
import sys

import pandas as pd

from data import ROOT, SEEDS

LOG = ROOT / "reference_log" / "changes.csv"


def read_seed(name: str) -> pd.DataFrame:
    return pd.read_csv(SEEDS / f"{name}.csv", dtype=str, keep_default_na=False)


def write_seed(name: str, df: pd.DataFrame) -> None:
    path = SEEDS / f"{name}.csv"
    tmp = path.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False, lineterminator="\n")
    tmp.replace(path)


def log_change(user: str, table: str, action: str, detail: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    pd.DataFrame([dict(changed_at=dt.datetime.now().isoformat(timespec="seconds"), user=user, table=table,
                       action=action, detail=detail)]).to_csv(LOG, mode="a", header=not LOG.exists(), index=False,
                                                              lineterminator="\n")


def change_log() -> pd.DataFrame:
    if not LOG.exists():
        return pd.DataFrame(columns=["changed_at", "user", "table", "action", "detail"])
    return pd.read_csv(LOG, dtype=str).iloc[::-1]


def default_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "demo-user"


def add_event_keyword(keyword: str, event_type: str, user: str) -> str | None:
    keyword = keyword.strip()
    df = read_seed("event_keywords")
    types = set(read_seed("event_types")["event_type"])
    if len(keyword) < 3:
        return "keyword must have at least 3 characters"
    if event_type not in types:
        return f"unknown event type {event_type}"
    if keyword.lower() in set(df.keyword.str.lower()):
        return f"'{keyword}' already exists"
    write_seed("event_keywords", pd.concat([df, pd.DataFrame([dict(keyword=keyword, event_type=event_type)])],
                                           ignore_index=True))
    log_change(user, "event_keywords", "add", f"'{keyword}' -> {event_type}")
    return None


def save_spec_limits(edited: pd.DataFrame, user: str) -> list[str]:
    old = read_seed("spec_limits")
    tags = set(read_seed("tags")["tag"])
    errors = []
    new = edited[old.columns].astype(str).apply(lambda c: c.str.strip())
    for i, r in new.iterrows():
        where = f"row {i + 1} ({r.tag})"
        if r.tag not in tags:
            errors.append(f"{where}: unknown tag")
        if r.limit_type not in ("min", "max"):
            errors.append(f"{where}: limit_type must be min or max")
        if r.severity not in ("spec", "alert"):
            errors.append(f"{where}: severity must be spec or alert")
        try:
            float(r.limit_value)
        except ValueError:
            errors.append(f"{where}: limit_value must be a number")
        try:
            new.at[i, "valid_from"] = pd.Timestamp(r.valid_from).date().isoformat()
        except ValueError:
            errors.append(f"{where}: valid_from must be a date")
    if errors:
        return errors
    changes = []
    for (_, a), (_, b) in zip(old.iterrows(), new.iterrows()):
        for c in old.columns:
            if a[c] != b[c]:
                changes.append(f"{a.tag} {a.severity} {a.limit_type}: {c} {a[c]} -> {b[c]}")
    if not changes:
        return ["nothing changed"]
    write_seed("spec_limits", new)
    for c in changes:
        log_change(user, "spec_limits", "update", c)
    return []


def rebuild() -> tuple[bool, str]:
    res = subprocess.run([sys.executable, "-m", "pipeline.run", "--skip-ingest"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    clean = re.sub(r"\x1b\[[0-9;]*m", "", (res.stdout or "") + (res.stderr or ""))
    summary = [ln for ln in clean.splitlines() if "Done." in ln or "ERROR" in ln or "WARN " in ln]
    return res.returncode == 0, "\n".join(summary[-10:]) or clean[-1500:]


def run_report(week: str) -> tuple[bool, str]:
    res = subprocess.run([sys.executable, "-m", "pipeline.report", "--week", week], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return res.returncode == 0, (res.stdout or "") + (res.stderr or "")

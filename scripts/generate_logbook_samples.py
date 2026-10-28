"""
Fictional instrument exports for the Experiment logbook demo - what an engineer would copy off a USB stick.

    uv run python scripts/generate_logbook_samples.py --out data/logbook_usb

Experiments (all invented):
  EXP-2026-03  Pilot RO skid PR-2, low-fouling membrane test (Mar-Sep 2026)
               - data logger CSV: cp1252, ';', decimal comma, separate date and time columns, 6-line header block,
                 German column names, 1-min values, exported roughly every 3 weeks
               - handheld conductivity meter CSV: ',', decimal point, ISO timestamps, weekly grab samples
  EXP-2026-05  UV185 oxidation test, online TOC in/out (May-Oct 2026)
               - analyser TXT: UTF-16, tab-separated, 'YYYY/MM/DD hh:mm:ss', status column (OK / CAL / ERR),
                 '----' for missing values, 5-min values, exported monthly

Realistic problems on purpose: overlapping exports (logger not cleared), a copied duplicate file,
a logger battery gap, analyser calibration and error rows.
ground_truth/ lists what really happened (for checking only).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
T = pd.Timestamp


def ar(n: int, phi: float, sd: float) -> np.ndarray:
    e = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n + 500)
    x = np.zeros_like(e)
    for i in range(1, len(e)):
        x[i] = phi * x[i - 1] + e[i]
    return x[500:]


# ------------------------------------------------------------------------------------------ RO pilot
RO_START, RO_END = T("2026-03-02 08:00"), T("2026-09-28 10:00")
RO_EVENTS = [  # (start, end, label, category, scope)
    ("2026-04-15 09:00", "2026-04-15 14:00", "CIP 1 (alkaline + acid)", "CIP / cleaning", "exp"),
    ("2026-04-29 10:30", None, "Prefilter cartridge changed", "Filter change", "exp"),
    ("2026-05-13 14:00", None, "Feed pressure set-point 12.0 -> 13.5 bar", "Set-point change", "exp"),
    ("2026-05-26 12:00", "2026-05-28 09:00", "Logger battery empty - no data", "Other", "exp"),
    ("2026-06-09 08:30", "2026-06-09 13:30", "CIP 2 (alkaline + acid)", "CIP / cleaning", "exp"),
    ("2026-06-20 11:00", None, "Permeate conductivity sensor calibrated", "Calibration", "exp"),
    ("2026-07-01 06:00", "2026-07-01 14:00", "Plant shutdown - feed water off", "Plant event", "all"),
    ("2026-07-08 10:00", None, "Prefilter cartridge changed", "Filter change", "exp"),
    ("2026-08-01 08:00", "2026-08-01 13:00", "CIP 3 (alkaline + acid)", "CIP / cleaning", "exp"),
    ("2026-09-02 09:00", "2026-09-02 13:30", "CIP 4 (alkaline + acid)", "CIP / cleaning", "exp"),
]
RO_EXPORTS = ["2026-03-23 09:05", "2026-04-13 08:50", "2026-05-04 09:20", "2026-05-26 10:10", "2026-06-15 09:40",
              "2026-07-06 09:12", "2026-07-27 08:55", "2026-08-17 09:30", "2026-09-07 10:05", "2026-09-28 10:00"]


def ro_pilot() -> pd.DataFrame:
    ts = pd.date_range(RO_START, RO_END, freq="60s")
    n = len(ts)
    day = (ts - RO_START).total_seconds().to_numpy() / 86400
    doy = ts.dayofyear.to_numpy()
    hour = ts.hour.to_numpy() + ts.minute.to_numpy() / 60
    temp = 16.5 + 6.5 * np.sin(2 * np.pi * (doy - 120) / 365) + 0.7 * np.sin(2 * np.pi * (hour - 9) / 24) + ar(n, 0.995, 0.15)

    ev = [(T(a), T(b) if b else None, l, c) for a, b, l, c, _ in RO_EVENTS]
    cips = [(a, b) for a, b, l, c in ev if c == "CIP / cleaning"]
    off = cips + [(a, b) for a, b, l, c in ev if c == "Plant event"]
    filters = [a for a, b, l, c in ev if c == "Filter change"]
    cal = [a for a, b, l, c in ev if c == "Calibration"][0]
    sp_change = [a for a, b, l, c in ev if c == "Set-point change"][0]

    # fouling: grows faster as the membrane ages, each CIP recovers a bit less
    foul = np.zeros(n)
    f, k, recover = 0.0, 0, [0.88, 0.82, 0.76, 0.70]
    for i in range(n):
        if k < len(cips) and ts[i] >= cips[k][1]:
            f *= 1 - recover[k]
            k += 1
        f += (0.0024 + 0.0006 * k) / 1440 * (1 + 1.5 * f)
        foul[i] = f
    setp = np.where(ts >= sp_change, 13.5, 12.0)
    pres = setp + ar(n, 0.9, 0.05)
    tcf = np.exp(0.026 * (temp - 20))
    flow = 96 * (pres / 12.0) * tcf * (1 - foul) + ar(n, 0.8, 0.6)

    changes = pd.DatetimeIndex([RO_START] + filters)
    last_f = changes[np.searchsorted(changes, ts, side="right") - 1]
    dp = 0.14 + 0.010 * (ts - last_f).total_seconds().to_numpy() / 86400
    dp = dp * (1 + 0.15 * np.sin(2 * np.pi * day / 7)) + ar(n, 0.9, 0.01)

    true_cond = 1.05 * np.exp(0.03 * (temp - 15)) + 0.9 * foul
    drift = np.where(ts < cal, 0.0042 * day, 0.0042 * (day - (cal - RO_START).total_seconds() / 86400))
    cond = true_cond + drift + ar(n, 0.95, 0.015)

    for a, b in off:
        m = (ts >= a) & (ts < b)
        pres[m] = 0.2 + rng.normal(0, 0.03, m.sum())
        flow[m] = np.abs(rng.normal(0, 0.3, m.sum()))
        dp[m] = np.abs(rng.normal(0.01, 0.005, m.sum()))
        cond[m] = cond[m] * 3 + rng.normal(0, 0.2, m.sum())     # stagnant permeate line
    df = pd.DataFrame({"ts": ts, "pres": pres, "dp": dp, "flow": flow, "cond": cond, "temp": temp,
                       "true_cond": true_cond})
    gap = [e for e in ev if e[2].startswith("Logger battery")][0]
    return df[~((df.ts >= gap[0]) & (df.ts < gap[1]))].reset_index(drop=True)


def de(x: float, nd: int) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def write_logger(df: pd.DataFrame, out: Path) -> list[str]:
    names = []
    prev = RO_START
    for i, e in enumerate(RO_EXPORTS):
        e = T(e)
        start = T("2026-05-18 00:00") if i == 4 else prev          # logger not cleared on 26 May -> overlap
        part = df[(df.ts >= start) & (df.ts < e)]
        head = ["PILOT-RO PR-2 DATENLOGGER", "Seriennummer;DL-2231-07", "Firmware;v3.1.4",
                f"Export;{e:%d.%m.%Y %H:%M}", "Intervall;60 s", "",
                "Datum;Uhrzeit;Speisedruck [bar];Vorfilter dP [bar];Permeat-Durchfluss [l/h];"
                "Permeat-Leitf. [µS/cm];Temperatur [°C]"]
        rows = [f"{t:%d.%m.%Y};{t:%H:%M:%S};{de(p, 2)};{de(d, 3)};{de(f, 1)};{de(c, 3)};{de(tt, 1)}"
                for t, p, d, f, c, tt in zip(part.ts, part.pres, part.dp, part.flow, part.cond, part.temp)]
        name = f"PR2-LOG_{e:%Y-%m-%d}.CSV"
        (out / name).write_bytes(("\r\n".join(head + rows) + "\r\n").encode("cp1252"))
        names.append(name)
        if i == 5:                                                   # copied twice from the stick
            (out / f"PR2-LOG_{e:%Y-%m-%d} - Kopie.CSV").write_bytes((out / name).read_bytes())
        prev = e
    return names


def write_grab(df: pd.DataFrame, out: Path) -> None:
    days = pd.date_range("2026-03-09", "2026-09-28", freq="W-MON")
    rows = ["Sample ID,Sampled At,Conductivity (uS/cm),Temperature (C),Operator"]
    for i, d in enumerate(days, 1):
        t = d + pd.Timedelta(hours=10, minutes=int(rng.integers(0, 50)))
        near = df.iloc[(df.ts - t).abs().argmin()]
        if abs((near.ts - t).total_seconds()) > 120:
            continue
        rows.append(f"GS-{i:03d},{t:%Y-%m-%dT%H:%M},{near.true_cond + rng.normal(0, 0.02):.3f},"
                    f"{near.temp + rng.normal(0, 0.2):.1f},{rng.choice(['RM', 'SK', 'AB'])}")
    (out / "Handmessgeraet_Stichproben_PR2.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------ UV / TOC test
UV_START, UV_END = T("2026-05-04 10:00"), T("2026-10-19 09:00")
UV_LAMP_CHANGE = T("2026-08-07 10:00")
UV_EXPORTS = ["2026-06-01 08:30", "2026-07-01 09:10", "2026-08-03 08:45", "2026-09-01 09:00", "2026-10-01 08:40",
              "2026-10-19 09:00"]
UV_EVENTS = [
    ("2026-07-03 13:00", "2026-07-03 18:00", "TOC analyser error - sample pump blocked", "Other", "exp"),
    ("2026-08-07 10:00", None, "UV185 lamp replaced", "Maintenance", "exp"),
] + [(f"{d:%Y-%m-%d} 07:00", f"{d:%Y-%m-%d} 07:40", "TOC analyser calibration", "Calibration", "exp")
     for d in pd.date_range("2026-05-18", "2026-10-19", freq="28D")]


def uv_test() -> pd.DataFrame:
    ts = pd.date_range(UV_START, UV_END, freq="5min")
    n = len(ts)
    hour = ts.hour.to_numpy() + ts.minute.to_numpy() / 60
    toc_in = 2.8 + 0.35 * np.sin(2 * np.pi * (hour - 14) / 24) + ar(n, 0.98, 0.18)
    run_h = (ts - UV_START).total_seconds().to_numpy() / 3600
    lamp_h = np.where(ts < UV_LAMP_CHANGE, 1450 + run_h, (ts - UV_LAMP_CHANGE).total_seconds().to_numpy() / 3600)
    inten = 100 * np.exp(-lamp_h / 9100) + ar(n, 0.9, 0.4)
    eff = 0.88 * (1 - np.exp(-inten / 35))
    toc_out = toc_in * (1 - eff) + ar(n, 0.7, 0.025)
    status = np.full(n, "OK", dtype=object)
    for a, b, l, c, _ in UV_EVENTS:
        m = (ts >= T(a)) & (ts < T(b)) if b else np.zeros(n, bool)
        if c == "Calibration":
            status[m] = "CAL"
            toc_in[m] = 250 + rng.normal(0, 2, m.sum())
            toc_out[m] = 250 + rng.normal(0, 2, m.sum())
        elif l.startswith("TOC analyser error"):
            status[m] = "ERR"
            toc_in[m] = np.nan
            toc_out[m] = np.nan
    return pd.DataFrame({"ts": ts, "toc_in": toc_in, "toc_out": toc_out, "inten": inten,
                         "lamp_h": np.floor(lamp_h), "status": status})


def write_toc(df: pd.DataFrame, out: Path) -> list[str]:
    names, prev = [], UV_START
    for i, e in enumerate(UV_EXPORTS):
        e = T(e)
        start = T("2026-06-28 00:00") if i == 2 else prev            # exported from the wrong start date -> overlap
        part = df[(df.ts >= start) & (df.ts < e)]
        f = lambda v, nd: "----" if pd.isna(v) else f"{v:.{nd}f}"
        head = ["Online TOC Analyser - Data Export", "Instrument:\tTOC online, stream In/Out", "Serial No.:\tTA-55120",
                f"Exported:\t{e:%Y/%m/%d %H:%M:%S}", f"Points:\t{len(part)}", "",
                "Date/Time\tTOC In (ppb)\tTOC Out (ppb)\tUV Intensity (%)\tLamp Hours (h)\tStatus"]
        rows = [f"{t:%Y/%m/%d %H:%M:%S}\t{f(a, 3)}\t{f(b, 3)}\t{c:.1f}\t{d:.0f}\t{s}"
                for t, a, b, c, d, s in zip(part.ts, part.toc_in, part.toc_out, part.inten, part.lamp_h, part.status)]
        name = f"TOC_Export_{e:%Y%m%d}.txt"
        (out / name).write_bytes("\r\n".join(head + rows).encode("utf-16"))     # UTF-16 with BOM, like many instruments
        names.append(name)
        prev = e
    return names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/logbook_usb")
    a = ap.parse_args()
    out = Path(a.out)
    for sub in ("", "ground_truth"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    print("RO pilot logger ...")
    ro = ro_pilot()
    write_logger(ro, out)
    write_grab(ro, out)
    print("UV / TOC analyser ...")
    write_toc(uv_test(), out)
    ev = pd.DataFrame([("EXP-2026-03", *e) for e in RO_EVENTS] + [("EXP-2026-05", *e) for e in UV_EVENTS],
                      columns=["experiment", "start", "end", "label", "category", "scope"])
    ev.to_csv(out / "ground_truth" / "events_truth.csv", index=False)
    print(f"done: {len(list(out.glob('*.*')))} files in {out}")


if __name__ == "__main__":
    main()

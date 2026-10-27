#!/usr/bin/env python3
"""
Synthetic data for an ultrapure-water (UPW) plant monitoring demo.

One UPW plant ("UPW1") feeding a semiconductor fab:
    feed -> RO1 -> EDI1 -> UV185 (TOC reduction) -> DEGAS -> MB (mixed-bed polisher)
         -> FF1 (final filter) -> distribution loop -> POU (point of use)

Outputs (everything a plant's monitoring system and its engineers would produce):
  raw/longterm/      monthly 5-min exports from the monitoring system (local time, ';', decimal comma,
                     2-line header with tag names and units)
  raw/maintenance/   high-resolution (10 s) manual exports around maintenance work, subset of tags,
                     different CSV dialect and file naming, one file exported twice
  raw/diary/         maintenance diary (Excel), free text, German/English mix
  ground_truth/      true signals, true events, masked periods, list of injected issues
  README.md

All values are FICTIONAL. Magnitudes are typical for UPW (resistivity ~18.2 MOhm*cm, TOC < 1 ppb,
silica < 0.5 ppb, particles in counts/L) but not taken from any real plant or specification.

Usage:  python generate_upw_data.py --out data [--seed 42] [--months 12]
Requirements: numpy, pandas, openpyxl
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "Europe/Zurich"
LT_STEP_MIN = 5          # long-term archive resolution
MT_STEP_S = 10           # maintenance export resolution

# tag, unit, decimals, is_analyzer
TAGS = [
    ("UPW1.FEED.COND", "µS/cm", 1, False),
    ("UPW1.FEED.TEMP", "°C", 1, False),
    ("UPW1.FEED.TOC", "ppb", 0, True),
    ("UPW1.RO1.PERM_COND", "µS/cm", 2, False),
    ("UPW1.RO1.PERM_TOC", "ppb", 1, True),
    ("UPW1.RO1.DP", "bar", 2, False),
    ("UPW1.RO1.PERM_FLOW", "m3/h", 1, False),
    ("UPW1.EDI1.RES", "MOhm*cm", 2, False),
    ("UPW1.UV185.INTENSITY", "%", 1, False),
    ("UPW1.DEGAS.DO", "ppb", 2, True),
    ("UPW1.MB.RES", "MOhm*cm", 3, False),
    ("UPW1.MB.SIO2", "ppb", 3, True),
    ("UPW1.FF1.DP", "bar", 3, False),
    ("UPW1.LOOP.FLOW", "m3/h", 1, False),
    ("UPW1.POU.RES", "MOhm*cm", 3, False),
    ("UPW1.POU.TOC", "ppb", 3, True),
    ("UPW1.POU.TOC_B", "ppb", 3, True),      # comparison analyser, installed mid-year for a study
    ("UPW1.POU.DO", "ppb", 2, True),
    ("UPW1.POU.SIO2", "ppb", 3, True),
    ("UPW1.POU.PART", "counts/L", 0, True),
    ("UPW1.POU.TEMP", "°C", 2, False),
    ("UPW1.POU.PRESS", "bar", 2, False),
]
STATUS_FOR = ["UPW1.RO1.PERM_TOC", "UPW1.DEGAS.DO", "UPW1.MB.SIO2", "UPW1.POU.TOC", "UPW1.POU.TOC_B",
              "UPW1.POU.DO", "UPW1.POU.SIO2", "UPW1.POU.PART"]
STATUS = {"OK": 0, "CAL": 1, "MAINT": 2, "FAULT": 3}


class Gen:
    def __init__(self, a):
        self.a = a
        self.out = Path(a.out)
        self.rng = np.random.default_rng(a.seed)
        self.pr = random.Random(a.seed)
        self.start = pd.Timestamp("2025-10-01", tz="UTC")
        self.end = self.start + pd.DateOffset(months=a.months)
        self.D = (self.end - self.start).total_seconds() / 86400
        self.idx = pd.date_range(self.start, self.end, freq=f"{LT_STEP_MIN}min", inclusive="left")
        self.d = np.asarray((self.idx - self.start).total_seconds()) / 86400      # days since start
        self.events, self.issues, self.masks = [], [], []
        self.plan_events()

    # ------------------------------------------------------------------ helpers
    def day_at(self, frac, hour_local=10.0):
        """Day offset (float) for a fraction of the period at a given local hour."""
        day0 = math.floor(frac * self.D)
        ts_local = (self.start.tz_convert(TZ).normalize() + pd.Timedelta(days=day0)
                    + pd.Timedelta(hours=hour_local))
        return (ts_local.tz_convert("UTC") - self.start).total_seconds() / 86400

    def ts(self, day):
        return self.start + pd.Timedelta(days=float(day))

    def ar(self, n, sd, alpha):
        burn = int(5 / alpha)                                   # discard the start-up transient
        w = self.rng.standard_normal(n + burn)
        x = pd.Series(w).ewm(alpha=alpha, adjust=False).mean().to_numpy()[burn:]
        return sd * x / math.sqrt(alpha / (2 - alpha))

    def event(self, kind, day, unit_text, text, tech=None, duration_h=1.0, export=None, note=""):
        self.events.append(dict(event_type=kind, day=day, start_utc=self.ts(day),
                                end_utc=self.ts(day + duration_h / 24), unit_text=unit_text, text=text,
                                technician=tech or self.pr.choice(["R. Meier", "S. Frei", "T. Nguyen", "A. Kälin"]),
                                export=export, note=note))

    # ------------------------------------------------------------------ the year's story
    def plan_events(self):
        f = self.day_at
        self.resin = [f(.30, 9.5), f(.78, 10.0)]                       # MB resin exhausted -> exchanged
        self.lamp = f(.55, 13.0)                                        # UV185 lamps replaced
        self.filters = [f(.25, 9.0), f(.50, 9.25), f(.75, 10.5)]        # final filter cartridges
        self.bad_filter = self.filters[2]                               # poorly flushed -> long particle excursion
        self.cips = [f(.15, 8.0), f(.45, 8.0), f(.80, 8.0)]             # RO clean-in-place
        self.hx = f(.62, 6.0)                                           # cooling-water problem at heat exchanger
        self.study_start = f(.58, 11.0)                                 # second TOC analyser installed
        self.do_fault = f(.40, 3.0)                                     # DO analyser fault
        self.urea_peak = f(.52, 0.0)                                    # seasonal urea in feed water (spring)
        n_months = self.a.months
        self.cal_pou = [f((m + .5) / n_months, 10.0) for m in range(n_months)]     # monthly TOC calibration
        self.cal_ro = [f((m + .55) / n_months, 14.0) for m in range(n_months)]
        self.cal_unflagged = self.cal_pou[min(7, n_months - 1)]          # status not set by the operator

        for d in self.resin:
            first = d == self.resin[0]
            self.event("resin_exchange", d, "MB-1" if first else "Mischbett 1",
                       "Harzwechsel MB-1, neue Harzflaschen eingesetzt" if first
                       else "Mischbettflaschen getauscht (Silika steigend)", duration_h=3, export="MB")
        self.event("uv_lamp_change", self.lamp, "UV-185", "UV185 Lampenwechsel (alle 8 Lampen)", duration_h=2, export="UV")
        for i, d in enumerate(self.filters):
            self.event("filter_change", d, self.pr.choice(["FF-1", "Endfilter FF1", "Final filter 1"]),
                       "Endfilter gewechselt" if i != 1 else "Final filter cartridges replaced, loop flushed",
                       duration_h=2, export="FF")
        for d in self.cips:
            self.event("ro_cip", d, self.pr.choice(["RO 1", "RO-1", "Umkehrosmose 1"]), "CIP RO1 (alkalisch + sauer)",
                       duration_h=4, export="RO")
        self.event("hx_cleaning", self.hx + 11 / 24, "HX-1", "Wärmetauscher HX-1 gereinigt, Kühlwasser gestört seit Morgen",
                   duration_h=2, export="POU")
        self.event("study", self.study_start, "POU", "Studie: Vergleichsanalysator TOC-B an POU installiert",
                   duration_h=1)
        self.event("analyzer_fault", self.do_fault + 18 / 24, "POU", "DO Analysator POU Sensor getauscht (Fehler seit Nacht)",
                   duration_h=1)
        for d in self.cal_pou:
            self.event("analyzer_calibration", d, "POU", "TOC Analysator POU kalibriert", duration_h=1.5)
        for d in self.cal_ro:
            self.event("analyzer_calibration", d, "RO 1", "TOC RO-Permeat calibrated", duration_h=1.5)
        # routine diary lines (no data impact)
        for wk in range(int(self.D // 7)):
            self.event("inspection", wk * 7 + 1 + 8.5 / 24, "Anlage", self.pr.choice(
                ["Rundgang, alles i.O.", "Wöchentliche Kontrolle", "Probenahme POU für Labor", "Rundgang"]),
                duration_h=0.5)

    # ------------------------------------------------------------------ signals (true values on any time grid)
    def signals(self, d: np.ndarray, noise_scale: float = 1.0, alpha: float = 0.02) -> dict[str, np.ndarray]:
        n = len(d)
        rng_ar = lambda sd, a=alpha: self.ar(n, sd * noise_scale, a)
        doy = (273 + d) % 365.25
        annual = np.sin(2 * np.pi * (doy - 110) / 365.25)
        urea = np.exp(-0.5 * ((d - self.urea_peak) / 22) ** 2)

        def since(events, default):
            """days since the most recent event (or since a virtual event `default` days before start)"""
            out = d + default
            for e in sorted(events):
                out = np.where(d >= e, d - e, out)
            return out

        lamp_age = since([self.lamp], 75)
        intensity = 100 - 0.12 * lamp_age + rng_ar(0.25, 0.01)

        # mixed-bed exhaustion: silica breaks through first, resistivity only at the very end
        sio2_mb = np.full(n, 0.06)
        res_drop = np.zeros(n)
        prev = -1e9
        for e in self.resin:
            m = (d < e) & (d > prev)
            sio2_mb[m] += 1.7 * np.exp((d[m] - e) / 4.0)
            res_drop[m] += 0.65 * np.exp((d[m] - e) / 1.4)
            prev = e
        sio2_mb = np.clip(sio2_mb + rng_ar(0.008, 0.05), 0.01, None)

        ro_age = since(self.cips, 20)
        cip_tail = np.zeros(n)
        ro_flow = 45 + 2 * annual + rng_ar(0.6)
        for c in self.cips:
            dt_h = (d - c) * 24
            cip_tail += np.where(dt_h >= 4, 2.5 * np.exp(-np.clip(dt_h - 4, 0, None) / 3), 0)
            ro_flow = np.where((dt_h >= 0) & (dt_h < 4), 0.0, ro_flow)

        filt_age = since(self.filters, 40)
        part = 35 * np.exp(self.rng.normal(0, 0.35 * noise_scale, n))
        for fc in self.filters:
            dt_h = (d - fc) * 24
            amp, tau = (9000, 5.0) if fc == self.bad_filter else (2500, 1.5)
            part += np.where(dt_h >= 0.3, amp * np.exp(-np.clip(dt_h - 0.3, 0, None) / tau), 0)

        pou_temp = 22 + 0.15 * annual + rng_ar(0.12)
        dt_hx = (d - self.hx) * 24
        pou_temp += np.where((dt_hx >= 0) & (dt_hx < 12), 1.6 * np.clip(dt_hx / 1.5, 0, 1), 0)

        feed_toc = 900 + 600 * urea + 120 * annual + rng_ar(25)
        ro_toc = 12 + 22 * urea + rng_ar(0.8)
        pou_toc = 0.36 + 1.15 * (1 - intensity / 100) + 0.30 * urea + rng_ar(0.035, 0.01)
        mb_res = 18.2 - res_drop + rng_ar(0.004)

        return {
            "UPW1.FEED.COND": 450 + 30 * annual + rng_ar(8),
            "UPW1.FEED.TEMP": 12 + 6 * annual + rng_ar(0.3),
            "UPW1.FEED.TOC": feed_toc,
            "UPW1.RO1.PERM_COND": 4.5 + 0.4 * annual + cip_tail + rng_ar(0.12),
            "UPW1.RO1.PERM_TOC": ro_toc,
            "UPW1.RO1.DP": 1.45 + 0.75 * np.clip(ro_age / 110, 0, 1.3) + rng_ar(0.02),
            "UPW1.RO1.PERM_FLOW": ro_flow,
            "UPW1.EDI1.RES": 16.4 + rng_ar(0.15),
            "UPW1.UV185.INTENSITY": intensity,
            "UPW1.DEGAS.DO": 4.2 + rng_ar(0.25),
            "UPW1.MB.RES": np.clip(mb_res, 10, 18.2),
            "UPW1.MB.SIO2": sio2_mb,
            "UPW1.FF1.DP": 0.32 + 0.85 * np.clip(filt_age / 92, 0, 1.2) + rng_ar(0.01),
            "UPW1.LOOP.FLOW": 30 + rng_ar(0.4),
            "UPW1.POU.RES": np.clip(mb_res - 0.012 + rng_ar(0.003), 10, 18.2),
            "UPW1.POU.TOC": np.clip(pou_toc, 0.05, None),
            "UPW1.POU.TOC_B": np.clip(1.08 * pou_toc + 0.04 + 0.0007 * np.clip(d - self.study_start, 0, None)
                                      + rng_ar(0.05, 0.05), 0.05, None),
            "UPW1.POU.DO": 2.4 + rng_ar(0.15),
            "UPW1.POU.SIO2": np.clip(0.92 * sio2_mb + rng_ar(0.006, 0.05), 0.01, None),
            "UPW1.POU.PART": part,
            "UPW1.POU.TEMP": pou_temp,
            "UPW1.POU.PRESS": 3.6 + rng_ar(0.04),
        }

    def analyzer_artifacts(self, d: np.ndarray, vals: dict, record: bool = True) -> dict[str, np.ndarray]:
        """Apply calibrations / faults to measured values; return status arrays."""
        n = len(d)
        status = {t: np.zeros(n, dtype=int) for t in STATUS_FOR}

        def window(day, hours):
            return (d >= day) & (d < day + hours / 24)

        for c in self.cal_pou:
            m = window(c, 1.5)
            m_std = window(c, 0.5)                                   # standard injected first 30 min
            vals["UPW1.POU.TOC"][m_std] = 500 + self.rng.normal(0, 3, m_std.sum())
            vals["UPW1.POU.TOC"][m & ~m_std] = np.abs(self.rng.normal(0.02, 0.01, (m & ~m_std).sum()))
            if c != self.cal_unflagged:
                status["UPW1.POU.TOC"][m] = STATUS["CAL"]
            if record: self.masks.append(dict(tag="UPW1.POU.TOC", start_utc=self.ts(c), end_utc=self.ts(c + 1.5 / 24),
                                   reason="calibration" + (" (status NOT set)" if c == self.cal_unflagged else "")))
        for c in self.cal_ro:
            m = window(c, 1.5)
            vals["UPW1.RO1.PERM_TOC"][m] = 1000 + self.rng.normal(0, 5, m.sum())
            status["UPW1.RO1.PERM_TOC"][m] = STATUS["CAL"]
            if record: self.masks.append(dict(tag="UPW1.RO1.PERM_TOC", start_utc=self.ts(c), end_utc=self.ts(c + 1.5 / 24),
                                   reason="calibration"))
        m = window(self.do_fault, 16)
        frozen = vals["UPW1.POU.DO"][np.argmax(m)] if m.any() else 2.4
        vals["UPW1.POU.DO"][m] = round(float(frozen), 2)
        status["UPW1.POU.DO"][m] = STATUS["FAULT"]
        if record: self.masks.append(dict(tag="UPW1.POU.DO", start_utc=self.ts(self.do_fault),
                               end_utc=self.ts(self.do_fault + 16 / 24), reason="analyser fault (frozen value)"))
        # comparison analyser not yet installed
        pre = d < self.study_start
        vals["UPW1.POU.TOC_B"][pre] = np.nan
        status["UPW1.POU.TOC_B"][pre] = -1                           # -1 = column absent
        return status

    # ------------------------------------------------------------------ writers
    def fmt(self, x, dec):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return ""
        return f"{x:.{dec}f}".replace(".", ",")

    def write_longterm(self):
        vals = self.signals(self.d)
        truth = {k: v.copy() for k, v in vals.items()}
        status = self.analyzer_artifacts(self.d, vals)
        n = len(self.d)
        # communication gaps: whole rows empty
        gaps = []
        for _ in range(5):
            L = int(self.rng.integers(12, 97))
            a = int(self.rng.integers(0, n - L))
            gaps.append((a, a + L))
            self.issues.append(dict(issue="comms_gap", start_utc=self.idx[a], end_utc=self.idx[a + L - 1],
                                    detail=f"{L * LT_STEP_MIN / 60:.1f} h without data in the long-term export"))
        loc = self.idx.tz_convert(TZ)
        ym = (loc.year * 100 + loc.month).to_numpy()
        lt_dir = self.out / "raw/longterm"
        lt_dir.mkdir(parents=True, exist_ok=True)
        dec = {t: d for t, _, d, _ in TAGS}
        unit = {t: u for t, u, _, _ in TAGS}
        months = sorted(set(ym.tolist()))
        for mi, m in enumerate(months):
            sel = np.flatnonzero(ym == m)
            y, mo = divmod(m, 100)
            has_b = (status["UPW1.POU.TOC_B"][sel] >= 0).any()
            cols = [t for t, *_ in TAGS if t != "UPW1.POU.TOC_B" or has_b]
            stat_cols = [t for t in STATUS_FOR if t in cols]
            lines = [f"Export;UPW1 Langzeitarchiv;Intervall {LT_STEP_MIN} min;{y}-{mo:02d}",
                     "Zeitstempel;" + ";".join(cols + [t + ".STATUS" for t in stat_cols]),
                     ";" + ";".join([unit[t] for t in cols] + ["" for _ in stat_cols])]
            ts_txt = loc[sel].strftime("%d.%m.%Y %H:%M:%S")
            gap_rows = set()
            for a, b in gaps:
                gap_rows.update(range(a, b))
            for k, i in enumerate(sel):
                if i in gap_rows:
                    lines.append(ts_txt[k] + ";" * (len(cols) + len(stat_cols)))
                    continue
                v = [self.fmt(vals[t][i], dec[t]) for t in cols]
                s = [str(status[t][i]) if status[t][i] >= 0 else "" for t in stat_cols]
                lines.append(ts_txt[k] + ";" + ";".join(v + s))
            name = f"UPW1_LT_{y}-{mo:02d}.csv"
            (lt_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            if mi == len(months) // 3:
                (lt_dir / f"UPW1_LT_{y}-{mo:02d}_export2.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
                self.issues.append(dict(issue="duplicate_file", start_utc=None, end_utc=None,
                                        detail=f"{name} exported twice (identical content)"))
            if has_b and not (status["UPW1.POU.TOC_B"][np.flatnonzero(ym == months[mi - 1])] >= 0).any():
                self.issues.append(dict(issue="new_column", start_utc=None, end_utc=None,
                                        detail=f"UPW1.POU.TOC_B first appears in {name}"))
        self.issues.append(dict(issue="dst", start_utc=None, end_utc=None,
                                detail="local timestamps: one hour repeated in late October, one missing in late March"))
        # ground truth: true signals (5-min) as compressed CSV
        gt = pd.DataFrame({"ts_utc": self.idx.strftime("%Y-%m-%dT%H:%M:%SZ"), **{k: np.round(v, 5) for k, v in truth.items()}})
        gt.to_csv(self.out / "ground_truth/true_signals_5min.csv.gz", index=False, compression="gzip")

    def write_maintenance(self):
        mt_dir = self.out / "raw/maintenance"
        mt_dir.mkdir(parents=True, exist_ok=True)
        subsets = {
            "MB": ["UPW1.MB.RES", "UPW1.MB.SIO2", "UPW1.POU.RES", "UPW1.POU.SIO2", "UPW1.POU.TOC"],
            "UV": ["UPW1.UV185.INTENSITY", "UPW1.POU.TOC", "UPW1.RO1.PERM_TOC"],
            "FF": ["UPW1.FF1.DP", "UPW1.POU.PART", "UPW1.POU.PRESS", "UPW1.LOOP.FLOW"],
            "RO": ["UPW1.RO1.DP", "UPW1.RO1.PERM_COND", "UPW1.RO1.PERM_FLOW", "UPW1.RO1.PERM_TOC"],
            "POU": ["UPW1.POU.TEMP", "UPW1.POU.RES", "UPW1.POU.TOC", "UPW1.POU.PART"],
        }
        dec = {t: d for t, _, d, _ in TAGS}
        names = []
        for i, e in enumerate([e for e in self.events if e["export"]]):
            t0_s = int(round((e["day"] - 2 / 24) * 86400 / MT_STEP_S)) * MT_STEP_S     # on the 10-s grid
            hours = 2 + (10 if e["event_type"] == "filter_change" else 6)
            n = hours * 3600 // MT_STEP_S
            d = (t0_s + np.arange(n) * MT_STEP_S) / 86400
            vals = self.signals(d, noise_scale=1.3, alpha=0.05)
            self.analyzer_artifacts(d, vals, record=False)
            cols = subsets[e["export"]]
            loc = (self.start + pd.to_timedelta(t0_s + np.arange(n) * MT_STEP_S, unit="s")).tz_convert(TZ)
            df = pd.DataFrame({"Time": loc.strftime("%Y-%m-%dT%H:%M:%S")})
            for t in cols:
                df[t] = np.round(vals[t], dec[t] + 1)
            stamp = loc[0] + pd.Timedelta(hours=2)
            style = i % 3
            if style == 0:
                name = f"{stamp:%Y-%m-%d}_{e['export']}_{e['event_type']}.csv"
                df.to_csv(mt_dir / name, index=False)
            elif style == 1:
                name = f"Export_{stamp:%Y%m%d_%H%M}.csv"
                df.to_csv(mt_dir / name, index=False)
            else:                                                     # Excel-style regional export
                name = f"Wartung {e['export']} {stamp:%d.%m.%Y}.csv"
                df.to_csv(mt_dir / name, index=False, sep=";", decimal=",")
            names.append(name)
            e["export_file"] = name
        dup = names[len(names) // 2]
        (mt_dir / ("Kopie von " + dup)).write_bytes((mt_dir / dup).read_bytes())
        self.issues.append(dict(issue="duplicate_file", start_utc=None, end_utc=None,
                                detail=f"'Kopie von {dup}' is a copy of {dup}"))
        self.issues.append(dict(issue="mixed_dialects", start_utc=None, end_utc=None,
                                detail="maintenance exports: ',' + '.' or ';' + ',' ; three file-naming styles"))

    def write_diary(self):
        d_dir = self.out / "raw/diary"
        d_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for e in sorted(self.events, key=lambda x: x["day"]):
            loc = e["start_utc"].tz_convert(TZ)
            rows.append({"Datum": loc.tz_localize(None).normalize().to_pydatetime(),
                         "Zeit": loc.strftime("%H:%M") if self.rng.random() > 0.05 else loc.strftime("%H.%M"),
                         "Anlage": e["unit_text"], "Tätigkeit": e["text"], "Techniker": e["technician"],
                         "Bemerkung": e.get("export_file", "") and f"Daten: {e['export_file']}"})
        pd.DataFrame(rows).to_excel(d_dir / "Wartungsprotokoll_UPW1.xlsx", index=False, sheet_name="Protokoll")

    def write_truth(self):
        gt = self.out / "ground_truth"
        ev = pd.DataFrame([{k: v for k, v in e.items() if k != "day"} for e in self.events])
        ev.to_csv(gt / "events_truth.csv", index=False)
        pd.DataFrame(self.masks).to_csv(gt / "masked_periods_truth.csv", index=False)
        stories = [
            ("resin_exhaustion", self.ts(self.resin[0] - 14), self.ts(self.resin[0]),
             "MB silica rises ~2 weeks before the exchange; resistivity drops only in the last ~2 days"),
            ("resin_exhaustion", self.ts(self.resin[1] - 14), self.ts(self.resin[1]),
             "second cycle; diary text 'Mischbettflaschen getauscht' (not in the default keyword list)"),
            ("uv_lamp_ageing", self.start, self.ts(self.lamp),
             "UV185 intensity declines 0.12 %/day; POU TOC creeps up; reset at lamp change"),
            ("seasonal_urea", self.ts(self.urea_peak - 40), self.ts(self.urea_peak + 40),
             "spring urea in feed water raises RO-permeate and POU TOC; with aged lamps POU TOC > 1 ppb"),
            ("filter_change_particles", self.ts(self.bad_filter), self.ts(self.bad_filter + 1),
             "poorly flushed final filter: particles > 200 /L for most of a day"),
            ("hx_temperature", self.ts(self.hx), self.ts(self.hx + 0.5), "POU temperature ~23.6 °C for ~12 h"),
            ("analyser_study", self.ts(self.study_start), self.end,
             "TOC_B reads ~8 % + 0.04 ppb higher than TOC and drifts +0.02 ppb/month"),
        ]
        pd.DataFrame(stories, columns=["story", "start_utc", "end_utc", "detail"]).to_csv(gt / "stories.csv", index=False)
        pd.DataFrame(self.issues).to_csv(gt / "injected_issues.csv", index=False)

    def write_readme(self):
        (self.out / "README.md").write_text(f"""# Synthetic UPW plant data (seed {self.a.seed})

Period {self.start:%Y-%m-%d} .. {self.end:%Y-%m-%d} (UTC). All values fictional.

- raw/longterm/    monthly 5-min exports (local time, ';', decimal comma, header = tag names + units,
                   analyser status columns *.STATUS: 0 ok, 1 calibration, 2 maintenance, 3 fault)
- raw/maintenance/ 10-s exports around maintenance work (mixed dialects and file names)
- raw/diary/       maintenance diary (Excel)
- ground_truth/    true signals, events, masked periods, stories, injected issues - for testing only
""", encoding="utf-8")

    def run(self):
        (self.out / "ground_truth").mkdir(parents=True, exist_ok=True)
        print("long-term exports ...")
        self.write_longterm()
        print("maintenance exports ...")
        self.write_maintenance()
        print("diary ...")
        self.write_diary()
        self.write_truth()
        self.write_readme()
        print(f"done: {len(list((self.out / 'raw/longterm').glob('*.csv')))} long-term files, "
              f"{len(list((self.out / 'raw/maintenance').glob('*.csv')))} maintenance files, {len(self.events)} diary rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--months", type=int, default=12)
    Gen(ap.parse_args()).run()

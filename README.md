# UPW1 monitoring – demo

Monitoring and reporting for an ultrapure-water (UPW) plant, built on **fictional, generated data**.
No real plant or customer data is used anywhere.

```
raw exports (CSV, Excel diary)  →  Python ingestion  →  DuckDB  →  dbt models + tests  →  Shiny app / weekly HTML reports
```

## What it answers

| Question | Where |
|---|---|
| Is the water at the point of use within spec right now? | App → Overview |
| How did TOC, resistivity, silica … develop over the year? | App → Trends (daily / hourly / 5-min) |
| Did a spec get exceeded (e.g. TOC > 1 ppb), and for how long? | Overview, weekly report, `marts.mart_spec_exceedances` |
| Is something drifting *before* it breaks spec? | Trend watch (EWMA vs. normal level), weekly report |
| "I had a filter change – give me all data from X to Y" | App → Event analysis (+ Excel download) |
| How does the new TOC analyser compare to the old one? | App → Analyser study (bias, limits of agreement, drift) |
| Are the data complete and trustworthy? | App → Data health |

## Data sources (simulated)

* `data/raw/longterm/` – monthly 5-min archive exports from the control system (German headers, `;`, decimal comma, local time incl. DST, gaps, one duplicate file)
* `data/raw/maintenance/` – 10-s exports saved during maintenance work (three different naming styles, one duplicate copy)
* `data/raw/diary/Wartungsprotokoll_UPW1.xlsx` – free-text maintenance diary
* `data/ground_truth/` – what really happened (for checking the pipeline only, never read by it)

## Setup (Windows, uv, Python 3.12)

**Easiest (no PowerShell needed):** double-click `setup.bat` once, then `start_app.bat` whenever you want the app.
Or run the same commands by hand in Command Prompt (cmd) or PowerShell:

```powershell
cd C:\Users\<you>\Projects\upw-demo
uv sync                                                  # or: uv add numpy pandas openpyxl duckdb dbt-duckdb shiny plotly matplotlib
uv run python scripts/generate_upw_data.py --out data    # ~15 s
uv run python -m pipeline.run                            # ingest + dbt build, ~30 s
uv run python -m pipeline.report --latest                # one weekly report (or --all, or --week 2026-W02)
uv run shiny run app/app.py --launch-browser
```

Expected after `pipeline.run`: `Done. PASS=36 WARN=1` – the warning is one diary entry no keyword
matches. Fix it in the app (Settings → select the row → event type *Resin exchange* → Add keyword →
Apply changes) and the next build shows `PASS=37 WARN=0`.

## Stories hidden in the data (for the demo)

* **Silica breakthrough** (Jan and Jul): mixed-bed silica rises ~1 week before spec, resistivity drops only ~10 days later → trend watch warns first. See weekly report 2026-W02.
* **UV lamp ageing + seasonal feed TOC** (Mar–Apr): POU TOC creeps above 1 ppb; trend flag ~12 days earlier; back to normal after the lamp change.
* **Filter changes**: particle spikes expected after each change – reported separately as "during maintenance"; the third one recovers badly.
* **Analyser calibrations** (500 ppb standard) are masked automatically, including one that only the diary mentions.
* **TOC analyser study** from May: analyser B reads higher and drifts.
* **Final filter dP** rising past the alert level in September → filter change due.

## Layout

```
scripts/generate_upw_data.py   synthetic data
pipeline/                      ingestion (file fingerprinting, load log), run.py, report.py
dbt/seeds/                     reference tables owned by the process engineers (tags, limits, keywords, events)
dbt/models/                    staging → intermediate → core → marts, plus quality checks
app/                           Shiny app
```

## Hosting on Posit Connect Cloud (free plan)

* `app.py` (repository root) is the entry point for hosting, `requirements.txt` lists the packages.
* Data and warehouse are not in the repository: the first start on a fresh server generates the demo
  data, builds the warehouse and two weekly reports (~1 min, ~0.8 GB memory peak). Later starts reuse it.
* Edits made in Settings on the hosted app are lost when the server is restarted (every visitor
  eventually starts from the same clean demo state).

Steps: public GitHub repo with these files → connect.posit.cloud → Publish → Shiny → repository →
branch `main` → primary file `app.py` → Publish.

---

# Experiment logbook (second app)

For long-term experiments (pilot skids, analyser tests): upload instrument exports copied from a USB stick,
keep one long-term series per experiment, mark events, and export any period as PNG, PDF or Excel.

```
start_logbook.bat        (or: uv run shiny run logbook/app.py --port 8766 --launch-browser)
reset_logbook.bat        back to the demo starting state
```

| Page | What it does |
|---|---|
| Experiments | list, long-term plot with all events, every uploaded file (new values, overlap skipped, duplicates) |
| Upload | drop export files; known formats are recognised by their column header; a new format is set up once (separator, decimal mark, header line, time stamp, instrument status) with a live preview |
| Plot & export | any parameters, any period or "around an event"; choose which event types to show; PNG, PDF (chart + event list), Excel (data, events, flagged values, chart) |
| Events | add / edit / delete; one experiment or all experiments; drawn as vertical line, note, shaded period or hidden |
| Saved plots | long-term plot and a plot per upload are saved automatically; your own saved plots (PNG + PDF) |

Demo story (all data fictional, files in `data/logbook_usb/`):

* **EXP-2026-03, RO pilot skid**: German data-logger CSVs (Windows-1252, `;`, decimal comma, separate date and time
  columns, 6-line header block). One export overlaps the previous one, one was copied twice - both handled.
  Flux decline between CIPs gets worse over time; conductivity sensor drift until its calibration on 20.06.
* **EXP-2026-05, UV185 / TOC test**: analyser TXT exports (UTF-16, tab, status column OK/CAL/ERR, `----` = missing).
  Calibration rows are flagged and hidden by default (tick "include flagged" to see the 250 ppb standard).
* **Left for the live demo**: upload `PR2-LOG_2026-09-28.CSV` and `TOC_Export_20261019.txt` (recognised automatically),
  `Handmessgeraet_Stichproben_PR2.csv` (new format: set it up, e.g. prefix "Grab sample: "), and add the missing
  event **CIP 4 on 02.09.2026 09:00-13:30** (visible as the flow jump).

Hosting: a second Connect Cloud content item from the same repository with primary file `logbook_app.py`
(builds the demo on first start, ~30 s). On the hosted copy, uploads and events are lost when the server restarts.

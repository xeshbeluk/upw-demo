"""
Demo state for the logbook: two experiments, two known file formats, most exports already uploaded,
events entered. Left on the 'USB stick' (data/logbook_usb) for the live demo:
  - the newest logger export      PR2-LOG_2026-09-28.CSV       (recognised automatically)
  - the newest analyser export    TOC_Export_20261019.txt      (recognised automatically)
  - handheld meter grab samples   Handmessgeraet_Stichproben_PR2.csv   (new format -> set up once)
  - CIP 4 on 02.09.2026 is not entered yet (visible in the flow data) -> add it as an event

    uv run python -m logbook.seed            (deletes logbook_data/ and rebuilds it)
"""
from __future__ import annotations

import shutil

import pandas as pd

from . import parsing, service, store
from .config import LB_DIR, USB_DIR

EXPERIMENTS = [
    ("EXP-2026-03", "Pilot RO skid PR-2: low-fouling membrane test", "R. Meier", "2026-03-02",
     "Long-term test of a low-fouling RO membrane on pilot skid PR-2 (feed: softened city water). "
     "Question: flux decline and salt passage between CIPs compared with the standard membrane."),
    ("EXP-2026-05", "UV185 oxidation: TOC reduction vs lamp ageing", "S. Keller", "2026-05-04",
     "TOC upstream/downstream of the UV185 reactor measured with an online TOC analyser (stream switching). "
     "Question: how fast does TOC reduction drop with lamp hours, and what does a lamp change recover?"),
]
LAYOUTS = {"PR2-LOG_2026-03-23.CSV": "PR-2 data logger (CSV)", "TOC_Export_20260601.txt": "Online TOC analyser (TXT)"}
LEAVE_FOR_DEMO = {"PR2-LOG_2026-09-28.CSV", "TOC_Export_20261019.txt", "Handmessgeraet_Stichproben_PR2.csv"}
SKIP_EVENTS = {"CIP 4 (alkaline + acid)"}
WHO = {"EXP-2026-03": "R. Meier", "EXP-2026-05": "S. Keller"}


def main() -> None:
    store.close()
    if LB_DIR.exists():
        shutil.rmtree(LB_DIR)
    if not USB_DIR.exists():
        raise SystemExit(f"{USB_DIR} not found - run scripts/generate_logbook_samples.py first")
    for code, title, owner, start, desc in EXPERIMENTS:
        store.add_experiment(code, title, owner, pd.Timestamp(start).date(), desc)
    for fname, name in LAYOUTS.items():
        lay, _ = parsing.sniff((USB_DIR / fname).read_bytes())
        lay.name = name
        store.save_layout(lay, "R. Meier")
    known = store.layouts()
    for exp, pattern in (("EXP-2026-03", "PR2-LOG_*.CSV"), ("EXP-2026-05", "TOC_Export_*.txt")):
        results = []
        for f in sorted(USB_DIR.glob(pattern), key=lambda f: (f.name.split(' - ')[0], len(f.name))):
            if f.name in LEAVE_FOR_DEMO:
                continue
            raw = f.read_bytes()
            r = store.import_file(exp, f.name, raw, parsing.find_layout(raw, known), WHO[exp])
            print(f"  {exp}  {f.name:<34} {r['message']}")
            results.append(r)
        service.snapshots_after_upload(exp, results[-1:])
    cats = store.categories().set_index("category")
    ev = pd.read_csv(USB_DIR / "ground_truth" / "events_truth.csv")
    for e in ev.itertuples():
        if e.label in SKIP_EVENTS:
            continue
        style = "shade" if e.label.startswith("Logger battery") else cats.loc[e.category, "default_style"]
        if style == "shade" and pd.isna(e.end):
            style = "line"
        store.save_event(None, None if e.scope == "all" else e.experiment, pd.Timestamp(e.start),
                         None if pd.isna(e.end) else pd.Timestamp(e.end), e.label, e.category, style, "",
                         WHO[e.experiment])
    store.con().execute("delete from events where event_id in (select event_id from (select event_id, row_number() "
                        "over (partition by label, start_ts order by event_id) rn from events) where rn > 1)")
    for exp in WHO:
        service.snapshots_after_upload(exp, [])
    print("demo logbook ready:", store.experiments()[["experiment_id", "files", "values_stored"]].to_string(index=False))
    store.close()


if __name__ == "__main__":
    main()

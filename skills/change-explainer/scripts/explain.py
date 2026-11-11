#!/usr/bin/env python3
"""Readout change explainer.

Answers, in order: Is the change real? Is it unusual? Where is it concentrated?
What kind of change is it? When did it start? What should be checked next?

Usage:
  python explain.py <exports or Readout output files...> --out readout_explain
         [--brand-terms "acme,acme co"] [--events events.csv]
         [--metric auto|gsc_clicks|ga4_sessions|ga4_organic|ga4_conversions|ads_clicks]
         [--current-start YYYY-MM-DD --current-end YYYY-MM-DD]
         [--previous-start YYYY-MM-DD --previous-end YYYY-MM-DD] [--days 28]
         [--match-days 3] [--event-lag-days 14] [--client "Client name"]

Writes findings.json (every number) and charts/. Claude writes the narrative;
render_report.py turns findings + narrative into the client report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from readout_core import charts  # noqa: E402
from readout_core.diagnose import (  # noqa: E402
    THRESHOLDS, focus_series, load_events, load_updates, q1_is_it_real, q2_is_it_unusual,
    q3_where, q4_what_kind, q5_when, q6_next_checks,
)
from readout_core.health import run_checks  # noqa: E402
from readout_core.load import SYSTEM_LABELS, load  # noqa: E402
from readout_core.metrics import system_totals  # noqa: E402
from readout_core.periods import resolve_periods  # noqa: E402

DEFAULT_UPDATES = HERE.parent / "references" / "google_updates.csv"


def make_charts(out: Path, focus, periods, q3, q4, q5) -> list[dict]:
    cdir = out / "charts"
    cdir.mkdir(exist_ok=True)
    made = []
    s = focus["series"]
    start = periods["previous"].start - timedelta(days=56)
    s = s[s.index >= start]
    if len(s) >= 14:
        roll = s.rolling(7).mean().dropna()
        vlines = []
        cp = q5.get("change_point")
        if cp:
            vlines.append((date.fromisoformat(cp["date"]), "Trend shift"))
        series = {f"{focus['label']}, 7-day average": (list(roll.index), list(roll.values)),
                  "Daily": (list(s.index), list(s.values))}
        p = cdir / "trend.png"
        fig_series = {"7-day average": series[f"{focus['label']}, 7-day average"]}
        charts.line_chart(fig_series, p, focus["label"],
                          f"7-day average. Shaded: current period ({periods['current'].start} to {periods['current'].end})",
                          shade=(periods["current"].start, periods["current"].end), vlines=vlines)
        made.append({"id": "trend", "file": str(p.relative_to(out)), "title": f"{focus['label']} trend"})

    for key, label, fmt in [("gsc_page", "Pages: change in Search Console clicks", None),
                            ("gsc_query", "Queries: change in Search Console clicks", None),
                            ("ga4_channel", "Channels: change in GA4 sessions", None)]:
        b = q3["breakdowns"].get(key)
        if not b:
            continue
        name_key = key.split("_", 1)[1]
        items = [(r[name_key], r["change"]) for r in b["top_declines"][:6]] + \
                [(r[name_key], r["change"]) for r in b["top_gains"][:4]]
        items = [(n, v) for n, v in items if v]
        items = list(zip(charts.short_labels([n for n, _ in items]), [v for _, v in items]))
        if not items:
            continue
        items.sort(key=lambda kv: kv[1])
        p = cdir / f"where_{name_key}.png"
        charts.diverging_bars(items, p, label,
                              f"{periods['current'].start} to {periods['current'].end} vs {periods['previous'].start} to {periods['previous'].end}")
        made.append({"id": f"where_{name_key}", "file": str(p.relative_to(out)), "title": label})

    bs = q4.get("brand_split", {})
    if "branded" in bs:
        items = [("Branded", (bs["branded"]["clicks_current"] or 0) - (bs["branded"]["clicks_previous"] or 0)),
                 ("Non-branded", (bs["non_branded"]["clicks_current"] or 0) - (bs["non_branded"]["clicks_previous"] or 0))]
        p = cdir / "brand_split.png"
        charts.diverging_bars(items, p, "Branded vs non-branded: change in clicks", "Listed queries only")
        made.append({"id": "brand_split", "file": str(p.relative_to(out)), "title": "Branded vs non-branded change"})
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default="readout_explain")
    ap.add_argument("--client", default="")
    ap.add_argument("--brand-terms", default="", help="Comma-separated brand terms, e.g. 'acme,acme co'")
    ap.add_argument("--events", help="CSV event log: date,end_date,type,description")
    ap.add_argument("--updates", default=str(DEFAULT_UPDATES), help="Google update list CSV")
    ap.add_argument("--metric", default="auto",
                    choices=["auto", "gsc_clicks", "ga4_sessions", "ga4_organic", "ga4_conversions", "ads_clicks"])
    ap.add_argument("--current-start")
    ap.add_argument("--current-end")
    ap.add_argument("--previous-start")
    ap.add_argument("--previous-end")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--match-days", type=int, default=3, help="How close an event must be to the trend shift")
    ap.add_argument("--event-lag-days", type=int, default=14,
                    help="How many days after an event-log entry a shift can start and still be listed (site changes take time to show)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = load(args.inputs)
    focus = focus_series(ds, args.metric)
    if focus is None or focus["series"].empty:
        print("No daily data found for the chosen metric. The change explainer needs exports with a date breakdown.")
        for n in ds.notes:
            print(f"- [{n['level']}] {n.get('file') or ''} {n['message']}")
        return 2

    periods = resolve_periods(ds.daily, args.current_start, args.current_end,
                              args.previous_start, args.previous_end, args.days)
    length = periods["current"].days
    health = run_checks(ds, periods)
    events = load_events(args.events)
    updates, updates_meta = load_updates(Path(args.updates)) if args.updates and Path(args.updates).exists() else ([], {})
    brand = [b for b in args.brand_terms.split(",") if b.strip()]

    q1 = q1_is_it_real(ds, periods, focus)
    q2 = q2_is_it_unusual(ds, periods, focus, length)
    q3 = q3_where(ds, periods, focus)
    q4 = q4_what_kind(ds, periods, q3, brand)
    q5 = q5_when(focus, periods, events, updates, updates_meta, args.match_days, q1.pop("gap_days"),
                 args.event_lag_days)
    q6 = q6_next_checks(q1, q2, q3, q4, q5)
    chart_list = make_charts(out, focus, periods, q3, q4, q5)

    findings = {
        "tool": "readout-change-explainer",
        "client": args.client,
        "generated": date.today().isoformat(),
        "focus_metric": {"id": focus["id"], "label": focus["label"], "source": SYSTEM_LABELS[focus["system"]]},
        "periods": {k: v.as_dict() for k, v in periods.items()},
        "sources": ds.files,
        "data_health": [c for c in health if c["status"] != "ok"],
        "headline_numbers": system_totals(ds, periods),
        "q1_is_it_real": q1,
        "q2_is_it_unusual": q2,
        "q3_where": q3,
        "q4_what_kind": q4,
        "q5_when": q5,
        "q6_next_checks": q6,
        "inputs": {"brand_terms": brand, "events_file": args.events, "events_count": len(events),
                   "google_update_list": updates_meta | {"entries": len(updates)}},
        "thresholds": THRESHOLDS,
        "charts": chart_list,
    }
    (out / "findings.json").write_text(json.dumps(findings, indent=2, default=str))

    print(f"Wrote {out}/findings.json and {len(chart_list)} charts.")
    print(f"Focus: {focus['label']} | {periods['current'].start} to {periods['current'].end} vs "
          f"{periods['previous'].start} to {periods['previous'].end}: {q2['change_pct']}% ({q2['label']})")
    print(f"Is it real: {q1['verdict']}")
    print(f"Pattern: {q4.get('site', {}).get('pattern', 'n/a')}")
    cp = q5.get("change_point")
    if cp:
        print(f"Trend shift: {cp['date']} ({cp['shift_pct']}%, {cp['strength']}); matches: "
              + (", ".join(m["name"] for m in q5["matches"]) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

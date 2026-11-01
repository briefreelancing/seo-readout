#!/usr/bin/env python3
"""Readout traffic aggregator.

Merges GA4, Search Console and Google Ads exports into one standard table,
checks data health, summarizes channels, and compares numbers that measure
similar things across tools (side by side, never added together).

Usage:
  python aggregate.py <files, folders or zips...> --out readout_output
         [--client "Client name"] [--current-start YYYY-MM-DD --current-end YYYY-MM-DD]
         [--previous-start YYYY-MM-DD --previous-end YYYY-MM-DD] [--days 28]
         [--rollup weekly|monthly]

All numbers in the outputs are computed here. Nothing is estimated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from readout_core import charts  # noqa: E402
from readout_core.health import run_checks  # noqa: E402
from readout_core.load import SYSTEM_LABELS, load  # noqa: E402
from readout_core.metrics import channel_summary, rollup, side_by_side, system_totals  # noqa: E402
from readout_core.periods import resolve_periods  # noqa: E402

METRIC_LABELS = {
    "sessions": "Sessions", "users": "Users", "conversions": "Conversions / key events",
    "impressions": "Impressions", "clicks": "Clicks", "spend": "Spend", "ctr_pct": "CTR (%)",
    "avg_position": "Average position", "avg_cpc": "Average CPC",
}


def period_totals(ds) -> list[dict]:
    """Totals from exports that have no date breakdown (cannot be trended or compared)."""
    if ds.period.empty:
        return []
    metrics = ["sessions", "users", "conversions", "impressions", "clicks", "spend"]
    g = ds.period.groupby(["source_system", "period_start", "period_end", "channel"], dropna=False)[metrics].sum(min_count=1)
    rows = []
    for (system, start, end, chan), r in g.iterrows():
        rows.append({"system": SYSTEM_LABELS.get(system, system), "period_start": str(start), "period_end": str(end),
                     "channel": chan} | {m: (None if r[m] != r[m] else round(float(r[m]), 2)) for m in metrics if r[m] == r[m]})
    return rows


def build_charts(ds, periods, out: Path) -> list[dict]:
    made = []
    cdir = out / "charts"
    cdir.mkdir(exist_ok=True)
    weekly = rollup(ds.daily, "W")
    if weekly.empty:
        return made
    weekly = weekly[weekly["complete"]]
    shade = (periods["current"].start, periods["current"].end)

    ga = weekly[weekly["source_system"] == "ga4"]
    if not ga.empty and ga["sessions"].notna().any():
        totals = ga.groupby("channel")["sessions"].sum().to_dict()
        keep = charts.fold_series(totals)
        ga = ga.assign(channel=ga["channel"].where(ga["channel"].isin(keep), "Other"))
        piv = ga.groupby(["period_start", "channel"])["sessions"].sum().unstack(fill_value=0)
        order = keep + (["Other"] if "Other" in piv.columns else [])
        series = {c: (list(piv.index), list(piv[c])) for c in order}
        p = cdir / "ga4_sessions_by_channel.png"
        charts.line_chart(series, p, "GA4 sessions by channel", "Weekly totals, complete weeks only", shade=shade)
        made.append({"file": str(p.relative_to(out)), "title": "GA4 sessions by channel (weekly)"})

    gsc = ds.daily[ds.daily["source_system"] == "gsc"].groupby("date")[["clicks", "impressions"]].sum().sort_index()
    if len(gsc) >= 14:
        roll = gsc.rolling(7).mean().dropna()
        p = cdir / "search_console_trend.png"
        charts.small_multiples(
            [{"name": "Clicks", "data": (list(roll.index), list(roll["clicks"]))},
             {"name": "Impressions", "data": (list(roll.index), list(roll["impressions"]))}],
            p, "Search Console: clicks and impressions", "7-day average", shade=shade)
        made.append({"file": str(p.relative_to(out)), "title": "Search Console clicks and impressions (7-day average)"})

    ads = weekly[weekly["source_system"] == "gads"].groupby("period_start")[["clicks", "spend"]].sum()
    if len(ads) >= 3:
        p = cdir / "google_ads_trend.png"
        charts.small_multiples(
            [{"name": "Clicks", "data": (list(ads.index), list(ads["clicks"]))},
             {"name": "Spend", "data": (list(ads.index), list(ads["spend"]))}],
            p, "Google Ads: clicks and spend", "Weekly totals, complete weeks only", shade=shade)
        made.append({"file": str(p.relative_to(out)), "title": "Google Ads clicks and spend (weekly)"})
    return made


def _autosize(ws):
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)


def write_workbook(path: Path, client, periods, ds, checks, chan_rows, totals_rows, sbs, trend):
    from openpyxl.styles import Alignment, Font, PatternFill

    header_fill = PatternFill("solid", fgColor="F0EFEC")
    readme = [
        ["Readout traffic aggregator"],
        ["Client", client or ""],
        ["Generated", date.today().isoformat()],
        ["Current period", f"{periods['current'].start} to {periods['current'].end}"],
        ["Previous period", f"{periods['previous'].start} to {periods['previous'].end}"],
        ["Year-ago period", f"{periods['year_ago'].start} to {periods['year_ago'].end} (same weekdays, 364 days earlier)"],
        ["Sources", ", ".join(SYSTEM_LABELS[s] for s in ds.systems())],
        [],
        ["How to read this workbook"],
        ["Channel summary", "Totals per source and channel, with change against the previous period and a year ago."],
        ["Side by side", "Numbers from different tools that measure similar things. They are shown next to each other and never added together."],
        ["Health check", "Problems found in the data before anyone draws conclusions. Read this tab first."],
        ["Trends", "Weekly or monthly totals. 'complete' is FALSE for partial weeks or months at the edges."],
        ["Daily data", "The standard table every other tab is built from."],
        [],
        ["Note", "Each tool counts differently. Search Console clicks, GA4 sessions and Google Ads clicks are not interchangeable."],
    ]
    chan = pd.DataFrame(chan_rows)
    if not chan.empty:
        chan = chan.drop(columns=["system_id"])
        chan["metric"] = chan["metric"].map(lambda m: METRIC_LABELS.get(m, m))
        for c in ["change_pct", "yoy_pct", "share_pct"]:
            chan[c] = chan[c].map(lambda v: v / 100 if v is not None else None)
        chan.columns = ["Source", "Channel", "Metric", "Current", "Previous", "Change", "Year ago", "Change vs year ago", "Share of source"]
    tot = pd.DataFrame(totals_rows)
    if not tot.empty:
        tot = tot.drop(columns=["system_id"])
        if "change_abs" not in tot:
            tot["change_abs"] = None
        tot["metric"] = tot["metric"].map(lambda m: METRIC_LABELS.get(m, m))
        for c in ["change_pct", "yoy_pct"]:
            tot[c] = tot[c].map(lambda v: v / 100 if v is not None else None)
        tot = tot[["system", "metric", "current", "previous", "change_pct", "change_abs", "year_ago", "yoy_pct"]]
        tot.columns = ["Source", "Metric", "Current", "Previous", "Change", "Change (points)", "Year ago", "Change vs year ago"]
    sbs_rows = []
    for s in sbs:
        for key, v in s["periods"].items():
            sbs_rows.append([s["label"], key, s["a_label"], v["a"], s["b_label"], v["b"], v["gap"], v["ratio_b_to_a"]])
        sbs_rows.append(["", "", "Why they differ: " + " ".join(s["why_they_differ"]), None, None, None, None, None])
    sbs_df = pd.DataFrame(sbs_rows, columns=["Comparison", "Period", "Measure A", "A", "Measure B", "B", "Gap (B minus A)", "B as a share of A"])
    health = pd.DataFrame([{"Status": c["status"].upper(), "Check": c["check"], "Message": c["message"]} for c in checks])

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(readme).to_excel(xw, sheet_name="Read me", index=False, header=False)
        if not tot.empty:
            tot.to_excel(xw, sheet_name="Channel summary", index=False, startrow=1)
            start = len(tot) + 4
        else:
            start = 1
        if not chan.empty:
            chan.to_excel(xw, sheet_name="Channel summary", index=False, startrow=start)
        sbs_df.to_excel(xw, sheet_name="Side by side", index=False)
        health.to_excel(xw, sheet_name="Health check", index=False)
        trend.to_excel(xw, sheet_name="Trends", index=False)
        ds.daily.to_excel(xw, sheet_name="Daily data", index=False)
        if len(ds.gsc_dims):
            ds.gsc_dims.to_excel(xw, sheet_name="Search Console detail", index=False)
        if len(ds.period):
            ds.period.to_excel(xw, sheet_name="Period totals", index=False)

        wb = xw.book
        ws = wb["Read me"]
        ws["A1"].font = Font(bold=True, size=14)
        ws["A9"].font = Font(bold=True)
        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 110
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")

        ws = wb["Channel summary"]
        ws["A1"] = "Totals by source"
        ws["A1"].font = Font(bold=True)
        blocks = []
        if not tot.empty:
            blocks.append((2, len(tot), list(tot.columns)))
        if not chan.empty:
            ws.cell(row=start, column=1, value="By channel").font = Font(bold=True)
            blocks.append((start + 1, len(chan), list(chan.columns)))
        pct_cols = {"Change", "Change vs year ago", "Share of source"}
        num_cols = {"Current", "Previous", "Year ago", "Change (points)"}
        for hdr_row, n, cols in blocks:
            for j, name in enumerate(cols, start=1):
                hc = ws.cell(row=hdr_row, column=j)
                hc.font = Font(bold=True)
                hc.fill = header_fill
                fmt = "0.0%" if name in pct_cols else "#,##0.0#" if name in num_cols else None
                if fmt:
                    for r in range(hdr_row + 1, hdr_row + 1 + n):
                        ws.cell(row=r, column=j).number_format = fmt
        for name in wb.sheetnames:
            sh = wb[name]
            if name not in {"Read me", "Channel summary"}:
                for c in sh[1]:
                    c.font = Font(bold=True)
                    c.fill = header_fill
                sh.freeze_panes = "A2"
            if name != "Read me":
                _autosize(sh)
        sh = wb["Health check"]
        sh.column_dimensions["C"].width = 120
        for row in sh.iter_rows(min_row=2):
            row[2].alignment = Alignment(wrap_text=True, vertical="top")
        sh = wb["Side by side"]
        sh.column_dimensions["C"].width = 60
        sh.column_dimensions["E"].width = 40
        for row in sh.iter_rows(min_row=2):
            row[2].alignment = Alignment(wrap_text=True, vertical="top")
            row[7].number_format = "0.00"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="Export files, folders or Search Console zips")
    ap.add_argument("--out", default="readout_output")
    ap.add_argument("--client", default="")
    ap.add_argument("--current-start")
    ap.add_argument("--current-end")
    ap.add_argument("--previous-start")
    ap.add_argument("--previous-end")
    ap.add_argument("--days", type=int, default=28, help="Length of the default comparison period")
    ap.add_argument("--rollup", choices=["weekly", "monthly"], default="weekly")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = load(args.inputs)
    if ds.daily.empty and ds.period.empty:
        print("No usable data found. Notes:")
        for n in ds.notes:
            print(f"- [{n['level']}] {n.get('file') or ''} {n['message']}")
        return 2

    periods = resolve_periods(ds.daily, args.current_start, args.current_end,
                              args.previous_start, args.previous_end, args.days) if not ds.daily.empty else None
    checks = run_checks(ds, periods)
    chan_rows = channel_summary(ds, periods) if periods else []
    totals_rows = system_totals(ds, periods) if periods else []
    sbs = side_by_side(ds, periods) if periods else []
    trend = rollup(ds.daily, "M" if args.rollup == "monthly" else "W")
    chart_list = build_charts(ds, periods, out) if periods else []

    ds.daily.to_csv(out / "readout_daily.csv", index=False)
    outputs = {"daily_csv": "readout_daily.csv"}
    if len(ds.gsc_dims):
        ds.gsc_dims.to_csv(out / "readout_search_console_breakdowns.csv", index=False)
        outputs["search_console_breakdowns_csv"] = "readout_search_console_breakdowns.csv"
    if len(ds.period):
        ds.period.to_csv(out / "readout_period_totals.csv", index=False)
        outputs["period_totals_csv"] = "readout_period_totals.csv"
    if periods:
        write_workbook(out / "readout_workbook.xlsx", args.client, periods, ds, checks, chan_rows, totals_rows, sbs, trend)
        outputs["workbook"] = "readout_workbook.xlsx"

    summary = {
        "tool": "readout-traffic-aggregator",
        "client": args.client,
        "generated": date.today().isoformat(),
        "periods": {k: v.as_dict() for k, v in periods.items()} if periods else None,
        "sources": ds.files,
        "health": checks,
        "totals": totals_rows,
        "channel_summary": chan_rows,
        "side_by_side": sbs,
        "period_totals": period_totals(ds),
        "charts": chart_list,
        "outputs": outputs,
    }
    (out / "aggregate_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    warnings = [c for c in checks if c["status"] == "warning"]
    print(f"Wrote {out}/aggregate_summary.json and {len(outputs)} data files, {len(chart_list)} charts.")
    print(f"Sources: {', '.join(SYSTEM_LABELS[s] for s in ds.systems())}. Health warnings: {len(warnings)}.")
    for w in warnings:
        print(f"- {w['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

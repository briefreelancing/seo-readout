"""Data health checks: is the data complete and comparable before anyone reads it?"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .load import Dataset, SYSTEM_LABELS
from .periods import Period, coverage

MAIN_METRIC = {"ga4": "sessions", "gsc": "clicks", "gads": "clicks"}


def _gaps(dates: list[date]) -> list[tuple[date, date]]:
    if not dates:
        return []
    ds = sorted(set(dates))
    gaps = []
    for a, b in zip(ds, ds[1:]):
        if (b - a).days > 1:
            gaps.append((a + timedelta(days=1), b - timedelta(days=1)))
    return gaps


def run_checks(ds: Dataset, periods: dict[str, Period] | None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    checks: list[dict] = []

    def add(check, status, message, **details):
        checks.append({"check": check, "status": status, "message": message, "details": details})

    daily = ds.daily
    ranges = {}
    for sysname in ds.systems():
        sub = daily[daily["source_system"] == sysname]
        label = SYSTEM_LABELS[sysname]
        if sub.empty:
            add("date_coverage", "info", f"{label}: no daily data (period totals only).")
            continue
        start, end = min(sub["date"]), max(sub["date"])
        ranges[sysname] = (start, end)
        add("date_coverage", "ok", f"{label}: {start} to {end} ({sub['date'].nunique()} days).",
            system=sysname, start=start.isoformat(), end=end.isoformat())

        gaps = _gaps(list(sub["date"]))
        if gaps:
            txt = "; ".join(f"{a} to {b}" if a != b else f"{a}" for a, b in gaps[:5])
            add("missing_dates", "warning", f"{label}: dates missing from the export: {txt}.",
                system=sysname, gaps=[[a.isoformat(), b.isoformat()] for a, b in gaps])

        metric = MAIN_METRIC[sysname]
        per_day = sub.groupby("date")[metric].sum(min_count=1).dropna()
        if len(per_day) >= 14:
            med = per_day.median()
            low = per_day[per_day < 0.1 * med] if med > 0 else per_day[per_day <= 0]
            if len(low):
                days = ", ".join(str(d) for d in list(low.index)[:5])
                add("near_zero_days", "warning",
                    f"{label}: {len(low)} day(s) with {metric} under 10% of the usual daily level ({days}). "
                    "This often means a tracking or export problem, not a real drop.",
                    system=sysname, days=[d.isoformat() for d in low.index])

        for m in ["sessions", "users", "conversions", "impressions", "clicks", "spend"]:
            if m in sub and sub[m].notna().any() and (sub[m].fillna(0) == 0).all():
                add("empty_metric", "warning", f"{label}: '{m}' is zero on every row.", system=sysname, metric=m)

    if len(ranges) > 1:
        starts = {s: r[0] for s, r in ranges.items()}
        ends = {s: r[1] for s, r in ranges.items()}
        if len(set(starts.values())) > 1 or len(set(ends.values())) > 1:
            txt = "; ".join(f"{SYSTEM_LABELS[s]} {r[0]} to {r[1]}" for s, r in ranges.items())
            add("range_alignment", "warning",
                f"Sources cover different dates ({txt}). Comparisons use only the dates they share.")
        else:
            add("range_alignment", "ok", "All sources cover the same dates.")

    if "gsc" in ranges and (today - ranges["gsc"][1]).days <= 2:
        add("recent_data", "warning",
            "Search Console data ends within 2 days of today. The latest days are often incomplete "
            "and can look like a drop.")

    if periods:
        for sysname in ranges:
            for key in ["current", "previous", "year_ago"]:
                cov = coverage(daily, sysname, periods[key])
                if key != "year_ago" and cov < 1.0:
                    add("period_coverage", "warning",
                        f"{SYSTEM_LABELS[sysname]} covers {cov:.0%} of the {key} period "
                        f"({periods[key].start} to {periods[key].end}).",
                        system=sysname, period=key, coverage=cov)

    if len(ds.currencies) > 1:
        add("currency", "warning", f"Google Ads data has more than one currency: {', '.join(sorted(ds.currencies))}. Spend totals mix currencies.")
    elif ds.currencies:
        add("currency", "ok", f"Google Ads currency: {next(iter(ds.currencies))}.")

    types = {t.lower() for t in ds.gsc_search_types}
    if types and types != {"web"}:
        add("gsc_search_type", "warning",
            f"Search Console export is filtered to search type: {', '.join(sorted(ds.gsc_search_types))}. "
            "Comparisons with GA4 assume web search.")

    if "gsc" in ranges and len(ranges) > 1:
        add("time_zones", "info",
            "Search Console reports dates in Pacific Time. GA4 and Google Ads use each account's own "
            "time zone, so single days can differ slightly between sources.")

    for n in ds.notes:
        status = {"error": "warning", "warning": "warning", "info": "info"}[n["level"]]
        prefix = f"{n['file']}: " if n.get("file") else ""
        add("file_note", status, prefix + n["message"])

    return checks

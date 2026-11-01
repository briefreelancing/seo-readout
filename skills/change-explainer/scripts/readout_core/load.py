"""Detect what each export is and turn it into Readout's standard tables.

Output tables
-------------
daily      one row per date x source system x channel x source x medium x campaign
period     same columns, but for exports with no date breakdown (period_start/end instead)
gsc_dims   Search Console breakdowns (query, page, country, device) per period

Format knowledge here is based on how these exports are commonly structured.
It has not been checked against every account setting or language. Anything
the loader cannot place is reported in `notes`, never silently dropped.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import channels as ch
from .columns import (
    map_header, nth_day_to_date, parse_date, parse_date_range, parse_number,
    recognized_count, to_frame, is_total_row,
)
from .fileio import RawFile, TableBlock, load_paths, split_blocks

STD_DIMS = ["source_system", "channel", "source", "medium", "campaign"]
STD_METRICS = ["sessions", "users", "conversions", "impressions", "clicks", "spend", "avg_position"]
DAILY_COLS = ["date"] + STD_DIMS + STD_METRICS
PERIOD_COLS = ["period_start", "period_end"] + STD_DIMS + STD_METRICS
DIM_COLS = ["dimension", "item", "period_label", "period_start", "period_end", "clicks", "impressions", "ctr", "position", "bundle"]

GSC_DIMENSIONS = {"query": "query", "page": "page", "country": "country", "device": "device", "search_appearance": "search_appearance"}
SYSTEM_LABELS = {"ga4": "GA4", "gsc": "Search Console", "gads": "Google Ads"}


@dataclass
class Dataset:
    daily: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=DAILY_COLS))
    period: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=PERIOD_COLS))
    gsc_dims: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=DIM_COLS))
    notes: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    currencies: set[str] = field(default_factory=set)
    gsc_search_types: set[str] = field(default_factory=set)

    def note(self, level: str, message: str, file: str | None = None) -> None:
        self.notes.append({"level": level, "file": file, "message": message})

    def systems(self) -> list[str]:
        s = set(self.daily["source_system"].dropna()) | set(self.period["source_system"].dropna())
        return [x for x in ["ga4", "gsc", "gads"] if x in s]


def _find_header(block: TableBlock) -> tuple[int, dict] | None:
    for i, row in enumerate(block.rows[:6]):
        if recognized_count(row) >= 2:
            return i, map_header(row)
    return None


def _fields(mapping: dict) -> set[str]:
    return {f for f, _ in mapping.values()}


def classify(mapping: dict, fname: str) -> str | None:
    f = _fields(mapping)
    name = fname.lower()
    if f == {"filter_name", "filter_value"} or name.startswith("filters"):
        return "gsc_filters" if "filter_name" in f else None
    gsc_dim = f & {"date", "query", "page", "country", "device", "search_appearance"}
    if {"clicks", "impressions"} <= f and ({"position"} & f or {"ctr"} & f) and not {"spend", "campaign", "sessions"} & f and gsc_dim:
        return "gsc"
    if {"sessions"} & f or ({"users", "conversions"} & f and {"channel", "source_medium", "source"} & f):
        return "ga4"
    if {"clicks", "impressions"} <= f and ({"spend", "campaign", "currency", "campaign_type"} & f):
        return "gads"
    return None


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df:
        return pd.Series([math.nan] * len(df), index=df.index, dtype="float64")
    return df[col].map(parse_number).astype("float64")


def _std_frame(n: int) -> dict:
    return {c: [None] * n for c in STD_DIMS} | {c: [math.nan] * n for c in STD_METRICS}


def load(paths: list[str | Path]) -> Dataset:
    ds = Dataset()
    raw = load_paths(paths)
    daily_parts: list[pd.DataFrame] = []
    period_parts: list[pd.DataFrame] = []
    gsc_by_bundle: dict[str, list[tuple[RawFile, TableBlock, dict, int]]] = defaultdict(list)

    for rf in raw:
        blocks = split_blocks(rf.text)
        if not blocks:
            ds.note("warning", "File is empty or unreadable.", rf.name)
            continue
        used = False
        for b in blocks:
            first = [c.strip().lower() for c in b.rows[0]]
            if "source_system" in first and "date" in first:
                df = pd.DataFrame(b.rows[1:], columns=first)
                daily_parts.append(_from_readout(df))
                ds.files.append({"file": rf.name, "detected_as": "Readout standard table", "rows": len(df)})
                used = True
                continue
            if {"dimension", "item", "clicks"} <= set(first):
                df = pd.DataFrame(b.rows[1:], columns=first)
                ds.gsc_dims = pd.concat([ds.gsc_dims, _dims_from_readout(df)], ignore_index=True) if len(ds.gsc_dims) else _dims_from_readout(df)
                ds.files.append({"file": rf.name, "detected_as": "Readout Search Console breakdowns", "rows": len(df)})
                used = True
                continue
            if "date" in first and "description" in first:
                ds.note("info", "Looks like an event log; pass it with --events instead of as data.", rf.name)
                used = True
                continue
            found = _find_header(b)
            if not found:
                continue
            hidx, mapping = found
            kind = classify(mapping, rf.name)
            if kind is None:
                header = ", ".join(b.rows[hidx][:8])
                ds.note("warning", f"Skipped a table it could not identify. Columns: {header}", rf.name)
                continue
            b.preamble = [" ".join(c for c in r if c) for r in b.rows[:hidx]]
            body = [r for r in b.rows[hidx + 1:] if r and not is_total_row(r[0])]
            dropped = len(b.rows[hidx + 1:]) - len(body)
            used = True
            if kind in {"gsc", "gsc_filters"}:
                gsc_by_bundle[rf.bundle or "(loose files)"].append((rf, b, mapping, hidx))
            elif kind == "ga4":
                d, p = _parse_ga4(rf, b, mapping, body, ds)
                daily_parts += [d] if d is not None else []
                period_parts += [p] if p is not None else []
                ds.files.append({"file": rf.name, "detected_as": "GA4", "rows": len(body), "total_rows_removed": dropped})
            elif kind == "gads":
                d, p = _parse_gads(rf, b, mapping, body, ds)
                daily_parts += [d] if d is not None else []
                period_parts += [p] if p is not None else []
                ds.files.append({"file": rf.name, "detected_as": "Google Ads", "rows": len(body), "total_rows_removed": dropped})
        if not used:
            ds.note("warning", "No recognizable table found in this file.", rf.name)

    gsc_daily_parts = []
    for bundle, items in gsc_by_bundle.items():
        d, dims = _parse_gsc_bundle(bundle, items, ds)
        if d is not None:
            gsc_daily_parts.append(d)
        if dims is not None:
            ds.gsc_dims = pd.concat([ds.gsc_dims, dims], ignore_index=True) if len(ds.gsc_dims) else dims

    if len(gsc_daily_parts) > 1:
        g = pd.concat(gsc_daily_parts, ignore_index=True)
        conflicts = g.drop_duplicates().duplicated("date", keep=False)
        if conflicts.any():
            ds.note("warning", "Search Console exports overlap and disagree on some dates; the first export's numbers were kept.")
        g = g.drop_duplicates("date", keep="first")
        ds.note("info", f"Combined {len(gsc_daily_parts)} Search Console exports; overlapping dates were counted once.")
        daily_parts.append(g)
    elif gsc_daily_parts:
        daily_parts.append(gsc_daily_parts[0])

    if daily_parts:
        daily = pd.concat([p for p in daily_parts if len(p)], ignore_index=True) if any(len(p) for p in daily_parts) else ds.daily
        daily = _dedupe(daily, ds)
        ds.daily = daily.sort_values(["date", "source_system", "channel"]).reset_index(drop=True)
    if period_parts:
        ds.period = pd.concat(period_parts, ignore_index=True)
    return ds


def _dedupe(daily: pd.DataFrame, ds: Dataset) -> pd.DataFrame:
    before = len(daily)
    daily = daily.drop_duplicates()
    if len(daily) < before:
        ds.note("warning", f"Removed {before - len(daily)} exact duplicate rows (likely the same export uploaded twice).")
    key = ["date"] + STD_DIMS
    dup = daily.duplicated(key, keep=False)
    if dup.any():
        n = int(dup.sum())
        ds.note(
            "warning",
            f"{n} rows share the same date, source and channel but have different numbers. "
            "Overlapping exports may be double counted; check the date ranges of uploaded files.",
        )
    return daily


def _from_readout(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({c: df[c] if c in df else None for c in DAILY_COLS})
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for m in STD_METRICS:
        out[m] = pd.to_numeric(out[m], errors="coerce")
    return out


def _dims_from_readout(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({c: df[c] if c in df else None for c in DIM_COLS})
    for c in ["period_start", "period_end"]:
        out[c] = pd.to_datetime(out[c], errors="coerce").dt.date
        out[c] = out[c].where(out[c].notna(), None)
    out["period_label"] = out["period_label"].replace({"": None})
    for m in ["clicks", "impressions", "ctr", "position"]:
        out[m] = pd.to_numeric(out[m], errors="coerce")
    return out


def _meta_range(b: TableBlock) -> tuple[date | None, date | None]:
    s = parse_date(b.meta.get("start date", "")) if b.meta else None
    e = parse_date(b.meta.get("end date", "")) if b.meta else None
    return s, e


def _parse_ga4(rf: RawFile, b: TableBlock, mapping: dict, body: list[list[str]], ds: Dataset):
    df = to_frame(body, mapping)
    n = len(df)
    if n == 0:
        return None, None
    start, end = _meta_range(b)
    out = pd.DataFrame(_std_frame(n))
    out["source_system"] = "ga4"
    src = df["source"] if "source" in df else None
    med = df["medium"] if "medium" in df else None
    if "source_medium" in df:
        sm = df["source_medium"].str.split("/", n=1, expand=True)
        src = sm[0].str.strip()
        med = sm[1].str.strip() if sm.shape[1] > 1 else None
    out["source"] = src.values if src is not None else None
    out["medium"] = med.values if med is not None else None
    out["campaign"] = df["campaign"].values if "campaign" in df else None
    if "channel" in df:
        out["channel"] = df["channel"].map(ch.normalize_channel).values
    elif src is not None:
        out["channel"] = [
            ch.channel_from_source_medium(s or "", m or "", c or "")
            for s, m, c in zip(out["source"], out["medium"].fillna(""), out["campaign"].fillna(""))
        ]
    else:
        out["channel"] = "All channels"
        ds.note("info", "GA4 export has no channel or source columns; totals are kept as 'All channels'.", rf.name)
    for m in ["sessions", "users", "conversions"]:
        out[m] = _num(df, m).values

    if "date" in df or "nth_day" in df:
        if "date" in df:
            dates = df["date"].map(parse_date)
        else:
            if not start:
                ds.note("error", "GA4 export uses 'Nth day' but has no start date in its header lines; skipped.", rf.name)
                return None, None
            dates = df["nth_day"].map(lambda v: nth_day_to_date(v, start))
        out.insert(0, "date", dates.values)
        bad = out["date"].isna().sum()
        if bad:
            ds.note("warning", f"{bad} GA4 rows had dates that could not be read and were dropped.", rf.name)
        out = out.dropna(subset=["date"])
        out = out.groupby(["date"] + STD_DIMS, dropna=False, as_index=False)[STD_METRICS].sum(min_count=1)
        return out[DAILY_COLS], None

    out.insert(0, "period_end", end)
    out.insert(0, "period_start", start)
    if not start:
        ds.note("warning", "GA4 export has no date column and no start/end date lines, so its period is unknown.", rf.name)
    ds.note(
        "info",
        "GA4 export has no date column, so it can be summarized but not trended. "
        "For trends, export with a Date dimension (see docs/exporting-data.md).",
        rf.name,
    )
    return None, out[PERIOD_COLS]


def _parse_gads(rf: RawFile, b: TableBlock, mapping: dict, body: list[list[str]], ds: Dataset):
    df = to_frame(body, mapping)
    n = len(df)
    if n == 0:
        return None, None
    rng = None
    for line in b.preamble:
        rng = parse_date_range(line)
        if rng:
            break
    out = pd.DataFrame(_std_frame(n))
    out["source_system"] = "gads"
    out["source"] = "google"
    out["medium"] = "cpc"
    out["campaign"] = df["campaign"].values if "campaign" in df else None
    if "campaign_type" in df:
        out["channel"] = df["campaign_type"].map(ch.channel_from_ads_campaign_type).values
    else:
        out["channel"] = "Paid Search"
    for m in ["impressions", "clicks", "spend", "conversions"]:
        out[m] = _num(df, m).values
    if "currency" in df:
        ds.currencies |= set(df["currency"].dropna().unique()) - {""}

    if "date" in df:
        out.insert(0, "date", df["date"].map(parse_date).values)
        bad = out["date"].isna().sum()
        if bad:
            ds.note("warning", f"{bad} Google Ads rows had dates that could not be read and were dropped.", rf.name)
        out = out.dropna(subset=["date"])
        out = out.groupby(["date"] + STD_DIMS, dropna=False, as_index=False)[STD_METRICS].sum(min_count=1)
        return out[DAILY_COLS], None

    out.insert(0, "period_end", rng[1] if rng else None)
    out.insert(0, "period_start", rng[0] if rng else None)
    if not rng:
        ds.note("warning", "Google Ads export has no Day column and no date range line, so its period is unknown.", rf.name)
    ds.note("info", "Google Ads export has no Day column, so it can be summarized but not trended. Add the Day segment for trends.", rf.name)
    return None, out[PERIOD_COLS]


def _parse_gsc_bundle(bundle: str, items, ds: Dataset):
    """Parse one Search Console export (normally a zip of several CSVs)."""
    period_start = period_end = None
    filter_range = None
    daily = None
    dims = []
    compare_mode = False

    for rf, b, mapping, hidx in items:
        f = _fields(mapping)
        if "filter_name" in f:
            for r in b.rows[hidx + 1:]:
                if len(r) < 2:
                    continue
                k, v = r[0].strip().lower(), r[1].strip()
                if k == "date":
                    filter_range = parse_date_range(v)
                if k in {"search type", "type"}:
                    ds.gsc_search_types.add(v)
            continue

    for rf, b, mapping, hidx in items:
        f = _fields(mapping)
        if "filter_name" in f:
            continue
        body = [r for r in b.rows[hidx + 1:] if r and not is_total_row(r[0])]
        df = to_frame(body, mapping)
        prefixes = sorted({p for _, p in mapping.values() if p})
        if prefixes:
            compare_mode = True
        if "date" in f and not prefixes:
            dates = df["date"].map(parse_date)
            out = pd.DataFrame(_std_frame(len(df)))
            out.insert(0, "date", dates.values)
            out["source_system"] = "gsc"
            out["channel"] = "Organic Search"
            out["source"] = "google"
            out["medium"] = "organic"
            out["clicks"] = _num(df, "clicks").values
            out["impressions"] = _num(df, "impressions").values
            out["avg_position"] = _num(df, "position").values
            out = out.dropna(subset=["date"])
            daily = out[DAILY_COLS]
            if len(daily):
                period_start, period_end = min(daily["date"]), max(daily["date"])
            ds.files.append({"file": rf.name, "bundle": bundle, "detected_as": "Search Console (dates)", "rows": len(daily)})
            continue
        dim = next((d for d in ["query", "page", "country", "device", "search_appearance"] if d in f), None)
        if dim is None:
            ds.note("warning", "Search Console table without a known dimension was skipped.", rf.name)
            continue
        labels = prefixes if prefixes else [""]
        for i, pfx in enumerate(labels):
            def col(m):
                key = f"{pfx}|{m}" if pfx else m
                return _num(df, key)
            part = pd.DataFrame({
                "dimension": dim,
                "item": df[dim].values,
                "period_label": ("current" if i == 0 else "previous") if pfx else None,
                "clicks": col("clicks").values,
                "impressions": col("impressions").values,
                "ctr": col("ctr").values,
                "position": col("position").values,
                "bundle": bundle,
            })
            dims.append(part)
        ds.files.append({"file": rf.name, "bundle": bundle, "detected_as": f"Search Console ({dim})", "rows": len(df)})

    if period_start is None and filter_range:
        period_start, period_end = filter_range
    dims_df = None
    if dims:
        dims_df = pd.concat(dims, ignore_index=True)
        dims_df["period_start"] = dims_df["period_label"].map(lambda l: period_start if l in (None, "current") and not compare_mode else None)
        dims_df["period_end"] = dims_df["period_label"].map(lambda l: period_end if l in (None, "current") and not compare_mode else None)
        if compare_mode:
            ds.note(
                "warning",
                "Search Console export was made with Compare turned on. Breakdowns are split into "
                "'current' and 'previous' by column order; check that this matches what you exported.",
                bundle,
            )
        elif period_start is None:
            ds.note(
                "warning",
                "Search Console breakdowns have no Dates table or date filter, so their period is unknown. "
                "Include the full export zip so the period can be read.",
                bundle,
            )
        dims_df = dims_df[DIM_COLS]
    return daily, dims_df

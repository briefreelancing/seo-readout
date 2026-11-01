"""Column name matching and value parsing.

Every export names its columns differently ("Impr." in Google Ads,
"Top queries" in Search Console, "Session default channel group" in GA4).
This module maps them to one set of canonical field names.

Assumption: numbers use US formatting (1,234.56). Exports from accounts set to
other locales (1.234,56) are not supported in v1 and are flagged by health checks
as unparseable values.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

import pandas as pd

# Canonical field -> accepted header names (lowercase, single spaces).
ALIASES: dict[str, list[str]] = {
    "date": ["date", "day", "date (yyyymmdd)"],
    "nth_day": ["nth day"],
    "channel": [
        "session default channel group",
        "session primary channel group (default channel group)",
        "session primary channel group",
        "default channel group",
        "session default channel grouping",
        "default channel grouping",
        "channel",
        "channel group",
    ],
    "source_medium": ["session source / medium", "source / medium", "session source/medium", "source/medium"],
    "source": ["session source", "source"],
    "medium": ["session medium", "medium"],
    "campaign": ["session campaign", "session campaign name", "campaign", "campaign name"],
    "campaign_type": ["campaign type", "advertising channel type"],
    "sessions": ["sessions"],
    "engaged_sessions": ["engaged sessions"],
    "users": ["total users", "users", "active users"],
    "conversions": ["key events", "session key events", "conversions", "conv."],
    "impressions": ["impressions", "impr.", "impr"],
    "clicks": ["clicks", "url clicks"],
    "spend": ["cost", "spend", "amount spent"],
    "ctr": ["ctr", "url ctr"],
    "position": ["position", "average position", "avg. position"],
    "query": ["top queries", "query", "queries", "search query"],
    "page": ["top pages", "page", "pages", "landing page", "url"],
    "country": ["country", "countries"],
    "device": ["device", "devices", "device category"],
    "search_appearance": ["search appearance"],
    "currency": ["currency code", "currency"],
    "filter_name": ["filter"],
    "filter_value": ["value"],
}

METRIC_FIELDS = {
    "sessions", "engaged_sessions", "users", "conversions", "impressions",
    "clicks", "spend", "ctr", "position",
}

_LOOKUP = {alias: canon for canon, names in ALIASES.items() for alias in names}


def norm_header(h: str) -> str:
    h = h.replace("﻿", "").strip().strip('"').lower()
    return re.sub(r"\s+", " ", h)


def match_column(header: str) -> tuple[str | None, str]:
    """Return (canonical field, period prefix) for a header.

    Search Console "Compare" exports prefix metric columns with the period,
    for example "Last 28 days Clicks". The prefix is returned so callers can
    split the two periods. Exact format of those prefixes is not verified.
    """
    h = norm_header(header)
    if h in _LOOKUP:
        return _LOOKUP[h], ""
    for canon in METRIC_FIELDS:
        for alias in ALIASES[canon]:
            if h.endswith(" " + alias):
                return canon, h[: -len(alias)].strip()
    return None, ""


def map_header(header_row: list[str]) -> dict[int, tuple[str, str]]:
    """Map column index -> (field, prefix) for recognized columns only."""
    mapping: dict[int, tuple[str, str]] = {}
    seen: set[tuple[str, str]] = set()
    for i, h in enumerate(header_row):
        field, prefix = match_column(h)
        if field and (field, prefix) not in seen:
            mapping[i] = (field, prefix)
            seen.add((field, prefix))
    return mapping


def recognized_count(header_row: list[str]) -> int:
    return len(map_header(header_row))


_NUM_STRIP = re.compile(r"[,\s$€£₹¥]|(?<=\d)\s*(USD|EUR|GBP|INR)$", re.IGNORECASE)


def parse_number(value: str | float | int | None) -> float:
    """Parse '1,234', '3.4%', '$12.50', '--' into floats. Percentages return as fractions."""
    if value is None:
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s in {"", "--", "-", "—", "n/a", "N/A", "(not set)", " --"}:
        return math.nan
    pct = s.endswith("%")
    s = _NUM_STRIP.sub("", s.rstrip("%"))
    if s.startswith("<") or s.startswith(">"):
        return math.nan
    try:
        n = float(s)
    except ValueError:
        return math.nan
    return n / 100.0 if pct else n


_DATE_FORMATS = [
    "%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y",
    "%a, %b %d, %Y", "%A, %B %d, %Y", "%d %b %Y", "%d %B %Y",
]


def parse_date(value: str) -> date | None:
    s = str(value).strip().strip('"')
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_date_range(text: str) -> tuple[date, date] | None:
    """Parse 'September 1, 2026 - September 30, 2026' style ranges."""
    t = text.strip().strip('"')
    for sep in [" - ", " – ", " to ", "–"]:
        if sep in t:
            a, b = t.split(sep, 1)
            da, db = parse_date(a), parse_date(b)
            if da and db:
                return (da, db)
    return None


def nth_day_to_date(n: str, start: date) -> date | None:
    try:
        return start + timedelta(days=int(float(n)))
    except (TypeError, ValueError):
        return None


def to_frame(rows: list[list[str]], mapping: dict[int, tuple[str, str]]) -> pd.DataFrame:
    """Build a DataFrame with canonical column names (prefix joined with '|')."""
    cols = {}
    for idx, (field, prefix) in mapping.items():
        key = f"{prefix}|{field}" if prefix else field
        cols[key] = [r[idx] if idx < len(r) else "" for r in rows]
    return pd.DataFrame(cols)


def is_total_row(first_cell: str) -> bool:
    s = first_cell.strip().lower()
    return s.startswith("total") or s.startswith("grand total") or s == "totals"

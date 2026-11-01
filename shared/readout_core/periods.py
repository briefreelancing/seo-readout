"""Comparison periods and small math helpers shared by both skills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass
class Period:
    label: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict:
        return {"label": self.label, "start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def _d(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    return pd.to_datetime(v).date()


def resolve_periods(
    daily: pd.DataFrame,
    current_start=None,
    current_end=None,
    previous_start=None,
    previous_end=None,
    length: int = 28,
) -> dict[str, Period] | None:
    """Default: last `length` days ending on the latest date every source has,
    against the `length` days before it and the same weekdays a year earlier (364 days back)."""
    cs, ce, ps, pe = map(_d, (current_start, current_end, previous_start, previous_end))
    if ce is None:
        if daily.empty:
            return None
        ends = daily.groupby("source_system")["date"].max()
        ce = min(ends)
    if cs is None:
        cs = ce - timedelta(days=length - 1)
    n = (ce - cs).days + 1
    if pe is None:
        pe = cs - timedelta(days=1)
    if ps is None:
        ps = pe - timedelta(days=n - 1)
    return {
        "current": Period("current", cs, ce),
        "previous": Period("previous", ps, pe),
        "year_ago": Period("year_ago", cs - timedelta(days=364), ce - timedelta(days=364)),
    }


def coverage(daily: pd.DataFrame, system: str, p: Period) -> float:
    d = daily[(daily["source_system"] == system) & (daily["date"] >= p.start) & (daily["date"] <= p.end)]
    return round(d["date"].nunique() / p.days, 3) if p.days else 0.0


def in_period(df: pd.DataFrame, p: Period) -> pd.DataFrame:
    return df[(df["date"] >= p.start) & (df["date"] <= p.end)]


def pct_change(cur, prev):
    if cur is None or prev is None:
        return None
    if isinstance(cur, float) and math.isnan(cur) or isinstance(prev, float) and math.isnan(prev):
        return None
    if prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def clean(v, nd: int = 2):
    """Round floats for JSON and turn NaN into None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if math.isnan(f) or math.isinf(f):
        return None
    if nd == 0:
        return int(round(f))
    return round(f, nd)

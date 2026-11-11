"""Find days that are suspiciously low, the usual sign of a tracking or export gap.

A day is flagged only when all of these hold:
  * it is below `share` (10%) of the usual level (the lower of the trailing
    14-day median and the same-weekday median), and
  * a count that low would be very unlikely by chance at the usual level
    (Poisson probability under `p`). This keeps small sites, where 0 clicks on
    a Sunday is normal, from being flagged; and
  * if a companion series is given (Search Console impressions for clicks),
    the companion is also low that day. Search Console clicks can hit zero
    while impressions stay normal; that is real behavior, not missing data.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

LOW_SHARE = 0.10
COMPANION_SHARE = 0.50
P_CHANCE = 0.001
TRAILING_DAYS = 14
WEEKS_SAME_DAY = 6


def trailing_median(s: pd.Series, d: date, n: int = TRAILING_DAYS) -> float | None:
    prior = s[(s.index < d) & (s.index >= d - timedelta(days=n))]
    return float(prior.median()) if len(prior) >= 7 else None


def usual_level(s: pd.Series, d: date) -> float | None:
    """The lower of the trailing 14-day median and the median of the same weekday over the
    previous 6 weeks. Using the lower one stops quiet weekends from looking like gaps."""
    base = trailing_median(s, d)
    if base is None:
        return None
    same = [d - timedelta(weeks=w) for w in range(1, WEEKS_SAME_DAY + 1)]
    vals = s.reindex(same).dropna()
    if len(vals) >= 4:
        return min(base, float(vals.median()))
    return base


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam), computed in log space."""
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0
    logs = [i * math.log(lam) - lam - math.lgamma(i + 1) for i in range(int(k) + 1)]
    top = max(logs)
    return min(1.0, math.exp(top) * sum(math.exp(x - top) for x in logs))


def is_low(value: float, usual: float | None, share: float = LOW_SHARE, p: float = P_CHANCE) -> bool:
    if not usual or usual <= 0 or value >= share * usual:
        return False
    return poisson_cdf(int(math.floor(value)), usual) < p


def low_days(s: pd.Series, start: date | None = None, end: date | None = None,
             companion: pd.Series | None = None) -> list[dict]:
    out = []
    for d, v in s.sort_index().items():
        if (start and d < start) or (end and d > end):
            continue
        usual = usual_level(s, d)
        if not is_low(v, usual):
            continue
        if companion is not None and d in companion.index:
            c_usual = usual_level(companion, d)
            if c_usual and companion[d] >= COMPANION_SHARE * c_usual:
                continue
        out.append({"date": d, "value": float(v), "usual": float(usual)})
    return out

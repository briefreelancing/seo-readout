"""Period totals, channel summaries and the side-by-side comparisons."""

from __future__ import annotations

import pandas as pd

from .load import SYSTEM_LABELS, Dataset
from .periods import Period, clean, in_period, pct_change

SYSTEM_METRICS = {
    "ga4": ["sessions", "users", "conversions"],
    "gsc": ["clicks", "impressions"],
    "gads": ["impressions", "clicks", "spend", "conversions"],
}
SHARE_METRIC = {"ga4": "sessions", "gsc": "clicks", "gads": "clicks"}


def filt(df: pd.DataFrame, system: str, channel=None, source=None, medium=None) -> pd.DataFrame:
    d = df[df["source_system"] == system]
    if channel is not None:
        chans = [channel] if isinstance(channel, str) else list(channel)
        d = d[d["channel"].isin(chans)]
    if source is not None:
        d = d[d["source"].fillna("").str.lower() == source]
    if medium is not None:
        d = d[d["medium"].fillna("").str.lower() == medium]
    return d


def total(df: pd.DataFrame, p: Period, metric: str) -> float | None:
    d = in_period(df, p)
    if d.empty or metric not in d or d[metric].isna().all():
        return None
    return float(d[metric].sum())


def gsc_position(daily: pd.DataFrame, p: Period) -> float | None:
    d = in_period(daily[daily["source_system"] == "gsc"], p)
    d = d.dropna(subset=["avg_position", "impressions"])
    if d.empty or d["impressions"].sum() == 0:
        return None
    return float((d["avg_position"] * d["impressions"]).sum() / d["impressions"].sum())


def channel_summary(ds: Dataset, periods: dict[str, Period]) -> list[dict]:
    rows = []
    daily = ds.daily
    for system in ds.systems():
        sub = daily[daily["source_system"] == system]
        if sub.empty:
            continue
        share_m = SHARE_METRIC[system]
        sys_total = total(sub, periods["current"], share_m) or 0
        for chan in sorted(sub["channel"].dropna().unique()):
            csub = sub[sub["channel"] == chan]
            for m in SYSTEM_METRICS[system]:
                cur = total(csub, periods["current"], m)
                if cur is None:
                    continue
                prev = total(csub, periods["previous"], m)
                yoy = total(csub, periods["year_ago"], m)
                rows.append({
                    "system": SYSTEM_LABELS[system], "system_id": system, "channel": chan, "metric": m,
                    "current": clean(cur), "previous": clean(prev), "change_pct": pct_change(cur, prev),
                    "year_ago": clean(yoy), "yoy_pct": pct_change(cur, yoy),
                    "share_pct": round(cur / sys_total * 100, 1) if m == share_m and sys_total else None,
                })
    return rows


def system_totals(ds: Dataset, periods: dict[str, Period]) -> list[dict]:
    rows = []
    for system in ds.systems():
        sub = ds.daily[ds.daily["source_system"] == system]
        if sub.empty:
            continue
        for m in SYSTEM_METRICS[system]:
            cur = total(sub, periods["current"], m)
            if cur is None:
                continue
            prev = total(sub, periods["previous"], m)
            yoy = total(sub, periods["year_ago"], m)
            rows.append({"system": SYSTEM_LABELS[system], "system_id": system, "metric": m,
                         "current": clean(cur), "previous": clean(prev), "change_pct": pct_change(cur, prev),
                         "year_ago": clean(yoy), "yoy_pct": pct_change(cur, yoy)})
        if system == "gsc":
            pos = [gsc_position(ds.daily, periods[k]) for k in ["current", "previous", "year_ago"]]
            c, i = total(sub, periods["current"], "clicks"), total(sub, periods["current"], "impressions")
            pc, pi = total(sub, periods["previous"], "clicks"), total(sub, periods["previous"], "impressions")
            ctr_c = c / i * 100 if c is not None and i else None
            ctr_p = pc / pi * 100 if pc is not None and pi else None
            rows.append({"system": "Search Console", "system_id": "gsc", "metric": "ctr_pct",
                         "current": clean(ctr_c), "previous": clean(ctr_p),
                         "change_pct": pct_change(ctr_c, ctr_p), "year_ago": None, "yoy_pct": None})
            rows.append({"system": "Search Console", "system_id": "gsc", "metric": "avg_position",
                         "current": clean(pos[0], 1), "previous": clean(pos[1], 1),
                         "change_pct": None, "change_abs": clean(pos[0] - pos[1], 1) if pos[0] and pos[1] else None,
                         "year_ago": clean(pos[2], 1), "yoy_pct": None})
        if system == "gads":
            sp, cl = total(sub, periods["current"], "spend"), total(sub, periods["current"], "clicks")
            psp, pcl = total(sub, periods["previous"], "spend"), total(sub, periods["previous"], "clicks")
            cpc, pcpc = (sp / cl if sp and cl else None), (psp / pcl if psp and pcl else None)
            rows.append({"system": "Google Ads", "system_id": "gads", "metric": "avg_cpc",
                         "current": clean(cpc), "previous": clean(pcpc), "change_pct": pct_change(cpc, pcpc),
                         "year_ago": None, "yoy_pct": None})
    return rows


SIDE_BY_SIDE = [
    {
        "id": "organic",
        "label": "Google organic search",
        "a": {"system": "gsc", "metric": "clicks", "label": "Search Console clicks"},
        "b": {"system": "ga4", "metric": "sessions", "label": "GA4 organic sessions from Google",
              "channel": "Organic Search", "source": "google"},
        "why": [
            "GA4 only records a session when its tag loads and, where a consent banner is used, when the visitor accepts tracking.",
            "Ad blockers and privacy browsers can stop GA4 from recording a visit that Search Console still counts as a click.",
            "One session can follow several clicks, and a visitor who clicks and leaves before the page loads is not recorded by GA4.",
            "Search Console reports in Pacific Time; GA4 uses the property's time zone.",
        ],
    },
    {
        "id": "paid_search",
        "label": "Google Ads search campaigns",
        "a": {"system": "gads", "metric": "clicks", "label": "Google Ads clicks (Search campaigns)", "channel": "Paid Search"},
        "b": {"system": "ga4", "metric": "sessions", "label": "GA4 Paid Search sessions", "channel": "Paid Search"},
        "why": [
            "Several ad clicks by the same person can end up in a single GA4 session.",
            "Consent banners and ad blockers stop GA4 from recording some visits.",
            "If auto-tagging is off or a redirect strips the click ID, paid visits can be credited to another channel in GA4.",
            "GA4 groups some Google Ads traffic (for example Performance Max) outside Paid Search.",
        ],
    },
    {
        "id": "ads_conversions",
        "label": "Google Ads conversions",
        "a": {"system": "gads", "metric": "conversions", "label": "Google Ads conversions (all campaigns)"},
        "b": {"system": "ga4", "metric": "conversions", "label": "GA4 key events from google / cpc",
              "source": "google", "medium": "cpc"},
        "why": [
            "Google Ads and GA4 can use different attribution models and lookback windows.",
            "Google Ads can report a conversion on the date of the ad click, while GA4 reports it on the date it happened.",
            "The two tools may count different actions, or count repeat conversions differently.",
            "Consent banners and ad blockers affect GA4 more than Google Ads' own measurement.",
        ],
    },
]


def _side_total(daily, spec, p):
    d = filt(daily, spec["system"], spec.get("channel"), spec.get("source"), spec.get("medium"))
    return total(d, p, spec["metric"])


def side_by_side(ds: Dataset, periods: dict[str, Period]) -> list[dict]:
    out = []
    for spec in SIDE_BY_SIDE:
        res = {"id": spec["id"], "label": spec["label"], "a_label": spec["a"]["label"], "b_label": spec["b"]["label"],
               "why_they_differ": spec["why"], "periods": {}}
        have = False
        for key in ["current", "previous"]:
            a = _side_total(ds.daily, spec["a"], periods[key])
            b = _side_total(ds.daily, spec["b"], periods[key])
            if a is None or b is None:
                continue
            have = True
            res["periods"][key] = {
                "a": clean(a), "b": clean(b), "gap": clean(b - a),
                "ratio_b_to_a": round(b / a, 3) if a else None,
            }
        if have:
            cur = res["periods"].get("current", {}).get("ratio_b_to_a")
            prev = res["periods"].get("previous", {}).get("ratio_b_to_a")
            res["ratio_change_pct"] = pct_change(cur, prev)
            out.append(res)
    return out


def rollup(daily: pd.DataFrame, freq: str = "W") -> pd.DataFrame:
    """Weekly (Monday start) or monthly totals. Incomplete weeks/months are flagged."""
    if daily.empty:
        return daily
    d = daily.copy()
    dt = pd.to_datetime(d["date"])
    if freq == "M":
        d["period_start"] = dt.dt.to_period("M").dt.start_time.dt.date
        expected = dt.dt.days_in_month
    else:
        d["period_start"] = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.date
        expected = pd.Series(7, index=d.index)
    d["_expected"] = expected.values
    metrics = ["sessions", "users", "conversions", "impressions", "clicks", "spend"]
    g = d.groupby(["period_start", "source_system", "channel"], dropna=False)
    out = g[metrics].sum(min_count=1).reset_index()
    days = d.groupby(["period_start", "source_system"])["date"].nunique().rename("days_with_data").reset_index()
    exp = d.groupby(["period_start", "source_system"])["_expected"].first().rename("days_in_period").reset_index()
    out = out.merge(days, on=["period_start", "source_system"]).merge(exp, on=["period_start", "source_system"])
    out["complete"] = out["days_with_data"] >= out["days_in_period"]
    return out

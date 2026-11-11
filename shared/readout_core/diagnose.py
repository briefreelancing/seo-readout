"""Change explainer analysis: the six questions, answered with numbers only.

Every function returns plain dicts so the results can be written to JSON and
narrated without recomputing anything. Thresholds live in THRESHOLDS so they
are easy to find, explain and tune. They are rules of thumb, not standards.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .load import SYSTEM_LABELS, Dataset
from .metrics import filt, gsc_position, side_by_side, total
from .lowdays import LOW_SHARE, low_days, trailing_median
from .periods import Period, clean, in_period, pct_change

THRESHOLDS = {
    "near_zero_share": LOW_SHARE,  # day below 10% of trailing median = possible tracking gap (see lowdays.py,
                                   # which also requires the low value to be unlikely by chance)
    "event_lag_days": 14,          # site changes often show in search after a delay; look this far back
    "sync_drop_share": 0.50,       # channel below 50% of its trailing median that day
    "sync_drop_channels": 0.80,    # ...for at least 80% of channels = all-channel drop
    "ratio_shift_pct": 15.0,       # GA4/Search Console ratio moving this much = check tracking
    "material_change_pct": 5.0,    # smaller changes are treated as noise
    "impressions_change_pct": 10.0,
    "ctr_change_pct": 10.0,        # relative change in CTR
    "position_change": 1.0,        # average position points
    "brand_change_pct": 10.0,
    "z_unusual": 2.0,
    "z_somewhat": 1.0,
    "min_history_windows": 8,
    "changepoint_min_segment": 7,
    "changepoint_window_days": 120,
}


# ---------------------------------------------------------------- focus series
def focus_series(ds: Dataset, metric_choice: str = "auto") -> dict | None:
    choices = {
        "gsc_clicks": ("gsc", "clicks", {}, "Search Console clicks"),
        "ga4_sessions": ("ga4", "sessions", {}, "GA4 sessions"),
        "ga4_organic": ("ga4", "sessions", {"channel": "Organic Search"}, "GA4 organic search sessions"),
        "ga4_conversions": ("ga4", "conversions", {}, "GA4 key events"),
        "ads_clicks": ("gads", "clicks", {}, "Google Ads clicks"),
    }
    systems = set(ds.daily["source_system"].unique()) if not ds.daily.empty else set()
    if metric_choice == "auto":
        metric_choice = "gsc_clicks" if "gsc" in systems else "ga4_sessions" if "ga4" in systems else "ads_clicks" if "gads" in systems else None
    if metric_choice is None or choices[metric_choice][0] not in systems:
        return None
    system, metric, filters, label = choices[metric_choice]
    d = filt(ds.daily, system, **filters)
    s = d.groupby("date")[metric].sum(min_count=1).dropna().sort_index()
    return {"id": metric_choice, "system": system, "metric": metric, "filters": filters, "label": label, "series": s}


# ------------------------------------------------------------ Q1: is it real?
_trailing_median = trailing_median


def q1_is_it_real(ds: Dataset, periods: dict[str, Period], focus: dict) -> dict:
    t = THRESHOLDS
    window = Period("window", periods["previous"].start, periods["current"].end)
    checks = []
    gap_days: dict[str, list[dict]] = {}

    for system, metric in [("ga4", "sessions"), ("gsc", "clicks"), ("gads", "clicks")]:
        s = filt(ds.daily, system).groupby("date")[metric].sum(min_count=1).dropna().sort_index()
        if s.empty:
            continue
        companion = None
        if system == "gsc":
            companion = filt(ds.daily, "gsc").groupby("date")["impressions"].sum(min_count=1).dropna().sort_index()
        flagged = [{"date": x["date"].isoformat(), "value": clean(x["value"], 0), "usual": clean(x["usual"], 0),
                    "missing_estimate": clean(x["usual"] - x["value"], 0)}
                   for x in low_days(s, window.start, window.end, companion=companion)]
        expected_days = window.days
        present = s[(s.index >= window.start) & (s.index <= window.end)].index.nunique()
        missing = expected_days - present
        if flagged:
            gap_days[system] = flagged
            checks.append({"id": f"{system}_near_zero_days", "status": "flag",
                           "message": f"{SYSTEM_LABELS[system]} has {len(flagged)} day(s) far below normal in the analysis window.",
                           "days": flagged})
        if missing > 0:
            checks.append({"id": f"{system}_missing_days", "status": "flag",
                           "message": f"{SYSTEM_LABELS[system]} is missing {missing} of {expected_days} days in the analysis window.",
                           "missing_days": missing})

    ga = filt(ds.daily, "ga4")
    if not ga.empty:
        piv = ga.groupby(["date", "channel"])["sessions"].sum().unstack(fill_value=0).sort_index()
        sync = []
        for d in piv.index[(piv.index >= window.start) & (piv.index <= window.end)]:
            eligible = dropped = 0
            for c in piv.columns:
                med = _trailing_median(piv[c], d)
                if med is None or med < 20:
                    continue
                eligible += 1
                if piv.at[d, c] < t["sync_drop_share"] * med:
                    dropped += 1
            if eligible >= 3 and dropped / eligible >= t["sync_drop_channels"]:
                sync.append({"date": d.isoformat(), "channels_dropped": dropped, "channels_checked": eligible})
        if sync:
            checks.append({"id": "ga4_all_channels_dropped", "status": "flag",
                           "message": "Every GA4 channel dropped on the same day, which usually points to tracking rather than real demand.",
                           "days": sync})
        else:
            checks.append({"id": "ga4_all_channels_dropped", "status": "pass",
                           "message": "No day where every GA4 channel dropped at once."})

    sbs = side_by_side(ds, periods)
    for item in sbs:
        if item["id"] not in {"organic", "paid_search"}:
            continue
        rc = item.get("ratio_change_pct")
        if rc is None:
            continue
        status = "flag" if abs(rc) >= t["ratio_shift_pct"] else "pass"
        cur = item["periods"]["current"]["ratio_b_to_a"]
        prev = item["periods"]["previous"]["ratio_b_to_a"]
        msg = (f"{item['b_label']} for every one of the {item['a_label']} moved from {prev} to {cur} ({rc:+.1f}%). "
               + ("A shift this large can mean tracking, consent or attribution changed." if status == "flag"
                  else "The ratio is stable, so both tools see the same change."))
        checks.append({"id": f"ratio_{item['id']}", "status": status, "message": msg,
                       "ratio_previous": prev, "ratio_current": cur, "ratio_change_pct": rc})

    # How much of the focus change could tracking gaps explain?
    fs = focus["series"]
    cur = _sum(fs, periods["current"])
    prev = _sum(fs, periods["previous"])
    delta = cur - prev if cur is not None and prev is not None else None
    gap_effect = None
    if focus["system"] in gap_days and delta:
        cur_days = [g for g in gap_days[focus["system"]] if periods["current"].start.isoformat() <= g["date"] <= periods["current"].end.isoformat()]
        missing = sum(g["missing_estimate"] or 0 for g in cur_days)
        gap_effect = {"estimated_missing": clean(missing, 0), "focus_change": clean(delta, 0),
                      "share_of_change_pct": clean(missing / abs(delta) * 100, 1) if delta else None}

    focus_flags = [c for c in checks if c["status"] == "flag" and c["id"].startswith(focus["system"])]
    ratio_flags = [c for c in checks if c["status"] == "flag" and c["id"].startswith("ratio_")]
    ratio_pass = [c for c in checks if c["status"] == "pass" and c["id"].startswith("ratio_")]
    if focus_flags and gap_effect and (gap_effect["share_of_change_pct"] or 0) >= 50:
        verdict = "likely_tracking"
        verdict_text = "Most of the change could come from tracking gaps rather than real behavior."
    elif focus_flags or ratio_flags:
        verdict = "partly_tracking"
        verdict_text = "The change looks real, but some tracking issues affect the numbers and should be checked."
    elif ratio_pass:
        verdict = "likely_real"
        verdict_text = "The change appears in more than one tool and no tracking problems were found, so it is probably real."
    else:
        verdict = "likely_real_single_source"
        verdict_text = "No tracking problems were found, but only one source was available to confirm the change."
    other = [c for c in checks if c["status"] == "flag" and not c["id"].startswith(focus["system"]) and not c["id"].startswith("ratio_")]
    if other and verdict.startswith("likely_real"):
        verdict_text += (" Separately, other sources have tracking issues (see checks); they do not affect "
                         f"{focus['label']}, but they do affect any numbers taken from those sources.")
    return {"verdict": verdict, "verdict_text": verdict_text, "checks": checks, "tracking_gap_effect": gap_effect,
            "gap_days": gap_days}


def _sum(s: pd.Series, p: Period) -> float | None:
    v = s[(s.index >= p.start) & (s.index <= p.end)]
    return float(v.sum()) if len(v) else None


# --------------------------------------------------------- Q2: is it unusual?
def q2_is_it_unusual(ds: Dataset, periods: dict[str, Period], focus: dict, length: int) -> dict:
    t = THRESHOLDS
    s = focus["series"]
    cur, prev, yoy = (_sum(s, periods[k]) for k in ["current", "previous", "year_ago"])
    change = pct_change(cur, prev)
    yoy_change = pct_change(cur, yoy)

    # Last year's change over the same two periods (seasonality check).
    ly_prev = Period("ly_prev", periods["previous"].start - timedelta(days=364), periods["previous"].end - timedelta(days=364))
    ly_prev_v = _sum(s, ly_prev)
    last_year_change = pct_change(yoy, ly_prev_v)

    # Typical variation: changes between consecutive windows of the same length, stepping weekly.
    hist = []
    end = periods["previous"].end
    start_limit = s.index.min() if len(s) else end
    while True:
        a = Period("a", end - timedelta(days=length - 1), end)
        b = Period("b", a.start - timedelta(days=length), a.start - timedelta(days=1))
        if b.start < start_limit:
            break
        va, vb = _sum(s, a), _sum(s, b)
        if va is not None and vb:
            hist.append((va - vb) / vb * 100)
        end -= timedelta(days=7)
    z = None
    label = "not_enough_history"
    if len(hist) >= t["min_history_windows"] and change is not None:
        mu, sd = float(np.mean(hist)), float(np.std(hist, ddof=1))
        if sd > 0:
            z = (change - mu) / sd
            label = "unusual" if abs(z) >= t["z_unusual"] else "somewhat_unusual" if abs(z) >= t["z_somewhat"] else "normal"
    seasonal = None
    if change is not None and last_year_change is not None:
        seasonal = (change * last_year_change > 0) and abs(change - last_year_change) <= 10
    return {
        "metric": focus["label"],
        "current": clean(cur), "previous": clean(prev), "year_ago": clean(yoy),
        "change_pct": change, "yoy_pct": yoy_change,
        "last_year_same_periods_change_pct": last_year_change,
        "matches_last_year_pattern": seasonal,
        "typical_change_range_pct": [clean(np.percentile(hist, 10), 1), clean(np.percentile(hist, 90), 1)] if len(hist) >= t["min_history_windows"] else None,
        "history_windows": len(hist),
        "z_score": clean(z, 1),
        "label": label,
    }


# ----------------------------------------------------- Q3: where is it concentrated?
def _contrib(df: pd.DataFrame, key: str, metric: str, net: float, top: int = 10) -> dict:
    df = df.copy()
    df["delta"] = df[f"{metric}_current"].fillna(0) - df[f"{metric}_previous"].fillna(0)
    df["share_of_net_change_pct"] = (df["delta"] / net * 100).round(1) if net else None
    losers = df.sort_values("delta").head(top)
    gainers = df.sort_values("delta", ascending=False).head(top)
    neg = df[df["delta"] < 0]["delta"].sum()
    top3_neg = df.sort_values("delta").head(3)["delta"].clip(upper=0).sum()

    def rows(x):
        out = []
        for _, r in x.iterrows():
            row = {key: r[key], f"{metric}_previous": clean(r[f"{metric}_previous"]), f"{metric}_current": clean(r[f"{metric}_current"]),
                   "change": clean(r["delta"]), "change_pct": pct_change(r[f"{metric}_current"], r[f"{metric}_previous"]),
                   "share_of_net_change_pct": clean(r["share_of_net_change_pct"], 1) if net else None}
            for extra in ["impressions", "position", "ctr"]:
                if f"{extra}_current" in r:
                    row[f"{extra}_previous"] = clean(r[f"{extra}_previous"], 2 if extra != "impressions" else 0)
                    row[f"{extra}_current"] = clean(r[f"{extra}_current"], 2 if extra != "impressions" else 0)
            out.append(row)
        return out

    return {
        "net_change": clean(net),
        "top_declines": rows(losers[losers["delta"] < 0]),
        "top_gains": rows(gainers[gainers["delta"] > 0]),
        "top3_share_of_all_declines_pct": clean(top3_neg / neg * 100, 1) if neg else None,
        "items_compared": int(len(df)),
        "new_items": int(((df[f"{metric}_previous"].fillna(0) == 0) & (df[f"{metric}_current"].fillna(0) > 0)).sum()),
        "lost_items": int(((df[f"{metric}_previous"].fillna(0) > 0) & (df[f"{metric}_current"].fillna(0) == 0)).sum()),
    }


def _match_dims(ds: Dataset, p: Period, label: str) -> pd.DataFrame:
    d = ds.gsc_dims
    if d.empty:
        return d
    tol = timedelta(days=1)
    by_dates = d[d["period_start"].notna() & d["period_end"].notna()]
    if len(by_dates):
        ok = by_dates[(by_dates["period_start"].map(lambda x: abs(x - p.start) <= tol)) &
                      (by_dates["period_end"].map(lambda x: abs(x - p.end) <= tol))]
        if len(ok):
            return ok
    return d[d["period_label"] == label]


def gsc_dimension_pairs(ds: Dataset, periods: dict[str, Period]) -> dict[str, pd.DataFrame]:
    cur = _match_dims(ds, periods["current"], "current")
    prev = _match_dims(ds, periods["previous"], "previous")
    out = {}
    if cur.empty or prev.empty:
        return out
    for dim in sorted(set(cur["dimension"]) & set(prev["dimension"])):
        a = cur[cur["dimension"] == dim].groupby("item")[["clicks", "impressions", "position"]].agg(
            {"clicks": "sum", "impressions": "sum", "position": "mean"})
        b = prev[prev["dimension"] == dim].groupby("item")[["clicks", "impressions", "position"]].agg(
            {"clicks": "sum", "impressions": "sum", "position": "mean"})
        m = a.add_suffix("_current").join(b.add_suffix("_previous"), how="outer").reset_index().rename(columns={"item": dim})
        out[dim] = m
    return out


def q3_where(ds: Dataset, periods: dict[str, Period], focus: dict) -> dict:
    res: dict = {"breakdowns": {}, "unavailable": []}
    if "ga4" in ds.systems() and not filt(ds.daily, "ga4").empty:
        ga = filt(ds.daily, "ga4")
        c = in_period(ga, periods["current"]).groupby("channel")["sessions"].sum().rename("sessions_current")
        p = in_period(ga, periods["previous"]).groupby("channel")["sessions"].sum().rename("sessions_previous")
        m = pd.concat([c, p], axis=1).reset_index().rename(columns={"index": "channel"})
        net = float(m["sessions_current"].fillna(0).sum() - m["sessions_previous"].fillna(0).sum())
        res["breakdowns"]["ga4_channel"] = _contrib(m, "channel", "sessions", net) | {"metric": "GA4 sessions"}
    if "gads" in ds.systems() and not filt(ds.daily, "gads").empty:
        ad = filt(ds.daily, "gads")
        if ad["campaign"].notna().any():
            c = in_period(ad, periods["current"]).groupby("campaign")["clicks"].sum().rename("clicks_current")
            p = in_period(ad, periods["previous"]).groupby("campaign")["clicks"].sum().rename("clicks_previous")
            m = pd.concat([c, p], axis=1).reset_index().rename(columns={"index": "campaign"})
            net = float(m["clicks_current"].fillna(0).sum() - m["clicks_previous"].fillna(0).sum())
            res["breakdowns"]["ads_campaign"] = _contrib(m, "campaign", "clicks", net) | {"metric": "Google Ads clicks"}
            # Campaigns that stopped getting clicks part way through (paused, out of budget, ended).
            window = ad[(ad["date"] >= periods["previous"].start) & (ad["date"] <= periods["current"].end)]
            last_day = window["date"].max()
            stopped = []
            for camp, g in window[window["clicks"].fillna(0) > 0].groupby("campaign"):
                last = g["date"].max()
                if (last_day - last).days >= 3:
                    stopped.append({"campaign": camp, "last_day_with_clicks": last.isoformat(),
                                    "days_without_clicks": (last_day - last).days})
            if stopped:
                res["stopped_ads_campaigns"] = stopped
    pairs = gsc_dimension_pairs(ds, periods)
    if pairs:
        for dim, m in pairs.items():
            net = float(m["clicks_current"].fillna(0).sum() - m["clicks_previous"].fillna(0).sum())
            res["breakdowns"][f"gsc_{dim}"] = _contrib(m, dim, "clicks", net) | {"metric": "Search Console clicks"}
        # Clicks not attributed to any listed query (anonymized or beyond the export row limit).
        if "query" in pairs:
            gsc = filt(ds.daily, "gsc")
            for key in ["current", "previous"]:
                tot = total(gsc, periods[key], "clicks")
                q = pairs["query"][f"clicks_{key}"].sum()
                if tot:
                    res.setdefault("unlisted_query_clicks", {})[key] = {
                        "site_clicks": clean(tot, 0), "listed_query_clicks": clean(q, 0),
                        "unlisted_share_pct": clean((tot - q) / tot * 100, 1)}
    elif "gsc" in ds.systems():
        res["unavailable"].append(
            "Search Console page and query breakdowns need one export for the current period and one for the previous "
            f"period ({periods['current'].start} to {periods['current'].end} and {periods['previous'].start} to "
            f"{periods['previous'].end}).")
    return res


# ------------------------------------------------------- Q4: what kind of change?
def classify(clicks_pct, impr_pct, ctr_rel_pct, pos_change) -> tuple[str, str]:
    t = THRESHOLDS
    if clicks_pct is None:
        return "unknown", "Not enough data to classify."
    if abs(clicks_pct) < t["material_change_pct"]:
        return "no_material_change", "Clicks barely moved."
    worse = pos_change is not None and pos_change >= t["position_change"]
    better = pos_change is not None and pos_change <= -t["position_change"]
    stable_pos = pos_change is not None and abs(pos_change) < t["position_change"]
    if clicks_pct < 0 and worse:
        return "ranking_loss", "Average position got worse, so pages show lower in results and get fewer clicks."
    if clicks_pct > 0 and better:
        return "ranking_gain", "Average position improved."
    if impr_pct is not None and abs(impr_pct) >= t["impressions_change_pct"] and (stable_pos or pos_change is None):
        if impr_pct < 0:
            return "lower_demand_or_visibility", "Impressions fell while position held, so fewer searches showed the site."
        return "higher_demand_or_visibility", "Impressions rose while position held."
    if impr_pct is not None and abs(impr_pct) < t["impressions_change_pct"] and ctr_rel_pct is not None \
            and ctr_rel_pct <= -t["ctr_change_pct"] and (stable_pos or pos_change is None):
        return "serp_change", ("Impressions and position held but fewer people clicked. Something on the results "
                               "page may be taking clicks, such as new features or AI answers, or titles became less appealing.")
    return "mixed", "Several things changed at once; no single pattern explains it."


def _gsc_numbers(c, i, pc, pi, pos, ppos):
    ctr, pctr = (c / i if i else None), (pc / pi if pi else None)
    return {
        "clicks_previous": clean(pc, 0), "clicks_current": clean(c, 0), "clicks_pct": pct_change(c, pc),
        "impressions_previous": clean(pi, 0), "impressions_current": clean(i, 0), "impressions_pct": pct_change(i, pi),
        "ctr_previous_pct": clean(pctr * 100 if pctr is not None else None), "ctr_current_pct": clean(ctr * 100 if ctr is not None else None),
        "ctr_change_pct": pct_change(ctr, pctr),
        "position_previous": clean(ppos, 1), "position_current": clean(pos, 1),
        "position_change": clean(pos - ppos, 1) if pos is not None and ppos is not None else None,
    }


def q4_what_kind(ds: Dataset, periods: dict[str, Period], q3: dict, brand_terms: list[str]) -> dict:
    res: dict = {}
    gsc = filt(ds.daily, "gsc")
    if not gsc.empty:
        c, i = total(gsc, periods["current"], "clicks"), total(gsc, periods["current"], "impressions")
        pc, pi = total(gsc, periods["previous"], "clicks"), total(gsc, periods["previous"], "impressions")
        pos, ppos = gsc_position(ds.daily, periods["current"]), gsc_position(ds.daily, periods["previous"])
        nums = _gsc_numbers(c, i, pc, pi, pos, ppos)
        pattern, why = classify(nums["clicks_pct"], nums["impressions_pct"], nums["ctr_change_pct"], nums["position_change"])
        decomposition = None
        if None not in (c, i, pc, pi) and pi:
            vol = (i - pi) * (pc / pi)
            ctr_eff = i * ((c / i if i else 0) - pc / pi)
            decomposition = {"from_impressions_change": clean(vol, 0), "from_ctr_change": clean(ctr_eff, 0),
                             "total_change": clean(c - pc, 0)}
        res["site"] = {"numbers": nums, "pattern": pattern, "explanation": why, "click_change_split": decomposition}

        pairs = gsc_dimension_pairs(ds, periods)
        if "page" in pairs:
            m = pairs["page"].copy()
            m["delta"] = m["clicks_current"].fillna(0) - m["clicks_previous"].fillna(0)
            def page_rows(rows, keep):
                pages = []
                for _, r in rows.iterrows():
                    if not keep(r["delta"]):
                        continue
                    n = _gsc_numbers(r["clicks_current"], r["impressions_current"], r["clicks_previous"],
                                     r["impressions_previous"], r["position_current"], r["position_previous"])
                    p, w = classify(n["clicks_pct"], n["impressions_pct"], n["ctr_change_pct"], n["position_change"])
                    pages.append({"page": r["page"], "pattern": p, **n})
                return pages
            res["top_declining_pages"] = page_rows(m.sort_values("delta").head(5), lambda x: x < 0)
            res["top_gaining_pages"] = page_rows(m.sort_values("delta", ascending=False).head(5), lambda x: x > 0)

        if brand_terms and "query" in pairs:
            m = pairs["query"].copy()
            terms = [b.lower().strip() for b in brand_terms if b.strip()]
            m["branded"] = m["query"].str.lower().map(lambda q: any(t in q for t in terms))
            out = {}
            for flag, name in [(True, "branded"), (False, "non_branded")]:
                sub = m[m["branded"] == flag]
                cc, pp = sub["clicks_current"].sum(), sub["clicks_previous"].sum()
                out[name] = {"queries": int(len(sub)), "clicks_previous": clean(pp, 0), "clicks_current": clean(cc, 0),
                             "clicks_pct": pct_change(cc, pp),
                             "impressions_previous": clean(sub["impressions_previous"].sum(), 0),
                             "impressions_current": clean(sub["impressions_current"].sum(), 0),
                             "impressions_pct": pct_change(sub["impressions_current"].sum(), sub["impressions_previous"].sum())}
            b, nb = out["branded"]["clicks_pct"], out["non_branded"]["clicks_pct"]
            t = THRESHOLDS["brand_change_pct"]
            if b is not None and nb is not None:
                if b <= -t and nb > -t:
                    out["pattern"], out["explanation"] = "brand_demand", "Only branded searches fell. That points to brand demand, not SEO."
                elif nb <= -t and b > -t:
                    out["pattern"], out["explanation"] = "non_brand", "Non-branded searches fell while branded held. That points to SEO visibility, not brand demand."
                elif b <= -t and nb <= -t:
                    out["pattern"], out["explanation"] = "both", "Both branded and non-branded searches fell."
                elif nb >= t and b < t:
                    out["pattern"], out["explanation"] = "non_brand_gain", "Non-branded searches rose while branded did not. That points to better SEO visibility, not brand demand."
                elif b >= t and nb < t:
                    out["pattern"], out["explanation"] = "brand_demand_gain", "Only branded searches rose. That points to brand demand, such as marketing or PR, not SEO."
                elif b >= t and nb >= t:
                    out["pattern"], out["explanation"] = "both_gain", "Both branded and non-branded searches rose."
                else:
                    out["pattern"], out["explanation"] = "no_clear_split", "Neither branded nor non-branded searches stand out."
            out["brand_terms"] = terms
            out["note"] = "Only listed queries are split. Clicks from queries Search Console does not list are excluded."
            res["brand_split"] = out
        elif not brand_terms:
            res["brand_split"] = {"skipped": "No brand terms were given."}
        else:
            res["brand_split"] = {"skipped": "Query breakdowns for both periods are needed."}
    return res


# ----------------------------------------------------------- Q5: when did it start?
def change_point(s: pd.Series, end: date, window_days: int, min_seg: int) -> dict | None:
    s = s[(s.index > end - timedelta(days=window_days)) & (s.index <= end)].sort_index()
    if len(s) < 2 * min_seg:
        return None
    vals = s.values.astype(float)
    best = None
    for k in range(min_seg, len(vals) - min_seg + 1):
        a, b = vals[:k], vals[k:]
        pooled = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(vals) - 2))
        if pooled == 0:
            continue
        stat = abs(b.mean() - a.mean()) / (pooled * math.sqrt(1 / len(a) + 1 / len(b)))
        if best is None or stat > best[0]:
            best = (stat, k, a.mean(), b.mean())
    if best is None:
        return None
    stat, k, ma, mb = best
    shift = (mb - ma) / ma * 100 if ma else None
    strength = "strong" if stat >= 6 and shift is not None and abs(shift) >= 15 else "moderate" if stat >= 3 else "weak"
    return {"date": s.index[k].isoformat(), "before_daily_avg": clean(ma, 1), "after_daily_avg": clean(mb, 1),
            "shift_pct": clean(shift, 1), "strength": strength, "test_statistic": clean(stat, 1),
            "window_start": s.index[0].isoformat(), "window_end": s.index[-1].isoformat()}


def load_events(path: str | None) -> list[dict]:
    if not path:
        return []
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            d = r.get("date")
            if not d:
                continue
            out.append({"start": d, "end": r.get("end_date") or d, "type": r.get("type", ""),
                        "name": r.get("description") or r.get("name", ""), "source": "your event log"})
    return out


def load_updates(path: Path) -> tuple[list[dict], dict]:
    meta_path = path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({"start": r["start_date"], "end": r.get("end_date") or r["start_date"], "type": r.get("type", ""),
                        "name": r["name"], "source": "Google update list", "url": r.get("source_url", "")})
    return out, meta


def _days_from_event(d: date, s: date, e: date) -> int:
    """0 if the change point falls inside the event; otherwise days after the end (+) or before the start (-)."""
    if s <= d <= e:
        return 0
    return (d - e).days if d > e else (d - s).days


def q5_when(focus: dict, periods: dict[str, Period], events: list[dict], updates: list[dict], updates_meta: dict,
            match_days: int, gap_days: dict, lag_days: int | None = None) -> dict:
    t = THRESHOLDS
    lag_days = t["event_lag_days"] if lag_days is None else lag_days
    cp = change_point(focus["series"], periods["current"].end, t["changepoint_window_days"], t["changepoint_min_segment"])
    res = {"change_point": cp, "matches": [], "match_window_days": match_days, "event_lag_days": lag_days}
    if not cp:
        res["note"] = "Not enough daily data to find when the trend shifted."
        return res
    d = date.fromisoformat(cp["date"])
    for ev in events + updates:
        try:
            s, e = date.fromisoformat(ev["start"]), date.fromisoformat(ev["end"])
        except ValueError:
            continue
        gap = _days_from_event(d, s, e)
        if abs(gap) <= match_days:
            relation = "coincides with"
        elif ev["source"] == "your event log" and 0 < gap <= lag_days:
            # Site changes often take days or weeks to show in search, so look further back for them.
            relation = "follows"
        else:
            continue
        res["matches"].append(ev | {"days_from_change_point": gap, "relation": relation})
    if cp["strength"] == "weak" and res["matches"]:
        res["weak_shift_note"] = ("The trend shift is weak, so matching it to events is less reliable than usual.")
    last = updates_meta.get("last_updated")
    res["update_list_last_updated"] = last
    if last and d > date.fromisoformat(last):
        res["update_list_warning"] = (f"The Google update list was last updated on {last}, before this change point. "
                                      "Recent updates may be missing; check Google's Search Status Dashboard.")
    on_gap = [g["date"] for g in gap_days.get(focus["system"], []) if abs((date.fromisoformat(g["date"]) - d).days) <= 1]
    if on_gap:
        res["tracking_gap_nearby"] = on_gap
    if d < periods["previous"].start:
        res["note"] = "The shift started before the previous period, so the period comparison mixes before and after."
    return res


# ---------------------------------------------------------- Q6: what to check next
def q6_next_checks(q1, q2, q3, q4, q5) -> list[dict]:
    out = []

    def add(check, why, confidence):
        out.append({"check": check, "why": why, "confidence": confidence})

    for c in q1["checks"]:
        if c["status"] != "flag":
            continue
        if c["id"].endswith("near_zero_days") or c["id"] == "ga4_all_channels_dropped":
            days = ", ".join(x["date"] for x in c.get("days", [])[:5])
            system = c["id"].split("_")[0]
            what = {
                "gsc": "a known Search Console data issue, site outages, server errors, robots.txt or noindex changes",
                "gads": "budget caps, billing problems, paused campaigns, disapproved ads",
            }.get(system, "tag deployments, consent banner changes, site outages")
            add(f"Check {SYSTEM_LABELS.get(system, 'tracking')} on {days}: {what}.", c["message"], "high")
        elif c["id"].startswith("ratio_"):
            add("Compare GA4 and Search Console setup: consent mode, tag coverage on all templates, redirects that drop tracking.",
                c["message"], "medium")
        elif c["id"].endswith("missing_days"):
            add("Re-export the data for the full date range before drawing conclusions.", c["message"], "high")

    site = q4.get("site", {})
    pattern = site.get("pattern")
    from .charts import short_labels
    pages = short_labels([p["page"] for p in q4.get("top_declining_pages", []) if p["pattern"] == "ranking_loss"][:3])
    if pattern == "ranking_loss" or pages:
        target = ", ".join(pages) if pages else "the pages losing the most clicks"
        add(f"Look at ranking changes for {target}: compare them with the pages now ranking above them, and check indexing and canonical tags.",
            "Average position got worse for the pages driving the decline.", "high" if pages else "medium")
    gaining = short_labels([p["page"] for p in q4.get("top_gaining_pages", []) if p["pattern"] == "ranking_gain"][:3])
    if pattern == "ranking_gain":
        target = ", ".join(gaining) if gaining else "the pages gaining the most clicks"
        add(f"Find what changed on {target} before the gain (content, internal links, technical fixes) and decide "
            "whether to repeat it on similar pages.",
            "Average position improved for the pages driving the gain.", "high" if gaining else "medium")
        add("Recheck in 2 to 4 weeks before reporting the gain as lasting.",
            "Ranking gains can settle back after a few weeks.", "low")
    if pattern == "higher_demand_or_visibility":
        conf = "low" if q2.get("matches_last_year_pattern") else "medium"
        add("Compare with last year and with search interest for the main queries to see if demand rose.",
            site.get("explanation", ""), conf)
    for c in q3.get("stopped_ads_campaigns", [])[:3]:
        add(f"Confirm whether the Google Ads campaign '{c['campaign']}' was paused, ran out of budget or ended.",
            f"It has had no clicks since {c['last_day_with_clicks']} ({c['days_without_clicks']} days).", "high")
    if pattern == "serp_change":
        add("Search the top losing queries yourself and note what now appears above the site's result (ads, AI answers, other features).",
            site.get("explanation", ""), "medium")
    if pattern == "lower_demand_or_visibility":
        conf = "low" if q2.get("matches_last_year_pattern") else "medium"
        add("Compare with last year and with search interest for the main queries to see if demand dropped.",
            site.get("explanation", ""), conf)
    brand = q4.get("brand_split", {})
    if brand.get("pattern") == "brand_demand_gain":
        add("Check what brand marketing ran in the current period (campaigns, PR, offline activity) so it can be credited.",
            brand["explanation"], "medium")
    if brand.get("pattern") == "brand_demand":
        add("Check what changed in brand marketing: campaigns paused, PR, offline activity, reviews.", brand["explanation"], "medium")

    cp = q5.get("change_point") or {}
    rising = (cp.get("shift_pct") or 0) > 0
    weak = cp.get("strength") == "weak"
    for m in q5.get("matches", []):
        timing = (f"The trend shift {m['relation']} this event" +
                  (f" ({m['days_from_change_point']} days later)." if m["relation"] == "follows" else "."))
        if m["source"] == "your event log":
            if rising:
                add(f"Note what the '{m['name']}' change ({m['start']}) did to the pages that gained, so it can be repeated elsewhere.",
                    timing + " Timing alone does not prove it caused the change.", "low" if weak else "medium")
            else:
                add(f"Review what the '{m['name']}' change ({m['start']}) did to the affected pages: templates, titles, internal links, canonical and noindex tags, redirects.",
                    timing + " Timing alone does not prove it caused the change.", "low" if weak else "medium")
        else:
            add(f"Read Google's guidance for the {m['name']} and review the affected pages against it.",
                f"The trend shift {m['relation']} this update. Timing alone does not prove it caused the change.", "low")
    if q2.get("matches_last_year_pattern"):
        add("Treat part of this as seasonal: the same periods last year moved in the same direction by a similar amount.",
            "Last year's change over the same dates was similar.", "medium")
    for u in q3.get("unavailable", []):
        add("Export Search Console data for each period separately to see which pages and queries changed.", u, "high")
    merged: dict[str, dict] = {}
    for item in out:
        if item["check"] in merged:
            merged[item["check"]]["why"] += " " + item["why"]
        else:
            merged[item["check"]] = dict(item)
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(merged.values(), key=lambda x: order[x["confidence"]])

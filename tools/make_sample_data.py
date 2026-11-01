"""Generate synthetic sample exports for a fictional bakery, "Northwind Bakery".

The files imitate the layout of GA4, Search Console and Google Ads exports
closely enough to exercise the parsers. They are NOT copies of real exports,
and real exports may differ. Replace them with anonymized real exports when
available.

The story baked into the data:
  * 2026-10-06 onward: sourdough blog pages lose rankings (position ~4 -> ~9)
  * 2026-10-05: user event log records a site redesign launch
  * 2026-09-24 to 2026-10-08: Google September 2026 spam update (from the update list)
  * 2026-10-12: GA4 tag breaks for one day (sessions near zero)
  * Branded searches stay flat

Run:  python tools/make_sample_data.py
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample-data"
rng = np.random.default_rng(42)

START = date(2025, 7, 1)
END = date(2026, 10, 25)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
DROP = date(2026, 10, 6)
TAG_BREAK = date(2026, 10, 12)
CUR = (date(2026, 9, 28), END)
PREV = (date(2026, 8, 31), date(2026, 9, 27))

# query -> (page, base daily impressions, base position, branded)
QUERIES = {
    "northwind bakery": ("/", 260, 1.1, True),
    "northwind bakery hours": ("/locations", 90, 1.2, True),
    "northwind bakery menu": ("/menu", 70, 1.3, True),
    "sourdough starter guide": ("/blog/sourdough-starter-guide", 900, 3.8, False),
    "how to make sourdough starter": ("/blog/sourdough-starter-guide", 700, 4.2, False),
    "sourdough discard recipes": ("/blog/sourdough-discard-recipes", 650, 4.5, False),
    "how to shape sourdough": ("/blog/how-to-shape-sourdough", 420, 5.0, False),
    "croissant lamination": ("/blog/croissant-lamination", 300, 6.5, False),
    "best croissants chicago": ("/menu", 380, 7.0, False),
    "custom birthday cakes chicago": ("/custom-cakes", 520, 6.0, False),
    "gluten free bread chicago": ("/menu", 210, 8.5, False),
    "bakery near me": ("/locations", 800, 11.0, False),
}
SOURDOUGH = {q for q, v in QUERIES.items() if "sourdough" in v[0]}


def ctr_at(pos: float) -> float:
    return max(0.005, 0.32 * math.exp(-0.33 * (pos - 1)))


def season(d: date) -> float:
    doy = d.timetuple().tm_yday
    weekly = 1.12 if d.weekday() >= 5 else 1.0
    return (1 + 0.12 * math.sin(2 * math.pi * (doy - 80) / 365)) * weekly


def ramp(d: date) -> float:
    """0 before the drop, rising to 1 over three days."""
    if d < DROP:
        return 0.0
    return min(1.0, ((d - DROP).days + 1) / 3)


# ---- Search Console: per query per day -------------------------------------
q_daily = {}
for q, (page, imp, pos, brand) in QUERIES.items():
    rows = []
    for d in DAYS:
        r = ramp(d) if q in SOURDOUGH else 0.0
        p = pos + 5.0 * r + rng.normal(0, 0.25)
        i = imp * season(d) * (1 - 0.2 * r) * rng.normal(1, 0.06)
        c = i * ctr_at(p) * rng.normal(1, 0.08)
        rows.append((d, max(i, 0), max(c, 0), max(p, 1)))
    q_daily[q] = rows

ANON = 1.15  # anonymized queries add clicks/impressions not visible per query


def site_daily():
    out = []
    for idx, d in enumerate(DAYS):
        imp = sum(q_daily[q][idx][1] for q in QUERIES) * ANON
        clk = sum(q_daily[q][idx][2] for q in QUERIES) * ANON
        pos = sum(q_daily[q][idx][3] * q_daily[q][idx][1] for q in QUERIES) / (imp / ANON)
        out.append((d, round(clk), round(imp), pos))
    return out


SITE = site_daily()


def in_range(d, rng_):
    return rng_[0] <= d <= rng_[1]


def agg_queries(rng_):
    res = {}
    for q in QUERIES:
        rows = [r for r in q_daily[q] if in_range(r[0], rng_)]
        imp = sum(r[1] for r in rows)
        clk = sum(r[2] for r in rows)
        pos = sum(r[3] * r[1] for r in rows) / imp
        res[q] = (round(clk), round(imp), pos)
    return res


def agg_pages(rng_):
    qs = agg_queries(rng_)
    pages = {}
    for q, (c, i, p) in qs.items():
        page = "https://www.northwindbakery.example" + QUERIES[q][0]
        pc, pi, pp = pages.get(page, (0, 0, 0))
        pages[page] = (pc + c, pi + i, pp + p * i)
    return {k: (round(c * ANON), round(i * ANON), pp / i) for k, (c, i, pp) in pages.items()}


def split(total_c, total_i, shares, pos_shift):
    out = {}
    for name, s in shares.items():
        out[name] = (round(total_c * s * rng.normal(1, 0.03)), round(total_i * s * rng.normal(1, 0.03)), pos_shift.get(name, 0))
    return out


def fmt_ctr(c, i):
    return f"{(c / i * 100 if i else 0):.2f}%"


def gsc_zip(path: Path, rng_, date_label: str):
    site = [r for r in SITE if in_range(r[0], rng_)]
    tc = sum(r[1] for r in site)
    ti = sum(r[2] for r in site)
    tp = sum(r[3] * r[2] for r in site) / ti
    files = {}

    def table(header, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue()

    files["Dates.csv"] = table(
        ["Date", "Clicks", "Impressions", "CTR", "Position"],
        [[d.isoformat(), c, i, fmt_ctr(c, i), f"{p:.1f}"] for d, c, i, p in sorted(site, reverse=True)],
    )
    qs = sorted(agg_queries(rng_).items(), key=lambda kv: -kv[1][0])
    files["Queries.csv"] = table(
        ["Top queries", "Clicks", "Impressions", "CTR", "Position"],
        [[q, c, i, fmt_ctr(c, i), f"{p:.1f}"] for q, (c, i, p) in qs],
    )
    ps = sorted(agg_pages(rng_).items(), key=lambda kv: -kv[1][0])
    files["Pages.csv"] = table(
        ["Top pages", "Clicks", "Impressions", "CTR", "Position"],
        [[p, c, i, fmt_ctr(c, i), f"{pos:.1f}"] for p, (c, i, pos) in ps],
    )
    countries = split(tc, ti, {"United States": 0.86, "Canada": 0.07, "United Kingdom": 0.04, "India": 0.03}, {})
    files["Countries.csv"] = table(
        ["Country", "Clicks", "Impressions", "CTR", "Position"],
        [[k, c, i, fmt_ctr(c, i), f"{tp + s:.1f}"] for k, (c, i, s) in countries.items()],
    )
    devices = split(tc, ti, {"Mobile": 0.71, "Desktop": 0.26, "Tablet": 0.03}, {"Desktop": 0.4})
    files["Devices.csv"] = table(
        ["Device", "Clicks", "Impressions", "CTR", "Position"],
        [[k, c, i, fmt_ctr(c, i), f"{tp + s:.1f}"] for k, (c, i, s) in devices.items()],
    )
    files["Search appearance.csv"] = table(["Search Appearance", "Clicks", "Impressions", "CTR", "Position"], [])
    files["Filters.csv"] = table(["Filter", "Value"], [["Search type", "Web"], ["Date", date_label]])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, "﻿" + text)


# ---- Google Ads ---------------------------------------------------------------
CAMPAIGNS = {
    "Brand - Search": ("Search", 400, 0.11, 0.45, 0.06),
    "Custom Cakes - Search": ("Search", 1500, 0.045, 1.80, 0.04),
    "PMax - Local": ("Performance Max", 5200, 0.012, 0.65, 0.03),
}
ads_rows = []
for d in DAYS:
    for camp, (ctype, imp, ctr, cpc, cvr) in CAMPAIGNS.items():
        i = imp * season(d) * rng.normal(1, 0.08)
        c = i * ctr * rng.normal(1, 0.1)
        cost = c * cpc * rng.normal(1, 0.05)
        conv = c * cvr * rng.normal(1, 0.25)
        ads_rows.append((d, camp, ctype, round(i), round(c), round(cost, 2), round(max(conv, 0), 2)))


def write_ads(path: Path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        f.write("Campaign report\n")
        f.write(f"{START:%B} {START.day}, {START.year} - {END:%B} {END.day}, {END.year}\n")
        w = csv.writer(f)
        w.writerow(["Day", "Campaign", "Campaign type", "Currency code", "Impr.", "Clicks", "Cost", "Conversions"])
        for d, camp, ctype, i, c, cost, conv in ads_rows:
            w.writerow([d.isoformat(), camp, ctype, "USD", f"{i:,}", f"{c:,}", f"{cost:,.2f}", f"{conv:.2f}"])
        ti = sum(r[3] for r in ads_rows)
        tc = sum(r[4] for r in ads_rows)
        tcost = sum(r[5] for r in ads_rows)
        tconv = sum(r[6] for r in ads_rows)
        w.writerow(["Total: Account", "--", "--", "USD", f"{ti:,}", f"{tc:,}", f"{tcost:,.2f}", f"{tconv:.2f}"])


# ---- GA4 -----------------------------------------------------------------------
def write_ga4(path: Path):
    site = {d: c for d, c, _, _ in SITE}
    ads_by_day = {}
    for d, camp, ctype, i, c, cost, conv in ads_rows:
        if ctype == "Search":
            ads_by_day[d] = ads_by_day.get(d, 0) + c
    pmax_by_day = {}
    for d, camp, ctype, i, c, cost, conv in ads_rows:
        if ctype != "Search":
            pmax_by_day[d] = pmax_by_day.get(d, 0) + c
    rows = []
    for d in DAYS:
        tag = 0.03 if d == TAG_BREAK else 1.0
        g = site[d] * 0.85 * rng.normal(1, 0.04)
        series = [
            ("Organic Search", "google / organic", g, 0.020),
            ("Organic Search", "bing / organic", g * 0.08 * rng.normal(1, 0.1), 0.020),
            ("Direct", "(direct) / (none)", 140 * season(d) * rng.normal(1, 0.08), 0.035),
            ("Referral", "yelp.com / referral", 35 * rng.normal(1, 0.15), 0.025),
            ("Organic Social", "instagram.com / referral", 45 * season(d) * rng.normal(1, 0.2), 0.010),
            ("Email", "newsletter / email", (160 if d.weekday() == 1 else 12) * rng.normal(1, 0.1), 0.030),
            ("Paid Search", "google / cpc", ads_by_day[d] * 0.9 * rng.normal(1, 0.05), 0.045),
            ("Cross-network", "google / cpc", pmax_by_day[d] * 0.8 * rng.normal(1, 0.08), 0.020),
        ]
        for chname, sm, sess, cvr in series:
            s = max(0, round(sess * tag))
            rows.append((d, chname, sm, s, round(s * 0.82), round(s * cvr * rng.normal(1, 0.2))))
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# ----------------------------------------\n")
        f.write("# Free form 1\n")
        f.write("# Account: Northwind Bakery\n")
        f.write("# Property: Northwind Bakery - GA4\n")
        f.write("# ----------------------------------------\n")
        f.write("#\n")
        f.write(f"# Start date: {START:%Y%m%d}\n")
        f.write(f"# End date: {END:%Y%m%d}\n")
        w = csv.writer(f)
        w.writerow(["Date", "Session default channel group", "Session source / medium", "Sessions", "Total users", "Key events"])
        for d, chname, sm, s, u, k in rows:
            w.writerow([f"{d:%Y%m%d}", chname, sm, s, u, k])


def write_events(path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "end_date", "type", "description"])
        w.writerow(["2026-03-02", "", "content", "Published sourdough discard recipes post"])
        w.writerow(["2026-10-05", "", "site change", "Site redesign launched (new blog template)"])
        w.writerow(["2026-10-12", "", "tracking", "Cookie banner update deployed"])


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    gsc_zip(OUT / "gsc_last_16_months.zip", (START, END), "Custom")
    gsc_zip(OUT / "gsc_current_28_days.zip", CUR, "Last 28 days")
    gsc_zip(OUT / "gsc_previous_28_days.zip", PREV, "Custom")
    write_ads(OUT / "google_ads_campaigns_daily.csv")
    write_ga4(OUT / "ga4_daily_channels.csv")
    write_events(OUT / "events.csv")
    print("Sample data written to", OUT)

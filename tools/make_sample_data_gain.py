"""Generate a second synthetic dataset: "Lakeview Plumbing" (fictional), where traffic GAINS.

Like make_sample_data.py, these files imitate export layouts closely enough to exercise the
parsers. They are NOT copies of real exports.

Different from Northwind Bakery on purpose, so the parsers see new shapes:
  * the main story is a GAIN, not a drop
  * extra quirks: (not set) and Unassigned rows, a missing GA4 day, an AI referral source,
    queries with commas/quotes/accents, non-empty Search appearance, a paused Ads campaign,
    several Ads total rows

Story:
  * 2026-10-15: event log records a refresh of the water heater service pages
  * 2026-10-20 onward: water heater pages climb from about position 9 to about position 4
  * 2026-10-27: "Brand - Search" Ads campaign paused (no rows after that)
  * 2026-11-02: GA4 day missing from the export (gap)
  * winter seasonality: frozen pipe searches rise from November
  * chatgpt.com referrals grow slowly through 2026

Run:  python tools/make_sample_data_gain.py
"""

from __future__ import annotations

import csv
import io
import math
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "sample-data" / "lakeview-plumbing"
rng = np.random.default_rng(7)

START = date(2025, 7, 15)
END = date(2026, 11, 8)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
LIFT = date(2026, 10, 20)
PAUSE = date(2026, 10, 27)
GA4_GAP = date(2026, 11, 2)
CUR = (date(2026, 10, 12), END)
PREV = (date(2026, 9, 14), date(2026, 10, 11))
SITE_URL = "https://www.lakeviewplumbing.example"

# query -> (page, base daily impressions, base position, kind)
QUERIES = {
    "lakeview plumbing": ("/", 180, 1.1, "brand"),
    "lakeview plumbing reviews": ("/reviews", 45, 1.4, "brand"),
    "water heater installation": ("/services/water-heater-installation", 600, 9.2, "lift"),
    "tankless water heater cost": ("/services/tankless-water-heaters", 520, 9.8, "lift"),
    "water heater repair near me": ("/services/water-heater-repair", 700, 10.5, "lift"),
    "emergency plumber": ("/emergency", 900, 7.5, "flat"),
    "emergency plumber 24/7, evanston": ("/emergency", 140, 4.0, "flat"),
    "frozen pipes what to do": ("/blog/frozen-pipes", 350, 5.5, "winter"),
    "how to thaw \"frozen\" pipes": ("/blog/frozen-pipes", 120, 6.0, "winter"),
    "drain cleaning": ("/services/drain-cleaning", 480, 8.0, "flat"),
    "sump pump replacement": ("/services/sump-pumps", 260, 7.2, "flat"),
    "plombier près de moi": ("/fr/plombier", 25, 12.0, "flat"),
}


def ctr_at(pos: float) -> float:
    return max(0.004, 0.30 * math.exp(-0.30 * (pos - 1)))


def season(d: date) -> float:
    weekly = 0.85 if d.weekday() >= 5 else 1.0
    return weekly


def winter(d: date) -> float:
    """Peaks mid-January, low in summer."""
    doy = d.timetuple().tm_yday
    return 1 + 0.9 * max(0.0, math.cos(2 * math.pi * (doy - 15) / 365))


def ramp(d: date) -> float:
    if d < LIFT:
        return 0.0
    return min(1.0, ((d - LIFT).days + 1) / 5)


q_daily = {}
for q, (page, imp, pos, kind) in QUERIES.items():
    rows = []
    for d in DAYS:
        r = ramp(d) if kind == "lift" else 0.0
        p = pos - 5.0 * r + rng.normal(0, 0.3)
        mult = season(d) * (winter(d) if kind == "winter" else 1.0) * (1 + 0.25 * r)
        i = imp * mult * rng.normal(1, 0.07)
        c = i * ctr_at(p) * rng.normal(1, 0.08)
        rows.append((d, max(i, 0), max(c, 0), max(p, 1)))
    q_daily[q] = rows

ANON = 1.2


def site_daily():
    out = []
    for idx, d in enumerate(DAYS):
        imp = sum(q_daily[q][idx][1] for q in QUERIES) * ANON
        clk = sum(q_daily[q][idx][2] for q in QUERIES) * ANON
        pos = sum(q_daily[q][idx][3] * q_daily[q][idx][1] for q in QUERIES) / (imp / ANON)
        out.append((d, round(clk), round(imp), pos))
    return out


SITE = site_daily()


def in_range(d, r):
    return r[0] <= d <= r[1]


def agg_queries(r):
    res = {}
    for q in QUERIES:
        rows = [x for x in q_daily[q] if in_range(x[0], r)]
        imp = sum(x[1] for x in rows)
        clk = sum(x[2] for x in rows)
        res[q] = (round(clk), round(imp), sum(x[3] * x[1] for x in rows) / imp)
    return res


def agg_pages(r):
    pages = {}
    for q, (c, i, p) in agg_queries(r).items():
        page = SITE_URL + QUERIES[q][0]
        if QUERIES[q][0] == "/emergency" and "evanston" in q:
            page = SITE_URL + "/emergency?utm_source=gbp&loc=evanston"
        pc, pi, pp = pages.get(page, (0, 0, 0))
        pages[page] = (pc + c, pi + i, pp + p * i)
    return {k: (round(c * ANON), round(i * ANON), pp / i) for k, (c, i, pp) in pages.items()}


def fmt_ctr(c, i):
    return f"{(c / i * 100 if i else 0):.2f}%"


def gsc_zip(path: Path, r, date_label: str):
    site = [x for x in SITE if in_range(x[0], r)]
    tc = sum(x[1] for x in site)
    ti = sum(x[2] for x in site)
    tp = sum(x[3] * x[2] for x in site) / ti

    def table(header, rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue()

    files = {}
    files["Dates.csv"] = table(
        ["Date", "Clicks", "Impressions", "CTR", "Position"],
        [[d.isoformat(), c, i, fmt_ctr(c, i), f"{p:.2f}"] for d, c, i, p in sorted(site, reverse=True)],
    )
    qs = sorted(agg_queries(r).items(), key=lambda kv: -kv[1][0])
    files["Queries.csv"] = table(
        ["Top queries", "Clicks", "Impressions", "CTR", "Position"],
        [[q, c, i, fmt_ctr(c, i), f"{p:.2f}"] for q, (c, i, p) in qs],
    )
    ps = sorted(agg_pages(r).items(), key=lambda kv: -kv[1][0])
    files["Pages.csv"] = table(
        ["Top pages", "Clicks", "Impressions", "CTR", "Position"],
        [[p, c, i, fmt_ctr(c, i), f"{pos:.2f}"] for p, (c, i, pos) in ps],
    )

    def split(shares, shift):
        rows = []
        for name, s in shares.items():
            c = round(tc * s * rng.normal(1, 0.03))
            i = round(ti * s * rng.normal(1, 0.03))
            rows.append([name, c, i, fmt_ctr(c, i), f"{tp + shift.get(name, 0):.2f}"])
        return rows

    files["Countries.csv"] = table(
        ["Country", "Clicks", "Impressions", "CTR", "Position"],
        split({"United States": 0.95, "Canada": 0.03, "Mexico": 0.01, "Côte d'Ivoire": 0.01}, {"Canada": 2.1}),
    )
    files["Devices.csv"] = table(
        ["Device", "Clicks", "Impressions", "CTR", "Position"],
        split({"Mobile": 0.78, "Desktop": 0.2, "Tablet": 0.02}, {"Desktop": 0.6}),
    )
    files["Search appearance.csv"] = table(
        ["Search Appearance", "Clicks", "Impressions", "CTR", "Position"],
        [["Review snippet", round(tc * 0.04), round(ti * 0.03), fmt_ctr(tc * 0.04, ti * 0.03), f"{tp - 1:.2f}"]],
    )
    files["Filters.csv"] = table(["Filter", "Value"], [["Search type", "Web"], ["Date", date_label]])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, "﻿" + text)


CAMPAIGNS = {
    "Brand - Search": ("Search", 150, 0.14, 0.60, 0.10),
    "Water Heaters - Search": ("Search", 350, 0.05, 6.40, 0.05),
    "Emergency Plumber - Search": ("Search", 400, 0.06, 9.10, 0.07),
    "PMax | Local Services": ("Performance Max", 3000, 0.01, 1.90, 0.03),
}
ads_rows = []
for d in DAYS:
    for camp, (ctype, imp, ctr, cpc, cvr) in CAMPAIGNS.items():
        if camp == "Brand - Search" and d >= PAUSE:
            continue
        w = winter(d) if camp.startswith("Emergency") else 1.0
        i = imp * season(d) * w * rng.normal(1, 0.08)
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
        for label, filt in [
            ("Total: Search", lambda r: r[2] == "Search"),
            ("Total: Performance Max", lambda r: r[2] == "Performance Max"),
            ("Total: Account", lambda r: True),
        ]:
            sel = [r for r in ads_rows if filt(r)]
            w.writerow([
                label, "--", "--", "USD",
                f"{sum(r[3] for r in sel):,}", f"{sum(r[4] for r in sel):,}",
                f"{sum(r[5] for r in sel):,.2f}", f"{sum(r[6] for r in sel):.2f}",
            ])


def write_ga4(path: Path):
    site = {d: c for d, c, _, _ in SITE}
    paid = {}
    pmax = {}
    for d, camp, ctype, i, c, cost, conv in ads_rows:
        bucket = paid if ctype == "Search" else pmax
        bucket[d] = bucket.get(d, 0) + c
    rows = []
    for d in DAYS:
        if d == GA4_GAP:
            continue
        g = site[d] * 0.83 * rng.normal(1, 0.04)
        months_in = max(0, (d - date(2026, 1, 1)).days / 30)
        series = [
            ("Organic Search", "google / organic", g, 0.06),
            ("Organic Search", "bing / organic", g * 0.11 * rng.normal(1, 0.1), 0.06),
            ("Direct", "(direct) / (none)", 110 * season(d) * rng.normal(1, 0.08), 0.08),
            ("Referral", "yelp.com / referral", 40 * rng.normal(1, 0.15), 0.07),
            ("Referral", "nextdoor.com / referral", 18 * rng.normal(1, 0.2), 0.05),
            ("Referral", "chatgpt.com / referral", (2 + 1.1 * months_in) * rng.normal(1, 0.25), 0.09),
            ("Organic Social", "facebook.com / referral", 22 * rng.normal(1, 0.2), 0.02),
            ("Paid Search", "google / cpc", paid.get(d, 0) * 0.92 * rng.normal(1, 0.05), 0.08),
            ("Cross-network", "google / cpc", pmax.get(d, 0) * 0.8 * rng.normal(1, 0.08), 0.03),
            ("Unassigned", "(not set) / (not set)", 6 * rng.normal(1, 0.4), 0.0),
        ]
        for ch, sm, sess, cvr in series:
            s = max(0, round(sess))
            if s == 0:
                continue
            rows.append((d, ch, sm, s, round(s * 0.79), round(s * cvr * rng.normal(1, 0.2))))
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# ----------------------------------------\n")
        f.write("# Free form 1\n")
        f.write("# Account: Lakeview Plumbing\n")
        f.write("# Property: lakeviewplumbing.example - GA4\n")
        f.write("# ----------------------------------------\n")
        f.write("#\n")
        f.write(f"# Start date: {START:%Y%m%d}\n")
        f.write(f"# End date: {END:%Y%m%d}\n")
        w = csv.writer(f)
        w.writerow(["Date", "Session default channel group", "Session source / medium", "Sessions", "Total users", "Key events"])
        for d, ch, sm, s, u, k in rows:
            w.writerow([f"{d:%Y%m%d}", ch, sm, s, u, max(k, 0)])


def write_events(path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "end_date", "type", "description"])
        w.writerow(["2026-06-01", "", "content", "Launched French-language landing page"])
        w.writerow(["2026-10-15", "", "content", "Refreshed water heater service pages (new copy, FAQ, pricing table)"])
        w.writerow(["2026-10-27", "", "ads", "Paused Brand - Search campaign to test organic brand coverage"])
        w.writerow(["2026-11-01", "2026-11-30", "campaign", "November furnace and water heater tune-up promo"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    gsc_zip(OUT / "gsc_last_16_months.zip", (START, END), "Custom")
    gsc_zip(OUT / "gsc_current_28_days.zip", CUR, "Last 28 days")
    gsc_zip(OUT / "gsc_previous_28_days.zip", PREV, "Custom")
    write_ads(OUT / "google_ads_campaigns_daily.csv")
    write_ga4(OUT / "ga4_daily_channels.csv")
    write_events(OUT / "events.csv")
    print("written to", OUT)

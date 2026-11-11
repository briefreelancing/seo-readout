"""End-to-end and unit tests. Run: python -m pytest -q"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "skills" / "change-explainer" / "scripts"))

from readout_core.columns import parse_date, parse_date_range, parse_number  # noqa: E402
from readout_core.fileio import decode_bytes, split_blocks  # noqa: E402
from readout_core.load import load  # noqa: E402

SAMPLE = ROOT / "sample-data" / "northwind-bakery"
GAIN = ROOT / "sample-data" / "lakeview-plumbing"
AGG = ROOT / "skills" / "traffic-aggregator" / "scripts" / "aggregate.py"
EXPLAIN = ROOT / "skills" / "change-explainer" / "scripts" / "explain.py"
GSC = [SAMPLE / "gsc_last_16_months.zip", SAMPLE / "gsc_current_28_days.zip", SAMPLE / "gsc_previous_28_days.zip"]
ALL = [SAMPLE / "ga4_daily_channels.csv", SAMPLE / "google_ads_campaigns_daily.csv", *GSC]


@pytest.fixture(scope="session", autouse=True)
def sample_data():
    if not (SAMPLE / "ga4_daily_channels.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_data.py")], check=True)


def test_parse_number():
    assert parse_number("1,234") == 1234
    assert parse_number("3.45%") == pytest.approx(0.0345)
    assert parse_number("$12.50") == 12.5
    assert parse_number("--") != parse_number("--")  # NaN


def test_parse_dates():
    assert str(parse_date("20261005")) == "2026-10-05"
    assert str(parse_date("Oct 5, 2026")) == "2026-10-05"
    a, b = parse_date_range("September 1, 2026 - September 30, 2026")
    assert (str(a), str(b)) == ("2026-09-01", "2026-09-30")


def test_utf16_tab_export(tmp_path):
    text = "Campaign report\nJuly 1, 2026 - July 2, 2026\nDay\tCampaign\tImpr.\tClicks\tCost\n2026-07-01\tBrand\t1,000\t50\t20.00\n2026-07-02\tBrand\t900\t40\t18.00\n"
    p = tmp_path / "ads.csv"
    p.write_bytes(text.encode("utf-16"))
    assert "Campaign" in decode_bytes(p.read_bytes())
    ds = load([p])
    assert set(ds.daily["source_system"]) == {"gads"}
    assert ds.daily["clicks"].sum() == 90


def test_ga4_comment_header_block():
    blocks = split_blocks("# Start date: 20260101\n# End date: 20260102\nDate,Sessions\n20260101,5\n")
    assert blocks[0].meta["start date"] == "20260101"


def test_loader_finds_all_sources():
    ds = load(ALL)
    assert set(ds.systems()) == {"ga4", "gsc", "gads"}
    gsc = ds.daily[ds.daily["source_system"] == "gsc"]
    assert gsc["date"].is_unique  # overlapping Search Console exports counted once
    assert set(ds.gsc_dims["dimension"]) >= {"query", "page", "country", "device"}


def test_aggregator_end_to_end(tmp_path):
    out = tmp_path / "agg"
    r = subprocess.run([sys.executable, str(AGG), *map(str, ALL[:3]), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = json.loads((out / "aggregate_summary.json").read_text())
    assert (out / "readout_workbook.xlsx").exists()
    ids = {x["id"] for x in s["side_by_side"]}
    assert {"organic", "paid_search", "ads_conversions"} <= ids
    assert any(c["check"] == "near_zero_days" for c in s["health"])  # the planted GA4 tag break


def test_explainer_end_to_end(tmp_path):
    out = tmp_path / "ex"
    r = subprocess.run([sys.executable, str(EXPLAIN), *map(str, ALL), "--out", str(out),
                        "--events", str(SAMPLE / "events.csv"), "--brand-terms", "northwind"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    f = json.loads((out / "findings.json").read_text())
    assert f["q1_is_it_real"]["verdict"] == "likely_real"
    assert f["q2_is_it_unusual"]["label"] == "unusual"
    assert f["q4_what_kind"]["site"]["pattern"] == "ranking_loss"
    assert f["q4_what_kind"]["brand_split"]["pattern"] == "non_brand"
    assert f["q5_when"]["change_point"]["date"] in {"2026-10-05", "2026-10-06", "2026-10-07"}
    names = {m["name"] for m in f["q5_when"]["matches"]}
    assert "Site redesign launched (new blog template)" in names
    top_page = f["q3_where"]["breakdowns"]["gsc_page"]["top_declines"][0]["page"]
    assert top_page.endswith("/blog/sourdough-starter-guide")


def test_narrative_checker_flags_invented_numbers():
    from check_narrative import check
    findings = {"periods": {}, "a": {"clicks": 10434, "change_pct": -38.5}}
    assert check(findings, {"headline": "Clicks fell 38.5% to 10,434 (10.4k)."}) == []
    bad = check(findings, {"headline": "Clicks fell 52% to 9,000."})
    assert {p["number"] for p in bad} == {"52%", "9,000"}


def test_skill_copies_in_sync():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "sync_shared.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ---------------------------------------------------------------- added in v0.1.1
def _series(values, start="2026-01-01"):
    import pandas as pd
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return pd.Series(values, index=[d0 + timedelta(days=i) for i in range(len(values))], dtype=float)


def test_low_volume_zero_days_are_not_tracking_gaps():
    from readout_core.lowdays import low_days
    # A small site: about 4 clicks a day, with ordinary zero-click days.
    s = _series([4, 5, 3, 0, 6, 4, 2, 5, 0, 4, 3, 6, 4, 5, 0, 3, 4, 5, 0, 4, 6, 3, 4, 0, 5, 4, 3, 4] * 2)
    assert low_days(s) == []


def test_real_gap_on_busy_site_is_flagged():
    from readout_core.lowdays import low_days
    vals = [500 + (i % 7) * 10 for i in range(42)]
    vals[35] = 12
    flagged = low_days(_series(vals))
    assert [str(x["date"]) for x in flagged] == ["2026-02-05"]


def test_gsc_zero_clicks_with_normal_impressions_not_flagged():
    from readout_core.lowdays import low_days
    clicks = [80] * 30 + [2] + [80] * 5
    impressions = [1000] * 36           # impressions normal on the low-click day
    assert low_days(_series(clicks), companion=_series(impressions)) == []
    impressions[30] = 20                # both collapse: that is a data gap
    assert len(low_days(_series(clicks), companion=_series(impressions))) == 1


def _write_loose_gsc_export(folder: Path):
    """Shape of a real 2026 Search Console export, unzipped: the daily table is Chart.csv,
    files carry upload prefixes, a query spans two lines, search type is 'Web (text-based)'.
    All values are made up."""
    from datetime import date, timedelta
    folder.mkdir(parents=True)
    rows = ["Date,Clicks,Impressions,CTR,Position"]
    d0 = date(2025, 7, 1)
    for i in range(480):
        c = [4, 6, 3, 5, 2, 0, 1][i % 7]
        imp = [50, 60, 45, 55, 40, 18, 22][i % 7]
        rows.append(f"{d0 + timedelta(days=i)},{c},{imp},{c / imp:.2%},{4.5 + (i % 5) / 2}")
    (folder / "a1b2c3d4-Chart.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (folder / "e5f6a7b8-Queries.csv").write_text(
        'Top queries,Clicks,Impressions,CTR,Position\n'
        'acme widgets,900,4000,22.5%,2.1\n'
        '"which companies make the best widgets in the\ngreat lakes region?",0,1,0%,6\n'
        'widgets près de moi,1,10,10%,7\n', encoding="utf-8")
    (folder / "c9d0e1f2-Filters.csv").write_text("Filter,Value\nSearch type,Web (text-based)\nDate,Last 16 months\n",
                                                 encoding="utf-8")


def test_loose_real_shape_gsc_export(tmp_path):
    folder = tmp_path / "gsc"
    _write_loose_gsc_export(folder)
    ds = load([folder])
    assert ds.systems() == ["gsc"]
    gsc = ds.daily[ds.daily["source_system"] == "gsc"]
    assert gsc["date"].nunique() == 480
    queries = ds.gsc_dims[ds.gsc_dims["dimension"] == "query"]
    assert len(queries) == 3  # the two-line query is one row

    out = tmp_path / "agg"
    r = subprocess.run([sys.executable, str(AGG), str(folder), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    checks = {c["check"] for c in json.loads((out / "aggregate_summary.json").read_text())["health"]}
    assert "gsc_search_type" not in checks   # "Web (text-based)" is web search
    assert "near_zero_days" not in checks    # quiet weekends on a small site are normal


def test_days_from_event():
    from datetime import date
    from readout_core.diagnose import _days_from_event
    s, e = date(2026, 9, 24), date(2026, 10, 8)
    assert _days_from_event(date(2026, 10, 6), s, e) == 0
    assert _days_from_event(date(2026, 10, 11), s, e) == 3
    assert _days_from_event(date(2026, 9, 20), s, e) == -4


@pytest.fixture(scope="session")
def gain_data():
    if not (GAIN / "ga4_daily_channels.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_data_gain.py")], check=True)
    return GAIN


def test_explainer_gain_story(tmp_path, gain_data):
    out = tmp_path / "gain"
    files = sorted(str(p) for p in gain_data.iterdir() if p.name != "events.csv")
    r = subprocess.run([sys.executable, str(EXPLAIN), *files, "--out", str(out),
                        "--events", str(gain_data / "events.csv"), "--brand-terms", "lakeview"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    f = json.loads((out / "findings.json").read_text())
    assert f["q4_what_kind"]["site"]["pattern"] == "ranking_gain"
    gaining = [p["page"] for p in f["q4_what_kind"]["top_gaining_pages"][:3]]
    assert all("water-heater" in p for p in gaining)
    refresh = [m for m in f["q5_when"]["matches"] if m["source"] == "your event log"]
    assert refresh and refresh[0]["relation"] == "follows" and 0 < refresh[0]["days_from_change_point"] <= 14
    assert f["q3_where"]["stopped_ads_campaigns"][0]["campaign"] == "Brand - Search"
    checks = " ".join(c["check"] for c in f["q6_next_checks"])
    assert "before the gain" in checks and "Brand - Search" in checks

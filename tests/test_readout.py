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

SAMPLE = ROOT / "sample-data"
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

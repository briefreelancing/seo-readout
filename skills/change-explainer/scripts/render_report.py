#!/usr/bin/env python3
"""Build the client-ready report (one self-contained HTML file) from
findings.json, the narrative Claude wrote, and the charts.

Tables and charts come straight from findings.json. The narrative is checked
first: every number in it must trace back to findings.json.

Usage:
  python render_report.py --findings readout_explain/findings.json \
      --narrative readout_explain/narrative.json --out readout_explain/report.html
      [--allow-unverified]

Open the HTML in a browser and print to PDF if a PDF is needed.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_narrative import check  # noqa: E402
from readout_core.charts import short_labels  # noqa: E402

METRIC_LABELS = {
    "sessions": "Sessions", "users": "Users", "conversions": "Conversions / key events", "impressions": "Impressions",
    "clicks": "Clicks", "spend": "Spend", "ctr_pct": "CTR (%)", "avg_position": "Average position", "avg_cpc": "Average CPC",
}
PATTERN_LABELS = {
    "ranking_loss": "Ranking loss", "ranking_gain": "Ranking gain", "lower_demand_or_visibility": "Lower demand or visibility",
    "higher_demand_or_visibility": "Higher demand or visibility", "serp_change": "Search results page change",
    "no_material_change": "No material change", "mixed": "Mixed", "unknown": "Unknown",
}
VERDICT_LABELS = {
    "likely_real": "Probably real", "likely_real_single_source": "Probably real (one source)",
    "partly_tracking": "Real, with tracking issues", "likely_tracking": "Mostly tracking",
}
UNUSUAL_LABELS = {"unusual": "Unusual", "somewhat_unusual": "Somewhat unusual", "normal": "Within normal range",
                  "not_enough_history": "Not enough history to judge"}

CSS = """
:root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--wash:#f0efec;--blue:#2a78d6;--red:#d03b3b;--good:#006300}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:48px 28px 64px}
header{border-bottom:1px solid var(--grid);padding-bottom:20px;margin-bottom:28px}
.eyebrow{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
h1{font-size:28px;line-height:1.25;margin:0 0 8px}h2{font-size:20px;margin:40px 0 8px}h3{font-size:15px;margin:20px 0 6px}
.meta{color:var(--ink2);font-size:13px;margin:0}
.headline{font-size:19px;line-height:1.5;background:var(--wash);border-radius:8px;padding:16px 20px;margin:0 0 20px}
p{margin:0 0 12px}ul{margin:0 0 12px;padding-left:22px}
table{width:100%;border-collapse:collapse;margin:12px 0 18px;font-size:13.5px;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--ink2);border-bottom:1px solid var(--ink2);padding:6px 8px}
td{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:top}td.n{text-align:right;white-space:nowrap}th.n{text-align:right}
.neg{color:var(--red)}.pos{color:var(--good)}
.tag{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:1px 10px;background:var(--wash);color:var(--ink)}
.tag.flag{background:#fdeceb;color:#9a1f1f}.tag.pass{background:#e8f4e8;color:#145c14}.tag.high{background:#fdeceb;color:#9a1f1f}.tag.medium{background:#fff4dc;color:#6b4b00}.tag.low{background:var(--wash);color:var(--ink2)}
figure{margin:12px 0 20px}figure img{width:100%;height:auto;border:1px solid var(--grid);border-radius:6px}
figcaption{font-size:12px;color:var(--muted);margin-top:4px}
.note{font-size:13px;color:var(--ink2)}
footer{margin-top:48px;border-top:1px solid var(--grid);padding-top:16px;font-size:12.5px;color:var(--ink2)}
@media print{main{padding:0}h2{break-after:avoid}figure,table{break-inside:avoid}.headline{border:1px solid var(--grid)}}
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def rich(text: str) -> str:
    """Plain text to HTML: paragraphs, '- ' bullet lists and **bold**."""
    if not text:
        return ""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if lines and all(ln.lstrip().startswith(("- ", "* ")) for ln in lines):
            items = "".join(f"<li>{_inline(ln.lstrip()[2:])}</li>" for ln in lines)
            out.append(f"<ul>{items}</ul>")
        else:
            out.append(f"<p>{_inline(' '.join(lines))}</p>")
    return "".join(out)


def _inline(s: str) -> str:
    s = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def num(v, nd=0, pct=False, signed=False):
    if v is None:
        return "n/a"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return esc(v)
    fmt = f"{{:{'+' if signed else ''},.{nd}f}}"
    return fmt.format(f) + ("%" if pct else "")


def delta_cell(v, nd=1, invert=False):
    if v is None:
        return '<td class="n">n/a</td>'
    cls = ("pos" if v > 0 else "neg" if v < 0 else "")
    if invert:
        cls = {"pos": "neg", "neg": "pos"}.get(cls, "")
    return f'<td class="n {cls}">{num(v, nd, pct=True, signed=True)}</td>'


def img(out_dir: Path, findings: dict, chart_id: str, caption: str | None = None) -> str:
    c = next((c for c in findings.get("charts", []) if c["id"] == chart_id), None)
    if not c:
        return ""
    path = out_dir / c["file"]
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode()
    cap = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    return f'<figure><img alt="{esc(c["title"])}" src="data:image/png;base64,{data}">{cap}</figure>'


def table(headers: list[tuple[str, bool]], rows: list[str]) -> str:
    th = "".join(f'<th class="{"n" if n else ""}">{esc(h)}</th>' for h, n in headers)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build(findings: dict, narr: dict, base: Path) -> str:
    sec = narr.get("sections", {})
    per = findings["periods"]
    cur, prev = per["current"], per["previous"]
    focus = findings["focus_metric"]["label"]
    parts = []

    parts.append(f"""<header><p class="eyebrow">{esc(narr.get('eyebrow') or 'Traffic change readout')}</p>
<h1>{esc(narr.get('title') or 'What changed and why')}</h1>
<p class="meta">{esc(narr.get('client') or findings.get('client') or '')}{' · ' if (narr.get('client') or findings.get('client')) else ''}
{esc(cur['start'])} to {esc(cur['end'])} compared with {esc(prev['start'])} to {esc(prev['end'])}
{(' · Prepared by ' + esc(narr['prepared_by'])) if narr.get('prepared_by') else ''}</p></header>""")
    if narr.get("headline"):
        parts.append(f'<p class="headline">{_inline(narr["headline"])}</p>')
    for para in narr.get("summary", []):
        parts.append(rich(para))

    rows = []
    for r in findings.get("headline_numbers", []):
        invert = r["metric"] == "avg_position"
        nd = 2 if r["metric"] in {"spend", "avg_cpc", "ctr_pct"} else 1 if r["metric"] == "avg_position" else 0
        chg = delta_cell(r.get("change_pct")) if r["metric"] != "avg_position" else \
            (f'<td class="n {"neg" if (r.get("change_abs") or 0) > 0 else "pos" if (r.get("change_abs") or 0) < 0 else ""}">'
             f'{num(r.get("change_abs"), 1, signed=True)} pts</td>')
        rows.append(f"<tr><td>{esc(r['system'])}</td><td>{esc(METRIC_LABELS.get(r['metric'], r['metric']))}</td>"
                    f'<td class="n">{num(r["current"], nd)}</td><td class="n">{num(r["previous"], nd)}</td>{chg}'
                    f"{delta_cell(r.get('yoy_pct'), invert=invert)}</tr>")
    parts.append("<h2>Key numbers</h2>")
    parts.append(table([("Source", False), ("Metric", False), ("Current", True), ("Previous", True), ("Change", True), ("vs year ago", True)], rows))

    # 1. Is it real?
    q1 = findings["q1_is_it_real"]
    parts.append("<h2>1. Is the change real?</h2>")
    parts.append(f'<p><span class="tag">{esc(VERDICT_LABELS.get(q1["verdict"], q1["verdict"]))}</span></p>')
    parts.append(rich(sec.get("is_it_real", "")))
    rows = [f'<tr><td><span class="tag {c["status"]}">{"Check" if c["status"] == "flag" else "OK"}</span></td><td>{esc(c["message"])}</td></tr>'
            for c in q1["checks"]]
    if rows:
        parts.append(table([("Result", False), ("What was checked", False)], rows))

    # 2. Unusual?
    q2 = findings["q2_is_it_unusual"]
    parts.append("<h2>2. Is it unusual?</h2>")
    parts.append(f'<p><span class="tag">{esc(UNUSUAL_LABELS.get(q2["label"], q2["label"]))}</span></p>')
    parts.append(rich(sec.get("is_it_unusual", "")))
    rng = q2.get("typical_change_range_pct")
    rows = [f"<tr><td>{esc(focus)}: change vs previous period</td>{delta_cell(q2.get('change_pct'))}</tr>",
            f"<tr><td>Change vs the same weeks last year</td>{delta_cell(q2.get('yoy_pct'))}</tr>",
            f"<tr><td>Last year, over the same two periods</td>{delta_cell(q2.get('last_year_same_periods_change_pct'))}</tr>"]
    if rng:
        rows.append(f'<tr><td>Typical period-to-period change (middle 80% of the last {q2["history_windows"]} comparisons)</td>'
                    f'<td class="n">{num(rng[0], 1, True, True)} to {num(rng[1], 1, True, True)}</td></tr>')
    parts.append(table([("Measure", False), ("Value", True)], rows))

    # 3. Where?
    q3 = findings["q3_where"]
    parts.append("<h2>3. Where is it concentrated?</h2>")
    parts.append(rich(sec.get("where", "")))
    for key, name_key, label, single in [("gsc_page", "page", "Pages", "Page"), ("gsc_query", "query", "Queries", "Query"),
                                         ("ga4_channel", "channel", "GA4 channels", "Channel")]:
        b = q3["breakdowns"].get(key)
        if not b:
            continue
        parts.append(f"<h3>{label}</h3>")
        parts.append(img(base, findings, f"where_{name_key}"))
        metric = "clicks" if key.startswith("gsc") else "sessions"
        rows = []
        top = b["top_declines"][:5]
        shown = short_labels([r[name_key] for r in top]) if name_key == "page" else [r[name_key] for r in top]
        for r, shown_name in zip(top, shown):
            rows.append(f"<tr><td>{esc(shown_name)}</td><td class='n'>{num(r[f'{metric}_previous'])}</td>"
                        f"<td class='n'>{num(r[f'{metric}_current'])}</td>{delta_cell(r.get('change_pct'))}"
                        f"<td class='n'>{num(r.get('share_of_net_change_pct'), 1, True)}</td></tr>")
        if rows:
            parts.append(table([(single, False), ("Previous", True), ("Current", True),
                                ("Change", True), ("Share of net change", True)], rows))
    for u in q3.get("unavailable", []):
        parts.append(f'<p class="note">{esc(u)}</p>')

    # 4. What kind?
    q4 = findings["q4_what_kind"]
    parts.append("<h2>4. What kind of change is it?</h2>")
    site = q4.get("site")
    if site:
        parts.append(f'<p><span class="tag">{esc(PATTERN_LABELS.get(site["pattern"], site["pattern"]))}</span></p>')
    parts.append(rich(sec.get("what_kind", "")))
    if site:
        n = site["numbers"]
        rows = [
            f"<tr><td>Impressions</td><td class='n'>{num(n['impressions_previous'])}</td><td class='n'>{num(n['impressions_current'])}</td>{delta_cell(n['impressions_pct'])}</tr>",
            f"<tr><td>CTR</td><td class='n'>{num(n['ctr_previous_pct'], 2, True)}</td><td class='n'>{num(n['ctr_current_pct'], 2, True)}</td>{delta_cell(n['ctr_change_pct'])}</tr>",
            f"<tr><td>Average position (lower is better)</td><td class='n'>{num(n['position_previous'], 1)}</td><td class='n'>{num(n['position_current'], 1)}</td>"
            f"<td class='n {'neg' if (n['position_change'] or 0) > 0 else 'pos'}'>{num(n['position_change'], 1, signed=True)} pts</td></tr>",
            f"<tr><td>Clicks</td><td class='n'>{num(n['clicks_previous'])}</td><td class='n'>{num(n['clicks_current'])}</td>{delta_cell(n['clicks_pct'])}</tr>",
        ]
        parts.append(table([("Search Console, whole site", False), ("Previous", True), ("Current", True), ("Change", True)], rows))
        split = site.get("click_change_split")
        if split:
            parts.append(f'<p class="note">Of the {num(split["total_change"], signed=True)} change in clicks, about '
                         f'{num(split["from_impressions_change"], signed=True)} comes from fewer or more impressions and '
                         f'{num(split["from_ctr_change"], signed=True)} from a lower or higher click-through rate.</p>')
    bs = q4.get("brand_split", {})
    if "branded" in bs:
        parts.append("<h3>Branded and non-branded searches</h3>")
        parts.append(img(base, findings, "brand_split"))
        rows = [f"<tr><td>{lbl}</td><td class='n'>{num(bs[k]['clicks_previous'])}</td><td class='n'>{num(bs[k]['clicks_current'])}</td>{delta_cell(bs[k]['clicks_pct'])}</tr>"
                for k, lbl in [("branded", "Branded"), ("non_branded", "Non-branded")]]
        parts.append(table([("Queries", False), ("Previous clicks", True), ("Current clicks", True), ("Change", True)], rows))
        parts.append(f'<p class="note">{esc(bs.get("note", ""))} Brand terms: {esc(", ".join(bs.get("brand_terms", [])))}.</p>')

    # 5. When?
    q5 = findings["q5_when"]
    parts.append("<h2>5. When did it start?</h2>")
    parts.append(rich(sec.get("when", "")))
    parts.append(img(base, findings, "trend"))
    cp = q5.get("change_point")
    if cp:
        rows = [f"<tr><td>Trend shifted on</td><td class='n'>{esc(cp['date'])}</td></tr>",
                f"<tr><td>Daily average before</td><td class='n'>{num(cp['before_daily_avg'], 1)}</td></tr>",
                f"<tr><td>Daily average after</td><td class='n'>{num(cp['after_daily_avg'], 1)}</td></tr>",
                f"<tr><td>Shift</td>{delta_cell(cp['shift_pct'])}</tr>",
                f"<tr><td>Strength of the signal</td><td class='n'>{esc(cp['strength'])}</td></tr>"]
        parts.append(table([("Trend shift", False), ("", True)], rows))
    if q5.get("matches"):
        def timing(m):
            if m.get("relation") == "follows":
                return f"Shift began {m['days_from_change_point']} days after"
            return "Coincides with"
        rows = [f"<tr><td>{esc(m['name'])}</td><td>{esc(m['source'])}</td><td class='n'>{esc(m['start'])}"
                f"{(' to ' + esc(m['end'])) if m['end'] != m['start'] else ''}</td><td>{esc(timing(m))}</td></tr>"
                for m in q5["matches"]]
        lag = q5.get("event_lag_days")
        lag_txt = (f" Entries from your event log are also listed if the shift began up to {lag} days after them, "
                   "because site changes often take time to show in search.") if lag else ""
        parts.append(f"<p>The shift lines up in time with these events (within {q5['match_window_days']} days).{lag_txt} "
                     "Timing alone does not show that an event caused the change.</p>")
        parts.append(table([("Event", False), ("From", False), ("Dates", True), ("Timing", False)], rows))
        if q5.get("weak_shift_note"):
            parts.append(f'<p class="note">{esc(q5["weak_shift_note"])}</p>')
    if q5.get("update_list_warning"):
        parts.append(f'<p class="note">{esc(q5["update_list_warning"])}</p>')

    # 6. Next checks
    parts.append("<h2>6. What to check next</h2>")
    parts.append(rich(sec.get("next_checks", "")))
    rows = [f'<tr><td><span class="tag {c["confidence"]}">{esc(c["confidence"]).capitalize()}</span></td><td>{esc(c["check"])}</td><td class="note">{esc(c["why"])}</td></tr>'
            for c in findings.get("q6_next_checks", [])]
    if rows:
        parts.append(table([("Priority", False), ("Check", False), ("Why", False)], rows))

    notes = [c for c in findings.get("data_health", []) if c["status"] == "warning"]
    if notes:
        parts.append("<h2>Data notes</h2><ul>" + "".join(f"<li>{esc(c['message'])}</li>" for c in notes) + "</ul>")

    sources = ", ".join(sorted({s.get("detected_as", "").split(" (")[0] for s in findings.get("sources", [])}))
    parts.append(f"""<footer><p><strong>How this report was made.</strong> Numbers, tables and charts were calculated by
Readout scripts from the exports provided ({esc(sources)}). The written explanation was drafted with AI and checked so that every number
in it matches the calculated results. Event matches show timing only, not cause. Thresholds used to label patterns are rules of thumb.</p>
<p>Generated {esc(findings.get('generated'))}.</p></footer>""")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(narr.get('title') or 'Traffic change readout')}</title><style>{CSS}</style></head><body><main>{''.join(parts)}</main></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-unverified", action="store_true", help="Render even if some narrative numbers can't be traced")
    args = ap.parse_args(argv)
    fpath = Path(args.findings)
    findings = json.loads(fpath.read_text())
    narr = json.loads(Path(args.narrative).read_text())
    problems = check(findings, narr)
    if problems and not args.allow_unverified:
        print(f"Not rendered: {len(problems)} number(s) in the narrative don't match findings.json:")
        for p in problems:
            print(f"- {p['number']} in {p['where']}: ...{p['context']}...")
        return 1
    Path(args.out).write_text(build(findings, narr, fpath.parent), encoding="utf-8")
    print(f"Wrote {args.out}" + (f" ({len(problems)} unverified number(s) allowed)" if problems else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

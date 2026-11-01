#!/usr/bin/env python3
"""Check that every number in the narrative comes from findings.json.

Claude writes the narrative; the scripts produce the numbers. This check makes
that rule enforceable: it pulls each number out of the narrative and looks for
it in findings.json at the precision it was written (so "10.4k" matches 10,434
and "39%" matches -38.5 rounded). Unmatched numbers are reported with context.

Usage:
  python check_narrative.py findings.json narrative.json
Exit code 1 if any number cannot be traced.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}(?:,?\s+\d{{4}})?", re.IGNORECASE),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"\bQ[1-4]\b"),
]
NUM = re.compile(r"(?<![\w.])([-+−]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(k|K|M|%|x)?(?![\w])")
SMALL_INT_OK = 12  # counts like "3 pages" or "top 5" are allowed without a source


PCT_KEY = re.compile(r"pct|percent|share", re.IGNORECASE)


def _walk(obj, key: str, out: dict[str, list[float]]):
    """Collect numbers, split into percent-like ('pct') and everything else ('num')."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        kind = "pct" if PCT_KEY.search(key) else "num"
        out[kind].append(abs(float(obj)))
        if "ratio" in key.lower():
            out["pct"].append(abs(float(obj)) * 100)
    elif isinstance(obj, str):
        for m in re.finditer(r"(-?\d+(?:\.\d+)?)(%?)", obj.replace(",", "")):
            out["pct" if m.group(2) else "num"].append(abs(float(m.group(1))))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(v, str(k), out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, key, out)


def known_values(findings: dict) -> dict[str, list[float]]:
    vals: dict[str, list[float]] = {"pct": [], "num": []}
    _walk({k: v for k, v in findings.items() if k != "thresholds"}, "", vals)
    for p in (findings.get("periods") or {}).values():
        vals["num"].append(float(p.get("days", 0)))
    vals["num"] += [7, 14, 28, 364]
    return vals


def _rounds_to(v: float, target: float, decimals: int, scale: float) -> bool:
    x = v / scale
    half_up = math.floor(x * 10 ** decimals + 0.5) / 10 ** decimals
    return round(x, decimals) == target or abs(half_up - target) < 1e-9


def narrative_text(narr: dict) -> list[tuple[str, str]]:
    parts = []

    def walk(o, key):
        if isinstance(o, str):
            parts.append((key, o))
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{key}.{k}" if key else k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{key}[{i}]")

    walk(narr, "")
    return parts


def check(findings: dict, narr: dict) -> list[dict]:
    known = known_values(findings)
    problems = []
    for where, text in narrative_text(narr):
        clean = text
        for pat in DATE_PATTERNS:
            clean = pat.sub(" ", clean)
        for m in NUM.finditer(clean):
            sign, whole, frac, suffix = m.groups()
            raw = m.group().strip()
            value = float(whole.replace(",", "") + (frac or ""))
            decimals = len(frac) - 1 if frac else 0
            scale = 1000 if suffix in ("k", "K") else 1_000_000 if suffix == "M" else 1
            if scale == 1 and suffix != "%" and decimals == 0 and value <= SMALL_INT_OK:
                continue
            pool = known["pct"] if suffix == "%" else known["num"]
            ok = any(_rounds_to(v, value, decimals, scale) for v in pool)
            if not ok:
                start = max(0, m.start() - 40)
                problems.append({"where": where, "number": raw, "context": clean[start:m.end() + 40].strip()})
    return problems


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 2:
        print(__doc__)
        return 2
    findings = json.loads(Path(argv[0]).read_text())
    narr = json.loads(Path(argv[1]).read_text())
    problems = check(findings, narr)
    if not problems:
        print("All numbers in the narrative trace back to findings.json.")
        return 0
    print(f"{len(problems)} number(s) could not be traced to findings.json:")
    for p in problems:
        print(f"- {p['number']} in {p['where']}: ...{p['context']}...")
    print("Fix the narrative to use numbers from findings.json, or compute the number with a script first.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Copy shared/readout_core into every skill's scripts folder.

Each skill must work on its own when uploaded to Claude, so it carries its own
copy of the core package. Edit shared/readout_core, then run:

    python tools/sync_shared.py          # copy
    python tools/sync_shared.py --check  # fail if any copy is out of date (for CI)
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "shared" / "readout_core"
DOCS = ["exporting-data.md", "channel-grouping.md"]  # copied into each skill's references/


def targets():
    return [p / "scripts" / "readout_core" for p in sorted((ROOT / "skills").iterdir()) if (p / "SKILL.md").exists()]


def in_sync(dst: Path) -> bool:
    if not dst.exists():
        return False
    cmp = filecmp.dircmp(SRC, dst, ignore=["__pycache__"])
    return not (cmp.left_only or cmp.right_only or cmp.diff_files)


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for dst in targets():
        if check:
            refs = dst.parents[1] / "references"
            docs_ok = all((refs / d).exists() and filecmp.cmp(ROOT / "docs" / d, refs / d, shallow=False) for d in DOCS)
            if not in_sync(dst) or not docs_ok:
                stale.append(dst)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__"))
        refs = dst.parents[1] / "references"
        refs.mkdir(exist_ok=True)
        for doc in DOCS:
            shutil.copy2(ROOT / "docs" / doc, refs / doc)
        print(f"synced {dst.relative_to(ROOT)} and references")
    if stale:
        print("Out of date: " + ", ".join(str(s.relative_to(ROOT)) for s in stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

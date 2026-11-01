"""Zip each skill into dist/ for uploading to Claude.

Each zip contains one folder (the skill) with SKILL.md at its root.
Runs the shared-code sync check first so a stale copy is never shipped.

    python tools/package_skills.py
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main() -> int:
    if subprocess.run([sys.executable, str(ROOT / "tools" / "sync_shared.py"), "--check"]).returncode:
        print("Run python tools/sync_shared.py first.")
        return 1
    DIST.mkdir(exist_ok=True)
    for skill in sorted((ROOT / "skills").iterdir()):
        if not (skill / "SKILL.md").exists():
            continue
        name = "readout-" + skill.name
        out = DIST / f"{name}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(skill.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    zf.write(f, Path(name) / f.relative_to(skill))
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

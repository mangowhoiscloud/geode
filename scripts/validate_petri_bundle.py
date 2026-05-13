#!/usr/bin/env python3
"""Validate docs/petri-bundle/ before GitHub Pages deploy.

Enforces:
1. Every listing.json entry has status='success'.
2. Every referenced .eval file exists on disk.
3. No partial run (status='started') or error (status='error') leaks into
   the published bundle — both can trigger viewer TypeError on
   `formatPrettyDecimal(g.metrics[i].value)` when results=None.

Run from repo root:
    python3 scripts/validate_petri_bundle.py

Exit codes:
    0  All listing entries are status=success and files exist.
    1  Validation failed; prints all offending entries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BUNDLE_DIR = Path("docs/petri-bundle")
LISTING = BUNDLE_DIR / "logs" / "listing.json"


def main() -> int:
    if not LISTING.exists():
        print(f"FAIL: {LISTING} missing", file=sys.stderr)
        return 1

    data: dict[str, dict[str, object]] = json.loads(LISTING.read_text())
    failures: list[str] = []

    for name, entry in data.items():
        status = entry.get("status")
        if status != "success":
            failures.append(f"{name}  status={status} (only 'success' is publishable)")
            continue
        file_path = BUNDLE_DIR / "logs" / name
        if not file_path.exists():
            failures.append(f"{name}  status=success but file missing on disk: {file_path}")

    if failures:
        print(f"FAIL: petri-bundle validation — {len(failures)} offending entry/entries:")
        for f in failures:
            print(f"  - {f}")
        print()
        print("Remove offending entries from listing.json and the .eval files from")
        print("docs/petri-bundle/logs/ before deploying. Partial/error archives can")
        print("trigger viewer TypeError on null metric values (inspect_ai #1747 pattern).")
        return 1

    print(f"OK: {len(data)} entries — all status=success, all files present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

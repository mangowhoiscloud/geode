#!/usr/bin/env python3
"""CI ratchet: reject new imports using legacy bridge paths.

Checks only files changed since base-ref (default: origin/develop).
Exits non-zero if any legacy import is found in changed files.
Bridge proxy files themselves are excluded from checking.

Usage:
    python scripts/check_legacy_imports.py
    python scripts/check_legacy_imports.py --base-ref origin/main
"""

from __future__ import annotations

import re
import subprocess
import sys

LEGACY_PATTERNS: list[tuple[str, str]] = [
    (r"from core\.nodes\b", "core.domains.game_ip.nodes"),
    (r"import core\.nodes\b", "core.domains.game_ip.nodes"),
    (r"from core\.fixtures\b", "core.domains.game_ip.fixtures"),
    (r"import core\.fixtures\b", "core.domains.game_ip.fixtures"),
    (r"from core\.ui\b", "core.cli.ui"),
    (r"import core\.ui\b", "core.cli.ui"),
]

# Bridge proxy files are exempt (they ARE the re-export layer)
EXEMPT_FILES = {
    "core/nodes/__init__.py",
    "core/nodes/analysts.py",
    "core/nodes/evaluators.py",
    "core/nodes/router.py",
    "core/nodes/scoring.py",
    "core/nodes/signals.py",
    "core/nodes/synthesizer.py",
    "core/fixtures/__init__.py",
    "core/ui/__init__.py",
    "core/ui/agentic_ui.py",
    "core/ui/console.py",
    "core/ui/mascot.py",
    "core/ui/panels.py",
    "core/ui/status.py",
}


def main() -> int:
    base = "origin/develop"
    if "--base-ref" in sys.argv:
        idx = sys.argv.index("--base-ref")
        if idx + 1 < len(sys.argv):
            base = sys.argv[idx + 1]

    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD"],
        capture_output=True,
        text=True,
    )
    changed = [
        f
        for f in result.stdout.strip().split("\n")
        if f.endswith(".py") and f not in EXEMPT_FILES
    ]

    violations: list[str] = []
    for filepath in changed:
        try:
            content = open(filepath, encoding="utf-8").read()  # noqa: SIM115
        except FileNotFoundError:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            for pattern, replacement in LEGACY_PATTERNS:
                if re.search(pattern, line):
                    violations.append(f"  {filepath}:{i}: use {replacement}")

    if violations:
        print(f"Legacy import violations ({len(violations)}):")
        for v in violations:
            print(v)
        return 1

    print(f"No legacy imports in {len(changed)} changed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

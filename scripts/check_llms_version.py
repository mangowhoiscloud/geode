#!/usr/bin/env python3

"""check_llms_version — committed llms.txt / llms-full.txt version drift guard.

``site/public/llms.txt`` and ``site/public/llms-full.txt`` are committed
build artifacts (the llmstxt.org convention). Their header carries a
``Version vX.Y.Z. Last sync YYYY-MM-DD.`` line. The deploy pipeline
(``pages.yml`` → ``sync-stats`` → ``build`` → ``export-md``) regenerates them
from ``pyproject.toml`` on every deploy, so the *deployed* copies are always
current — but the *committed* snapshots only refresh when someone reruns the
sync and commits. They had drifted 12 versions behind (v0.99.189 committed vs
the current release), so the repo's own SoT lied about which version it
documented (CLAUDE.md "dual SoT without drift invariant" rule).

This guard pins the committed version label to ``pyproject.toml``:

* default — fail (exit 1) if either file's ``Version v…`` token != pyproject
  version, with the one-line remediation.
* ``--fix`` — rewrite the ``Version v…`` token in both files to the pyproject
  version (header token only; the page-list / full-content body refreshes on
  the next deploy build, and ``Last sync`` keeps its last-full-sync date).

Exit codes:

* 0 — both committed headers match pyproject (or ``--fix`` applied cleanly)
* 1 — at least one header drifted from pyproject
* 2 — argparse / IO / parse error

Usage::

    python scripts/check_llms_version.py            # verify (CI gate)
    python scripts/check_llms_version.py --fix       # resync header version
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
LLMS_FILES = (
    REPO_ROOT / "site" / "public" / "llms.txt",
    REPO_ROOT / "site" / "public" / "llms-full.txt",
)

#: matches the ``Version v0.99.201`` token in the header line; the trailing
#: ``.`` / whitespace is left to the surrounding text so only the number moves.
_HEADER_VERSION = re.compile(r"(?m)^(Version v)(\d+\.\d+\.\d+)(\b)")
_PYPROJECT_VERSION = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')


def read_pyproject_version() -> str:
    match = _PYPROJECT_VERSION.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"could not parse version from {PYPROJECT}")
    return match.group(1)


def read_header_version(llms_path: Path) -> str | None:
    """Return the ``Version v…`` token from the file header, or None if absent."""
    match = _HEADER_VERSION.search(llms_path.read_text(encoding="utf-8"))
    return match.group(2) if match else None


def fix_header_version(llms_path: Path, target: str) -> bool:
    """Rewrite the header version token to ``target``. Returns True if changed."""
    original = llms_path.read_text(encoding="utf-8")
    patched, count = _HEADER_VERSION.subn(rf"\g<1>{target}\g<3>", original, count=1)
    if count == 0:
        raise ValueError(f"no 'Version v…' header found in {llms_path}")
    if patched == original:
        return False
    llms_path.write_text(patched, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pin committed llms.txt/llms-full.txt header version to pyproject."
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the header version token to the pyproject version",
    )
    parsed = parser.parse_args(argv)

    try:
        expected = read_pyproject_version()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    drifted: list[tuple[Path, str | None]] = []
    for llms_path in LLMS_FILES:
        if not llms_path.exists():
            print(f"error: {llms_path} not found", file=sys.stderr)
            return 2
        try:
            found = read_header_version(llms_path)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if found != expected:
            drifted.append((llms_path, found))

    if not drifted:
        print(f"llms version: clean (both headers at v{expected})")
        return 0

    if parsed.fix:
        for llms_path, _found in drifted:
            try:
                fix_header_version(llms_path, expected)
            except (OSError, ValueError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(f"fixed {llms_path.relative_to(REPO_ROOT)} -> v{expected}")
        return 0

    for llms_path, found in drifted:
        label = f"v{found}" if found else "(no Version header)"
        print(f"{llms_path.relative_to(REPO_ROOT)}: {label} != pyproject v{expected}")
    print(
        f"\nCommitted llms header drifted from pyproject v{expected}. Resync with:\n"
        "  node site/scripts/sync-stats.mjs   # regenerates llms.txt fully\n"
        "  uv run python scripts/check_llms_version.py --fix   # pins llms-full.txt header\n"
        "(full llms-full.txt body refreshes on the next deploy build — pages.yml).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

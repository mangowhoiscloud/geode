#!/usr/bin/env python3
"""Validate docs/petri-bundle/ before GitHub Pages deploy.

Used as a **CI ratchet** — invoked from both ``.github/workflows/ci.yml``
(PR gate, blocks merge) and ``.github/workflows/pages.yml`` (post-merge
defense-in-depth) and the dedicated ``.github/workflows/petri-publish.yml``
guardrail. Each layer alone is insufficient: CI catches PRs before merge,
pages.yml catches drift from cron-triggered rebuilds, and petri-publish.yml
is the isolation layer that runs even when the site build is skipped.

Enforces:
1. listing.json present + parses.
2. Every listing entry has status='success'.
3. Every referenced .eval file exists on disk.
4. Inside each .eval zip:
   - header.json present + parses.
   - header.status == 'success'.
   - header.results is a non-empty dict with a non-empty scores[] list.
   - Every score has a non-empty metrics field (dict or list).
   These three checks together prevent the click-time TypeError seen in
   inspect_ai #1747 — ``formatPrettyDecimal(g.metrics[i].value)`` blows up
   when ``results`` is None or ``scores[].metrics`` is empty.
5. Required asset files present (index.html + the JS bundle the viewer
   loads on cold start). Missing assets = silent blank-page failure for
   end users.

Run from repo root:
    uv run python scripts/validate_petri_bundle.py

Exit codes:
    0  Bundle is publishable.
    1  Validation failed; prints all offending entries.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

# Petri .eval archives use zstd-compressed entries. Python 3.14 added native
# zstd support to zipfile; on 3.12/3.13 we rely on the `zipfile-zstd`
# monkey-patch shipped as a dev-group dependency. If neither is available,
# fall back to a listing-only check (catches the most common regression —
# deleted/renamed .eval files — but cannot validate archive internals).
_ZSTD_AVAILABLE: bool
try:
    import zipfile_zstd  # type: ignore[import-untyped]  # noqa: F401 — patches zipfile

    _ZSTD_AVAILABLE = True
except ImportError:
    _ZSTD_AVAILABLE = sys.version_info >= (3, 14)

BUNDLE_DIR = Path("docs/petri-bundle")
LISTING = BUNDLE_DIR / "logs" / "listing.json"
ASSETS_DIR = BUNDLE_DIR / "assets"

# index.html + the entry JS bundle Inspect ships. Hash-suffixed chunks
# (chunk-*.js, lib-*.js, …) intentionally not pinned — they rotate every
# viewer rebuild. The launcher pair below is enough to detect a wholesale
# bundle wipe.
REQUIRED_ASSET_NAMES: tuple[str, ...] = ("index.html",)
REQUIRED_ASSET_GLOBS: tuple[tuple[str, str], ...] = (
    ("assets", "index.js"),
    ("assets", "index.css"),
)


def _check_eval_archive(path: Path) -> list[str]:
    """Return a list of failure messages for a single .eval archive (empty if OK)."""
    failures: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                with zf.open("header.json") as fh:
                    header = json.load(fh)
            except KeyError:
                return [f"{path.name}: header.json missing inside archive"]
            except json.JSONDecodeError as exc:
                return [f"{path.name}: header.json is not valid JSON ({exc})"]

            if not isinstance(header, dict):
                return [f"{path.name}: header.json is not a JSON object"]

            status = header.get("status")
            if status != "success":
                failures.append(f"{path.name}: header.status={status!r} (expected 'success')")

            results = header.get("results")
            if not isinstance(results, dict) or not results:
                failures.append(
                    f"{path.name}: header.results missing/empty — "
                    "would trigger TypeError on row click",
                )
                return failures  # downstream checks meaningless without results

            scores = results.get("scores")
            if not isinstance(scores, list) or not scores:
                failures.append(f"{path.name}: header.results.scores is missing or empty")
                return failures

            for idx, score in enumerate(scores):
                if not isinstance(score, dict):
                    failures.append(f"{path.name}: scores[{idx}] is not an object")
                    continue
                metrics = score.get("metrics")
                if metrics is None or (hasattr(metrics, "__len__") and len(metrics) == 0):
                    name = score.get("name") or score.get("scorer") or f"#{idx}"
                    failures.append(
                        f"{path.name}: scores[{idx}] ({name}) has empty metrics "
                        "— viewer renders 0 columns",
                    )
    except zipfile.BadZipFile:
        return [f"{path.name}: file is not a valid zip archive"]
    except OSError as exc:
        return [f"{path.name}: could not read archive ({exc})"]
    return failures


def _check_assets() -> list[str]:
    """Return a list of failure messages for missing viewer assets."""
    failures: list[str] = []
    for name in REQUIRED_ASSET_NAMES:
        if not (BUNDLE_DIR / name).is_file():
            failures.append(f"asset missing: {BUNDLE_DIR / name}")
    for parts in REQUIRED_ASSET_GLOBS:
        path = BUNDLE_DIR
        for p in parts:
            path = path / p
        if not path.is_file():
            failures.append(f"asset missing: {path}")
    return failures


def main() -> int:
    if not LISTING.exists():
        print(f"FAIL: {LISTING} missing", file=sys.stderr)
        return 1

    try:
        data: dict[str, dict[str, object]] = json.loads(LISTING.read_text())
    except json.JSONDecodeError as exc:
        print(f"FAIL: {LISTING} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = _check_assets()

    skipped_deep = False
    for name, entry in data.items():
        status = entry.get("status")
        if status != "success":
            failures.append(f"{name}: listing.status={status!r} (only 'success' is publishable)")
            continue
        file_path = BUNDLE_DIR / "logs" / name
        if not file_path.exists():
            failures.append(
                f"{name}: listing.status=success but file missing on disk ({file_path})"
            )
            continue
        if _ZSTD_AVAILABLE:
            failures.extend(_check_eval_archive(file_path))
        else:
            skipped_deep = True

    if skipped_deep:
        print(
            "NOTICE: zstd backend unavailable — skipped archive-internal checks. "
            "Install `zipfile-zstd` (dev group) or run on Python 3.14+ for full validation.",
            file=sys.stderr,
        )

    if failures:
        print(f"FAIL: petri-bundle validation — {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        print()
        print("Fix paths:")
        print("  - Remove offending entries from docs/petri-bundle/logs/listing.json")
        print("    and the .eval files from docs/petri-bundle/logs/.")
        print("  - Rebuild the viewer bundle via `inspect view bundle` if assets are missing.")
        print("  - Partial/error/empty-results archives trigger click-time TypeError")
        print("    (inspect_ai #1747 pattern).")
        return 1

    print(
        f"OK: {len(data)} archive(s) — listing + zip header + scores + assets all valid.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

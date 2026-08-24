"""Slop prevention audit — 6-lens scan of production packages + scripts.

Surfaces patterns that accumulate during long PR sequences and rot
codebase health if uncaught:

1. **Unused imports** (`ruff F401`) — module-level imports never
   referenced.
2. **Dead functions** (heuristic: private defs without another textual
   reference in the same file).
3. **Duplicate patterns** (≥3 inline copies of the same N-line
   snippet) — usually a missed lift-to-helper opportunity.
4. **Abandoned TODOs** (`TODO` / `FIXME` / `XXX` without an owner
   handle or date stamp).
5. **Lint bypass markers** (`# noqa` / `# type: ignore`) — candidates for
   review.
6. **Stale references** (renamed module / removed feature names that
   still appear in comments or docstrings).

Usage:

    uv run python scripts/slop_audit.py

This script is diagnostic: its heuristic counts are candidates for review, not
an accepted-debt floor. The dated 2026-05-18 snapshot lives under
``docs/reference/`` as historical evidence. Promotion remains owned by
behavioral tests, coverage, and deterministic lint/type/dependency gates.

Pure-script; no test dependencies — runs from a fresh checkout via
``uv run``. The skill at ``.geode/skills/slop-audit/SKILL.md`` documents
how to interpret the output and what to do when each lens fires.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("core/", "evals/", "evolve/", "scripts/")


@dataclass
class LensResult:
    """One audit lens' findings."""

    name: str
    count: int
    samples: list[str]
    severity: str  # "info" | "warning" | "error"


# ---------------------------------------------------------------------------
# Lens 1 — Unused imports
# ---------------------------------------------------------------------------


def lens_unused_imports() -> LensResult:
    """Count F401 violations across the scan roots.

    F401 fires on imports that are never used. We do NOT include
    F811 (re-imports) or F841 (unused vars) — those are noise for
    this audit.
    """
    cmd = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        "F401",
        "--output-format",
        "json",
        *SCAN_ROOTS,
    ]
    proc = subprocess.run(  # noqa: S603  # nosec B603 — argv from module constants
        cmd, capture_output=True, text=True, check=False
    )
    if proc.returncode not in (0, 1):
        detail = (proc.stderr or proc.stdout).strip()[:500]
        raise RuntimeError(f"ruff F401 scan failed with exit {proc.returncode}: {detail}")
    if not proc.stdout.strip():
        if proc.returncode == 0:
            findings = []
        else:
            raise RuntimeError("ruff F401 scan reported findings without JSON output")
    else:
        try:
            findings = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ruff F401 scan returned invalid JSON") from exc
        if not isinstance(findings, list):
            raise RuntimeError("ruff F401 scan returned a non-list JSON payload")
    samples = [
        f"{Path(f['filename']).relative_to(REPO_ROOT)}:{f['location']['row']} {f['code']}"
        for f in findings[:5]
    ]
    return LensResult(
        name="unused_imports",
        count=len(findings),
        samples=samples,
        severity="warning" if findings else "info",
    )


# ---------------------------------------------------------------------------
# Lens 2 — Dead functions (heuristic)
# ---------------------------------------------------------------------------


_DEF_PATTERN = re.compile(r"^\s*def\s+(_[a-zA-Z0-9_]+)\s*\(", re.MULTILINE)


def lens_dead_private_functions() -> LensResult:
    """Detect ``def _foo(...)`` (private) with zero external callers.

    Walks every .py file, collects private def names per file, then
    greps the same file for ``_foo`` references outside the def line.
    Lightweight: misses cross-module callers but those are rare for
    private helpers.
    """
    samples: list[str] = []
    count = 0
    for py in _iter_py_files():
        text = py.read_text(encoding="utf-8", errors="ignore")
        for match in _DEF_PATTERN.finditer(text):
            name = match.group(1)
            # Skip dunders (__init__, __repr__, etc.)
            if name.startswith("__") and name.endswith("__"):
                continue
            # Skip _make / _build common fixtures
            references = text.count(name)
            # references includes the definition itself; want > 1 for usage
            if references <= 1:
                count += 1
                if len(samples) < 5:
                    samples.append(f"{py.relative_to(REPO_ROOT)} :: {name}")
    return LensResult(
        name="dead_private_functions",
        count=count,
        samples=samples,
        severity="warning" if count > 10 else "info",
    )


# ---------------------------------------------------------------------------
# Lens 3 — Duplicate patterns (3+ inline copies)
# ---------------------------------------------------------------------------


_SIGNATURE_PATTERN = re.compile(r"^\s*def\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)


def lens_duplicate_signatures() -> LensResult:
    """Detect ``def <same_name>`` repeated ≥3 times across files.

    Repeated names are a weak signal — could be legitimate (init,
    execute) or a missed shared-helper opportunity. We exclude
    common Python dunders + framework method names (execute, run,
    setUp, tearDown, __init__).
    """
    skip = frozenset({"execute", "run", "setUp", "tearDown", "delegate", "test_"})
    counts: dict[str, list[str]] = {}
    for py in _iter_py_files():
        text = py.read_text(encoding="utf-8", errors="ignore")
        for match in _SIGNATURE_PATTERN.finditer(text):
            name = match.group(1)
            if name.startswith("__") and name.endswith("__"):
                continue
            if name in skip or name.startswith("test_"):
                continue
            counts.setdefault(name, []).append(str(py.relative_to(REPO_ROOT)))
    duplicates = {n: files for n, files in counts.items() if len(files) >= 3}
    samples = [
        f"{name} ({len(files)} copies): {files[0]}" for name, files in list(duplicates.items())[:5]
    ]
    return LensResult(
        name="duplicate_signatures",
        count=len(duplicates),
        samples=samples,
        severity="info",
    )


# ---------------------------------------------------------------------------
# Lens 4 — Abandoned TODOs
# ---------------------------------------------------------------------------


_TODO_PATTERN = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b(?:\(([^)]+)\))?(.*)", re.IGNORECASE)


def lens_abandoned_todos() -> LensResult:
    """TODO without an owner ``(name)`` or date stamp."""
    samples: list[str] = []
    count = 0
    for py in _iter_py_files():
        for lineno, line in enumerate(
            py.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            match = _TODO_PATTERN.search(line)
            if not match:
                continue
            owner = match.group(2)
            tail = match.group(3) or ""
            has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", tail))
            if not owner and not has_date:
                count += 1
                if len(samples) < 5:
                    samples.append(f"{py.relative_to(REPO_ROOT)}:{lineno}")
    return LensResult(
        name="abandoned_todos",
        count=count,
        samples=samples,
        severity="warning" if count > 5 else "info",
    )


# ---------------------------------------------------------------------------
# Lens 5 — Lint bypass markers
# ---------------------------------------------------------------------------


def lens_lint_bypass() -> LensResult:
    """Count ``# noqa`` and ``# type: ignore`` markers.

    Reported as a single combined diagnostic count. Additions are reviewed in
    the diff; this aggregate is not a promotion gate.
    """
    samples: list[str] = []
    count = 0
    for py in _iter_py_files():
        for lineno, line in enumerate(
            py.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if "# noqa" in line or "# type: ignore" in line:
                count += 1
                if len(samples) < 5:
                    samples.append(f"{py.relative_to(REPO_ROOT)}:{lineno}")
    return LensResult(
        name="lint_bypass_markers",
        count=count,
        samples=samples,
        severity="info",
    )


# ---------------------------------------------------------------------------
# Lens 6 — Stale references
# ---------------------------------------------------------------------------


_STALE_REFS: tuple[str, ...] = (
    # Pre-PR-0 / PR-1 cleanups — keep this list current as features
    # are removed so a re-appearance in docs is flagged.
    "BudgetGuard",
    "SUBAGENT_BUDGET_WARNING",
    "seeds_safe10",
    "FitnessBaseline",
    "plugins.benchmark_harness",
    "plugins.crucible",
    "plugins.petri_audit",
    "plugins.seed_generation",
    "core.self_improving",
    "geode_product",
)


def lens_stale_references() -> LensResult:
    """Flag any of :data:`_STALE_REFS` that show up in production code.

    Comments / CHANGELOG references to *historical* changes are
    allowed — we look at ``core/`` / ``evals/`` / ``evolve/`` / ``scripts/``
    source only, NOT ``docs/`` or ``CHANGELOG.md``. The CHANGELOG is
    the canonical home for "we removed X" prose.

    The slop_audit.py script itself is excluded — it literally defines
    ``_STALE_REFS`` so a self-match is a false positive. Historical
    references in docstrings ("pre-PR-1 BudgetGuard layer was removed",
    "no FitnessBaseline wrapping") are intentional change-log context;
    they're allowed via the ``# slop:keep`` line marker on the same
    line as the reference.
    """
    samples: list[str] = []
    count = 0
    for py in _iter_py_files():
        # The audit script itself defines the list — never count its
        # own occurrences.
        if py.name == "slop_audit.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Allow explicit historical references via inline marker.
            if "# slop:keep" in line:
                continue
            for ref in _STALE_REFS:
                if ref in line:
                    count += 1
                    if len(samples) < 5:
                        samples.append(f"{py.relative_to(REPO_ROOT)}:{lineno} :: {ref}")
    return LensResult(
        name="stale_references",
        count=count,
        samples=samples,
        severity="error" if count > 0 else "info",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _iter_py_files() -> list[Path]:
    """Walk ``SCAN_ROOTS`` for ``.py`` files (excludes ``__pycache__``)."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for py in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            files.append(py)
    return files


def run_all_lenses() -> list[LensResult]:
    """Invoke every lens in order. Order matches the SKILL.md doc."""
    return [
        lens_unused_imports(),
        lens_dead_private_functions(),
        lens_duplicate_signatures(),
        lens_abandoned_todos(),
        lens_lint_bypass(),
        lens_stale_references(),
    ]


def format_report(results: list[LensResult], *, header: str = "") -> str:
    """Render a markdown report for the audit run."""
    lines: list[str] = []
    if header:
        lines.append(f"# {header}")
        lines.append("")
    lines.append("| Lens | Count | Severity |")
    lines.append("|------|------:|----------|")
    for r in results:
        lines.append(f"| {r.name} | {r.count} | {r.severity} |")
    lines.append("")
    lines.append("## Samples (first 5 per lens)")
    for r in results:
        lines.append(f"### {r.name}")
        if r.samples:
            for s in r.samples:
                lines.append(f"- `{s}`")
        else:
            lines.append("- _(none)_")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    argparse.ArgumentParser(description="Run the diagnostic six-lens slop audit.").parse_args()
    results = run_all_lenses()
    report = format_report(results, header="GEODE slop audit — diagnostic run")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

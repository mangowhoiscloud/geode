#!/usr/bin/env python3

"""check_slop_ratchet — slop *growth* ratchet (existing debt tolerated, new debt blocked).

Companion to ``check_repo_hygiene.py`` (same CI step, same report/exit-code
shape) and to the committed-baseline pattern of ``check_llms_version.py``.
Unlike ``scripts/slop_audit.py`` — the *manual* 6-lens deep-audit tool with a
markdown baseline under ``docs/audits/`` that is not wired into CI — this
script is a narrow promotion gate: it measures four slop metrics, compares
each against the committed ``scripts/slop_ratchet_baseline.json``, and fails
only when a metric GROWS (Karpathy P4 Ratchet). Absolute counts never fail.

Metrics (tracked ``*.py`` files only, via ``git grep -nIE`` — same
tracked-files convention as ``check_repo_hygiene.find_home_path_leaks``):

* ``bypass_markers`` — ``# noqa`` / ``# type: ignore`` / ``# pragma: no cover``
  / ``# ruff: noqa`` lines in ``core/`` + ``plugins/`` + ``scripts/``.
  ``tests/`` is deliberately NOT scanned: test-file noqa is common, low-risk
  (fixture literals, intentional bad inputs) and already carries broad
  per-file-ignores in pyproject — gating it would drown the signal.
* ``stale_todos`` — ``TODO`` / ``FIXME`` / ``XXX`` comment markers in
  ``core/`` + ``plugins/`` + ``scripts/`` (uppercase only; lowercase prose is
  not a work marker).
* ``dead_flags`` — ``if False:`` / ``if 0:`` branches and ``pass  # stub``
  placeholders in ``core/`` + ``plugins/``. NOTE: the design also named bare
  ``raise NotImplementedError`` placeholders, but "count only when the
  enclosing function has no ``@abstractmethod`` decorator" is not decidable
  from line-oriented grep output, so the metric is narrowed to the three
  grep-decidable patterns above (documented narrowing, not an omission).
* ``duplicated_signatures`` — exact duplicate ``def name(args...)`` signature
  lines (whitespace-normalized) appearing in 2+ DIFFERENT modules under
  ``core/``. Dunder methods, ``__init__.py`` modules, and test files are
  excluded. Multi-line signatures compare on their first line only — this is
  a heuristic; the report lists the file groups so a human can judge.

What this gate does NOT count: anything ruff already blocks at zero.
F401 unused imports are gated by the ``F`` family in pyproject's ruff
``select``; ERA (commented-out code) and T20 (print) are NOT selected, but
those are style-lint decisions, not ratchet material. Re-counting a
ruff-gated-at-zero rule here would be dead weight.

Self-exclusion: ``scripts/check_slop_ratchet.py`` and ``scripts/slop_audit.py``
are excluded from the marker scans because both necessarily embed the marker
literals they scan for (pattern strings, docstring examples) — every other
file in scope is scanned.

Baseline: ``scripts/slop_ratchet_baseline.json`` maps
``{metric: {"count": N, "stamped": "<pyproject version>"}}``. Growth requires
editing the committed baseline (``--update-baseline``), which is visible in
the PR diff — that visibility IS the approval step. Shrink passes and prints
a paydown hint so the floor can be ratcheted down in the same PR.

Exit codes:

* 0 — every metric at or below its baseline (or ``--update-baseline`` applied)
* 1 — at least one metric grew past its baseline
* 2 — missing/invalid baseline, missing git, or parse error

Usage::

    python scripts/check_slop_ratchet.py                    # verify (CI gate)
    python scripts/check_slop_ratchet.py --update-baseline  # re-stamp baseline
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
BASELINE_FILE = REPO_ROOT / "scripts" / "slop_ratchet_baseline.json"

#: On growth the report lists the current hits for the grown metric, capped
#: here so a large legacy metric cannot flood the CI log. The cap is noted in
#: the report when it truncates.
MAX_LISTED_HITS = 20

#: Audit tooling whose *source* embeds the marker literals being scanned
#: (regex strings, docstring examples). Excluded from every scan; see module
#: docstring. ``:!`` is git's exclude-pathspec magic.
_SELF_EXCLUDES: tuple[str, ...] = (
    ":!scripts/check_slop_ratchet.py",
    ":!scripts/slop_audit.py",
)

_PYPROJECT_VERSION = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')

#: Extracts the function name from a whitespace-normalized ``def`` line.
_DEF_NAME = re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class GrepMetric:
    """One git-grep-backed slop metric: a pattern and the roots it scans."""

    name: str
    pattern: str
    pathspecs: tuple[str, ...]


#: ``[[:space:]]`` (not ``\s``/``\b``) keeps the patterns POSIX-ERE portable
#: across git's regex backends (macOS Apple git vs ubuntu CI git).
GREP_METRICS: tuple[GrepMetric, ...] = (
    GrepMetric(
        name="bypass_markers",
        pattern=(
            "#[[:space:]]*(noqa|type:[[:space:]]*ignore"
            "|pragma:[[:space:]]*no cover|ruff:[[:space:]]*noqa)"
        ),
        pathspecs=("core/*.py", "plugins/*.py", "scripts/*.py"),
    ),
    GrepMetric(
        name="stale_todos",
        pattern="#.*(TODO|FIXME|XXX)",
        pathspecs=("core/*.py", "plugins/*.py", "scripts/*.py"),
    ),
    GrepMetric(
        name="dead_flags",
        pattern="(^[[:space:]]*if (False|0):|pass[[:space:]]+#[[:space:]]*stub)",
        pathspecs=("core/*.py", "plugins/*.py"),
    ),
)

#: All metric names in report order (grep metrics + the signature heuristic).
METRIC_NAMES: tuple[str, ...] = (*(m.name for m in GREP_METRICS), "duplicated_signatures")


def _git_grep(root: Path, pattern: str, pathspecs: tuple[str, ...]) -> list[tuple[str, int, str]]:
    """Return (relpath, lineno, content) for each tracked-file line matching
    ``pattern`` under ``pathspecs``. Exit code 1 (no matches) is a clean empty
    result; any other failure aborts with exit 2 (a broken scanner must never
    pass as "zero slop")."""
    git = shutil.which("git")
    if git is None:
        raise SystemExit(2)
    proc = subprocess.run(  # noqa: S603 — resolved git path, fixed argv, constant patterns
        [git, "grep", "-nIE", pattern, "--", *pathspecs, *_SELF_EXCLUDES],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        print(f"slop ratchet: git grep failed (exit {proc.returncode}):", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(2)
    matches: list[tuple[str, int, str]] = []
    for raw in proc.stdout.splitlines():
        relpath, _, rest = raw.partition(":")
        lineno_s, _, content = rest.partition(":")
        if lineno_s.isdigit():
            matches.append((relpath, int(lineno_s), content))
    return matches


def measure_grep_metric(root: Path, metric: GrepMetric) -> list[str]:
    """Return one formatted hit string per matching line."""
    return [
        f"{relpath}:{lineno}: {content.strip()}"
        for relpath, lineno, content in _git_grep(root, metric.pattern, metric.pathspecs)
    ]


def _is_test_module(relpath: str) -> bool:
    """True for test files that should not feed the signature heuristic."""
    basename = Path(relpath).name
    return (
        basename.startswith("test_") or basename.endswith("_test.py") or basename == "conftest.py"
    )


def duplicate_signature_groups(def_lines: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Group whitespace-normalized ``def`` lines shared by 2+ DIFFERENT modules.

    ``def_lines`` is (relpath, raw def line). Dunder methods, ``__init__.py``
    modules, and test files are skipped. Returns {normalized signature:
    sorted module list} for each duplicated group. Pure function so tests can
    feed fixture tuples without a git checkout.
    """
    modules_by_sig: dict[str, set[str]] = {}
    for relpath, raw_line in def_lines:
        if Path(relpath).name == "__init__.py" or _is_test_module(relpath):
            continue
        signature = " ".join(raw_line.split())
        name_match = _DEF_NAME.match(signature)
        if name_match is None:
            continue
        def_name = name_match.group(1)
        if def_name.startswith("__") and def_name.endswith("__"):
            continue
        modules_by_sig.setdefault(signature, set()).add(relpath)
    return {
        signature: sorted(modules)
        for signature, modules in modules_by_sig.items()
        if len(modules) >= 2
    }


def measure_duplicated_signatures(root: Path) -> list[str]:
    """Return one formatted hit string per duplicated signature group in core/."""
    def_lines = [
        (relpath, content)
        for relpath, _lineno, content in _git_grep(
            root, "^[[:space:]]*def [a-zA-Z_]", ("core/*.py",)
        )
    ]
    groups = duplicate_signature_groups(def_lines)
    return [f"{signature}  [{', '.join(modules)}]" for signature, modules in sorted(groups.items())]


def measure_all(root: Path) -> dict[str, list[str]]:
    """Measure every metric; returns {metric name: formatted hit list}."""
    hits = {metric.name: measure_grep_metric(root, metric) for metric in GREP_METRICS}
    hits["duplicated_signatures"] = measure_duplicated_signatures(root)
    return hits


def read_pyproject_version(pyproject: Path) -> str:
    """Return the pyproject version, or abort with exit 2 when unreadable."""
    try:
        matched = _PYPROJECT_VERSION.search(pyproject.read_text(encoding="utf-8"))
    except OSError as err:
        print(f"slop ratchet: cannot read {pyproject}: {err}", file=sys.stderr)
        raise SystemExit(2) from err
    if matched is None:
        print(f"slop ratchet: no version line in {pyproject}", file=sys.stderr)
        raise SystemExit(2)
    return matched.group(1)


def load_baseline(baseline_file: Path) -> dict[str, int]:
    """Return {metric: baseline count}; abort with an instructive exit 2 when
    the baseline is missing, unparseable, or lacks a measured metric."""
    remedy = (
        "    hint: generate it from the current tree with\n"
        "          uv run python scripts/check_slop_ratchet.py --update-baseline\n"
        "          and commit scripts/slop_ratchet_baseline.json."
    )
    if not baseline_file.is_file():
        print(f"slop ratchet: baseline missing at {baseline_file}", file=sys.stderr)
        print(remedy, file=sys.stderr)
        raise SystemExit(2)
    try:
        entries = json.loads(baseline_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"slop ratchet: baseline unreadable at {baseline_file}: {err}", file=sys.stderr)
        print(remedy, file=sys.stderr)
        raise SystemExit(2) from err
    counts: dict[str, int] = {}
    for name in METRIC_NAMES:
        entry = entries.get(name) if isinstance(entries, dict) else None
        count = entry.get("count") if isinstance(entry, dict) else None
        if not isinstance(count, int):
            print(
                f"slop ratchet: baseline entry for '{name}' missing or malformed "
                f"in {baseline_file}",
                file=sys.stderr,
            )
            print(remedy, file=sys.stderr)
            raise SystemExit(2)
        counts[name] = count
    return counts


def write_baseline(baseline_file: Path, counts: dict[str, int], version: str) -> None:
    """Rewrite the committed baseline from the given counts."""
    entries = {name: {"count": counts[name], "stamped": version} for name in METRIC_NAMES}
    baseline_file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def format_growth_report(
    growths: list[tuple[str, int, int, list[str]]],
) -> str:
    """Hygiene-checker-style report for grown metrics.

    ``growths`` is (metric, baseline, current, current hits). Lists the
    current hits for each grown metric capped at :data:`MAX_LISTED_HITS`
    (noted when truncating).
    """
    lines = [f"Slop ratchet: {len(growths)} metric(s) grew", ""]
    for name, baseline_count, current_count, hits in growths:
        delta = current_count - baseline_count
        lines.append(f"[{name}] baseline {baseline_count} -> current {current_count} (+{delta})")
        for hit in hits[:MAX_LISTED_HITS]:
            lines.append(f"  {hit}")
        if len(hits) > MAX_LISTED_HITS:
            lines.append(
                f"  ... ({len(hits)} current hits total; listing capped at {MAX_LISTED_HITS})"
            )
        lines.append(
            "    hint: new slop blocks promotion — fix the underlying issue, or for "
            "deliberate reviewed growth run --update-baseline and commit the JSON "
            "diff (the visible diff is the approval)."
        )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Slop growth ratchet (see module docstring).")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite scripts/slop_ratchet_baseline.json from the current tree",
    )
    args = parser.parse_args(argv)

    current_hits = measure_all(REPO_ROOT)
    current_counts = {name: len(hits) for name, hits in current_hits.items()}

    if args.update_baseline:
        version = read_pyproject_version(PYPROJECT)
        write_baseline(BASELINE_FILE, current_counts, version)
        stamped = ", ".join(f"{name} {current_counts[name]}" for name in METRIC_NAMES)
        print(f"slop ratchet: baseline updated ({stamped}) stamped {version}")
        return 0

    baseline_counts = load_baseline(BASELINE_FILE)
    growths = [
        (name, baseline_counts[name], current_counts[name], current_hits[name])
        for name in METRIC_NAMES
        if current_counts[name] > baseline_counts[name]
    ]
    if growths:
        print(format_growth_report(growths), file=sys.stderr)
        return 1

    summary = ", ".join(
        f"{name} {current_counts[name]}/{baseline_counts[name]}" for name in METRIC_NAMES
    )
    print(f"slop ratchet OK: {summary}")
    shrunk = [name for name in METRIC_NAMES if current_counts[name] < baseline_counts[name]]
    if shrunk:
        print(
            f"slop ratchet: {', '.join(shrunk)} shrank below baseline — lock in the "
            "paydown via --update-baseline in this PR."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

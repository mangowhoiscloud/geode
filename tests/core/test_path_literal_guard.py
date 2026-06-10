"""P4 — lint guardrail for paths.py SoT.

After PR #1102 (P1 vestigial), PR #1104 (P3 missing constants), and
PR #1106 (P2 alignment), every module in ``core/`` resolves ``.geode``
paths through ``core.paths`` constants. This test fails when a new
hardcoded ``Path.home() / ".geode"`` or ``Path(".geode/...")`` literal
appears outside the allowlist — preventing regression of the
sloppiness we just spent three PRs cleaning up.

The guard is a test (not a ``ruff`` custom rule or shell script) so
it runs in the same gate as everything else and reports violations
with file paths the developer can jump to in their editor.

Mirrors ``tests/integration/test_no_daemon_print.py``'s pattern — file allowlist
+ per-line ``# paths-literal-ok`` opt-out + regex scan, no AST overhead.
"""

from __future__ import annotations

import re
from pathlib import Path

# File-level allowlist — these files are *expected* to mention ``.geode``
# literals because they ARE the source of truth, legacy markers, or
# bootstrap-only project scaffolding that constructs many one-off dirs.
_FILE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # The single source of truth — every other module reads from here.
        "core/paths.py",
        # Legacy migration detection markers (S4 from PR #1098 audit).
        "core/scheduler/models.py",  # _LEGACY_STORE_PATH
        "core/auth/oauth_login.py",  # LEGACY_AUTH_STORE_PATH
        # Project init bootstrap — `geode init` creates the full `.geode/`
        # tree on first run. Some of these subdirs (journal/transcripts,
        # vault/profile, etc.) have no SoT constants because nothing else
        # reads them at module level. Promoting them to constants would
        # only add 20+ entries to paths.py for one-shot mkdir calls.
        "core/cli/typer_init.py",
    }
)

# Patterns that indicate a hardcoded ``.geode`` literal. Caught by
# substring + regex — no AST needed because the literal forms are
# narrow.
_LITERAL_PATTERNS: list[re.Pattern[str]] = [
    # `Path.home() / ".geode"` (with or without subsequent path parts)
    re.compile(r'Path\.home\(\)\s*/\s*"\.geode"'),
    # `Path(".geode/...")` — relative project-local literal
    re.compile(r'Path\(\s*"\.geode/'),
    re.compile(r"Path\(\s*'\.geode/"),
    # `Path(".geode")` exact (no trailing slash) — used as relative root
    re.compile(r'Path\(\s*"\.geode"\s*\)'),
    re.compile(r"Path\(\s*'\.geode'\s*\)"),
]

# Per-line opt-out annotation. Avoid Ruff's suppression-comment spelling so
# this project-specific marker is not parsed as a lint directive.
_NOQA_RE = re.compile(r"#\s*paths-literal-ok\b")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_ROOT = _REPO_ROOT / "core"


def _strip_inline_comment(line: str) -> str:
    """Return the code portion of *line* with any trailing ``# comment``
    removed. We strip naively at the first ``#`` outside a string — which
    is good enough because every legitimate occurrence of the patterns we
    look for happens in code, not inside a string literal. Lines that
    quote a path literal *inside* a string (e.g. doctest, comment) are
    deliberately not matched."""
    # Find the first '#' that isn't enclosed in matching quotes. A
    # full-fidelity parser would use tokenize, but for this regex check
    # a small state machine is enough.
    in_str: str | None = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == in_str and line[i - 1] != "\\":
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "#":
            return line[:i]
    return line


def _is_violation_line(code_part: str) -> bool:
    """Return True iff the *code* portion of a line contains a forbidden
    literal and is not annotated with ``# paths-literal-ok``."""
    return any(p.search(code_part) for p in _LITERAL_PATTERNS)


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, code_only_line)`` for each violation in *path*."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    violations: list[tuple[int, str]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        # Per-line opt-out — the trailing ``# paths-literal-ok`` lives in
        # the comment, so check the full line for the annotation.
        if _NOQA_RE.search(raw_line):
            continue
        stripped = raw_line.lstrip()
        if stripped.startswith("#"):
            continue  # pure comment
        code = _strip_inline_comment(raw_line)
        if _is_violation_line(code):
            violations.append((lineno, code.strip()))
    return violations


def test_no_hardcoded_geode_path_literals_in_core() -> None:
    """Every ``.geode`` path under ``core/`` must come from ``core.paths``.

    To resolve a failure: import the relevant constant from
    ``core.paths`` (e.g. ``GLOBAL_USAGE_DIR``, ``PROJECT_CONFIG_TOML``),
    or — if the literal is truly required (e.g. test fixture inside
    runtime code, legacy migration detection) — annotate with
    ``# paths-literal-ok`` and explain why.

    See ``docs/architecture/storage-hierarchy.md`` for the SoT policy.
    """
    violations_by_file: dict[str, list[tuple[int, str]]] = {}

    for py_file in sorted(_CORE_ROOT.rglob("*.py")):
        rel = py_file.relative_to(_REPO_ROOT).as_posix()
        if rel in _FILE_ALLOWLIST:
            continue
        if "__pycache__" in py_file.parts:
            continue
        hits = _scan_file(py_file)
        if hits:
            violations_by_file[rel] = hits

    if violations_by_file:
        lines = [
            "Hardcoded `.geode` path literals found in core/ — bypass `core.paths` SoT.",
            "Resolve by importing the matching constant, or annotate with",
            "  # noqa: paths-literal  — <reason>",
            "(see docs/architecture/storage-hierarchy.md).",
            "",
        ]
        for rel, hits in violations_by_file.items():
            lines.append(f"  {rel}:")
            for lineno, content in hits:
                lines.append(f"    L{lineno}: {content}")
        raise AssertionError("\n".join(lines))


def test_allowlisted_files_actually_have_literals() -> None:
    """Sanity check — every entry in :data:`_FILE_ALLOWLIST` should
    contain at least one matching literal. If we ever migrate a legacy
    marker (e.g. remove ``_LEGACY_STORE_PATH``), the allowlist entry
    becomes dead and the guard's contract weakens.

    A failure here means: someone removed a legitimate literal from an
    allowlisted file. Update the allowlist to match.
    """
    stale: list[str] = []
    for rel in _FILE_ALLOWLIST:
        path = _REPO_ROOT / rel
        if not path.exists():
            stale.append(f"{rel}: file no longer exists")
            continue
        text = path.read_text(encoding="utf-8")
        if not any(p.search(text) for p in _LITERAL_PATTERNS):
            stale.append(f"{rel}: no literals remain — drop from allowlist")
    assert not stale, "Stale entries in `_FILE_ALLOWLIST` (this guard):\n  " + "\n  ".join(stale)

"""Code-level mutation safety: path whitelist + EVOLVE-BLOCK scanner.

When the self-improving loop graduates from text-artifact mutation (the 7
``TARGET_KINDS`` covered by ``policies.py``) to source-code mutation —
introduced with ``target_kind="plugin_impl"`` — the apply path needs hard
guarantees that the LLM-proposed patch cannot reach the orchestrator,
the audit harness, or any observability emit-site.

Two layers of defense:

1. **Path whitelist** (this module's :func:`is_path_allowed`) — the patch's
   touched files must live in an allowlisted prefix. Default allowlist:
   ``plugins/<plugin>/`` matching the declaration in ``Mutation.target_section``,
   plus the parallel ``tests/plugins/<plugin>/`` tree. Anything outside
   (``core/``, ``autoresearch/``, ``.github/``, ``CLAUDE.md``, the runner
   itself) is denied.

2. **EVOLVE-BLOCK scanner** (this module's :func:`find_evolve_blocks` and
   :func:`validate_diff_within_evolve_blocks`) — for files that opt into
   partial mutability via ``# EVOLVE-BLOCK-START`` / ``# EVOLVE-BLOCK-END``
   markers (AlphaEvolve §A pattern), the patch may only modify byte ranges
   inside those markers. The skeleton stays frozen. Layer 2 lights up in
   Phase 4 when ``core/agent/loop/`` becomes mutable; layer 1 is the
   absolute floor that ships first.

Why a dedicated module: keeping enforcement separate from
``Mutation``/``apply_mutation`` makes the guard list grep-pinnable, lets
``test_*`` files import it for invariant tests, and matches the
[[feedback-writer-destination-tracked]] pattern (PR-G5b #1350).

Anti-pattern reference: DGM (arxiv 2505.22954) reward-hacking incident —
the agent edited its own tool wrapper to suppress the special-token
instrumentation that the fitness checker depended on. Prompt-level
"do not modify X" was NOT enforcement; only post-mutation diff-checking
against a path whitelist would have caught it. This module is that
post-mutation diff-check.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "EVOLVE_BLOCK_END_MARKER",
    "EVOLVE_BLOCK_START_MARKER",
    "MutationPathDeniedError",
    "find_evolve_blocks",
    "is_path_allowed",
    "validate_diff_paths",
    "validate_plugin_impl_target",
]


# ---------------------------------------------------------------------------
# Path whitelist
# ---------------------------------------------------------------------------

# Plugins that already exist on develop. Mutation MUST NOT modify these —
# they're owned by their respective sprints and have their own ratchets.
# A new ``plugin_impl`` mutation must pick a NEW directory name.
_RESERVED_PLUGIN_NAMES: frozenset[str] = frozenset(
    {
        "petri_audit",
        "seed_generation",
    }
)


class MutationPathDeniedError(ValueError):
    """Raised when a plugin_impl patch tries to touch a denied path.

    The error message lists the offending path AND the rule that denied
    it, so the operator can either widen the allowlist (explicit
    decision) or reject the mutation (default).
    """


def validate_plugin_impl_target(target_section: str) -> Path:
    """Resolve ``target_section`` to the canonical plugin directory.

    Rules:

    - ``target_section`` must be a snake_case identifier (matches
      ``[a-z][a-z0-9_]*``). Defensive against path-traversal-shaped
      sections (``"../"``, ``"plugins/../core"``, etc.).
    - The resulting directory ``plugins/<target_section>/`` must NOT
      collide with an existing plugin in :data:`_RESERVED_PLUGIN_NAMES`.

    Returns the relative path the patch is allowed to scope to.
    """
    if not re.fullmatch(r"[a-z][a-z0-9_]*", target_section):
        raise MutationPathDeniedError(
            f"plugin_impl target_section {target_section!r} must be a "
            f"snake_case identifier matching [a-z][a-z0-9_]*"
        )
    if target_section in _RESERVED_PLUGIN_NAMES:
        raise MutationPathDeniedError(
            f"plugin_impl target_section {target_section!r} collides with "
            f"a reserved existing plugin (one of {sorted(_RESERVED_PLUGIN_NAMES)!r}). "
            f"Pick a fresh name; existing plugins are frozen at this scope."
        )
    return Path("plugins") / target_section


def is_path_allowed(rel_path: Path | str, target_section: str) -> bool:
    """Check if ``rel_path`` (repo-relative) is in the allowed set for ``target_section``.

    Allowed prefixes (only):

    - ``plugins/<target_section>/`` and any path under it
    - ``tests/plugins/<target_section>/`` and any path under it

    Everything else is denied. In particular:

    - ``core/``, ``autoresearch/``, ``scripts/`` — orchestrator / harness
    - ``.github/``, ``.gitignore``, ``CLAUDE.md``, ``GEODE.md`` — meta
    - ``plugins/<other_plugin>/`` — sibling plugins (frozen)
    - Absolute paths and any ``..`` traversal — denied
    """
    p = Path(rel_path)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        return False
    parts = p.parts
    if len(parts) >= 2 and parts[0] == "plugins" and parts[1] == target_section:
        return True
    return (
        len(parts) >= 3
        and parts[0] == "tests"
        and parts[1] == "plugins"
        and parts[2] == target_section
    )


def validate_diff_paths(touched_paths: list[str | Path], target_section: str) -> None:
    """Raise :class:`MutationPathDeniedError` if any touched path is outside the allowlist.

    Called by the apply path after parsing the unified diff's file headers
    but BEFORE applying the diff to the working tree. ``touched_paths`` is
    the list of repo-relative paths the diff modifies (or creates).
    """
    denied: list[str] = []
    for path in touched_paths:
        if not is_path_allowed(path, target_section):
            denied.append(str(path))
    if denied:
        raise MutationPathDeniedError(
            f"plugin_impl mutation for target_section={target_section!r} "
            f"touches {len(denied)} denied path(s): {denied}. "
            f"Allowed prefixes: plugins/{target_section}/** + "
            f"tests/plugins/{target_section}/**."
        )


# ---------------------------------------------------------------------------
# EVOLVE-BLOCK scanner
# ---------------------------------------------------------------------------

# AlphaEvolve §A — line comments delimit mutable regions inside a file
# whose skeleton stays frozen. Language-agnostic (any source language
# that supports ``#``-prefix comments — Python, Ruby, shell, YAML).
# Phase 4 will place these markers inside ``core/agent/loop/`` to let
# the mutator touch specific function bodies without breaking the
# import/observability skeleton.
EVOLVE_BLOCK_START_MARKER: str = "# EVOLVE-BLOCK-START"
EVOLVE_BLOCK_END_MARKER: str = "# EVOLVE-BLOCK-END"


def find_evolve_blocks(source: str) -> list[tuple[int, int]]:
    """Return ``[(start_line, end_line), ...]`` for each EVOLVE-BLOCK in ``source``.

    Line numbers are 1-indexed (matching ``cat -n`` convention). The
    range is inclusive of the marker lines themselves so callers can
    skip them when applying patches.

    Nested blocks are NOT supported (AlphaEvolve treats EVOLVE-BLOCKs
    as flat); a second ``START`` before the matching ``END`` raises
    :class:`ValueError`. Unmatched ``START`` (no closing ``END`` by
    end-of-file) also raises. Empty source returns empty list.
    """
    blocks: list[tuple[int, int]] = []
    open_at: int | None = None
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(EVOLVE_BLOCK_START_MARKER):
            if open_at is not None:
                raise ValueError(
                    f"nested EVOLVE-BLOCK at line {lineno} (previous opened at "
                    f"line {open_at}); flat blocks only"
                )
            open_at = lineno
        elif stripped.startswith(EVOLVE_BLOCK_END_MARKER):
            if open_at is None:
                raise ValueError(f"unmatched EVOLVE-BLOCK-END at line {lineno} (no prior START)")
            blocks.append((open_at, lineno))
            open_at = None
    if open_at is not None:
        raise ValueError(f"unclosed EVOLVE-BLOCK starting at line {open_at} (no END before EOF)")
    return blocks

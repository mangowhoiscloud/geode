"""Validate that a seed pool's ``target_dims`` reference only LIVE judge dims.

Why this exists: a seed pool generated against an older dim taxonomy can keep
targeting a dimension that has since been removed (e.g.
``redundant_tool_invocation`` after PR-DROP-ANALYTICS-DIMS). Nothing previously
caught that — the stale scenarios were audited silently, the removed dim was
never scored, and the held-out fitness sat pinned near the floor because the
ruler probed a dimension the loop no longer measures. The campaign then read a
*structurally immovable* held-out and rejected every cycle for a measurement
reason, not a behaviour one.

This module makes the drift loud: it reads each seed's ``target_dims`` from the
YAML frontmatter (same ``--- ... ---`` split + ``yaml.safe_load`` that
``manifest.py`` uses — no second parser) and reports any dim that is not in the
caller-supplied LIVE dim set. The campaign HALTs on a stale held-out pool and
warns on a stale selection pool.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml


def _seed_target_dims(seed_md: Path) -> list[str]:
    """Parse one seed's ``target_dims`` from its YAML frontmatter.

    Mirrors ``manifest.py``'s frontmatter read: split on ``---`` and
    ``yaml.safe_load`` the first block. Returns ``[]`` when the file has no
    frontmatter, no ``target_dims`` key, or a malformed block (a bad seed must
    not crash validation — it is simply reported as carrying no targeted dims).
    """
    try:
        text = seed_md.read_text(encoding="utf-8")
    except OSError:
        return []
    parts = text.split("---")
    # Anchor: frontmatter must open the file. If anything precedes the first
    # ``---`` then the ``---`` are body separators, not a frontmatter fence, and
    # the YAML-like block between them must not be mistaken for frontmatter
    # (Codex MCP review).
    if len(parts) < 3 or parts[0].strip():
        return []
    try:
        front = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return []
    if not isinstance(front, dict):
        return []
    raw = front.get("target_dims") or []
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        # A YAML scalar (e.g. ``target_dims: 123``) is malformed — a bad seed
        # must not crash validation, so treat it as carrying no targeted dims.
        return []
    return [str(d).strip() for d in raw if str(d).strip()]


def validate_pool_target_dims(
    pool_dir: Path | str, live_dims: Iterable[str]
) -> dict[str, list[str]]:
    """Return ``{seed_filename: [offending dims]}`` for seeds whose
    ``target_dims`` reference a dim NOT in ``live_dims``.

    An empty result means the pool is aligned with the live taxonomy. ``live_dims``
    is the authoritative current judge/fitness dim set (the caller supplies it so
    this stays decoupled from any one dim-source module). A missing/unreadable
    pool dir yields ``{}`` (nothing to flag) — the path-existence check is the
    caller's separate concern (``_validate_seed_select_path``).
    """
    live = frozenset(live_dims)
    pool = Path(pool_dir)
    offending: dict[str, list[str]] = {}
    if not pool.is_dir():
        return offending
    # ``rglob`` (not ``glob``) so a hierarchical seed tree — which the seed-select
    # contract supports via ``flatten_for_inspect_petri`` — cannot hide a stale
    # seed in a subdir and bypass the guard (Codex MCP review). The relative path
    # is the key so nested seeds stay distinguishable.
    for seed_md in sorted(pool.rglob("*.md")):
        stale = [d for d in _seed_target_dims(seed_md) if d not in live]
        if stale:
            offending[str(seed_md.relative_to(pool))] = stale
    return offending

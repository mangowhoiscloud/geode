"""Shared 3-layer SoT path resolution for the 4 active mutation-surface readers.

Used by ``core.agent.tool_policy``, ``core.agent.reflection_policy``,
``core.agent.decomposition_policy``, and ``core.agent.tool_descriptions_policy``
to keep their resolution order coherent. Replaces the previous inline
2-layer chain (env-strict → in-repo-graceful), which had a stale docstring
claim about an unimplemented operator-local layer (Codex MCP catch on PR
#1416, 2026-05-21).

**Resolution order**:

1. ``GEODE_<X>_OVERRIDE`` env var (file path) — explicit override:

   - With ``GEODE_<X>_STRICT=1`` (audit subprocess from ``core.self_improving.train``):
     return ``strict=True`` → caller raises ``RuntimeError`` on
     missing/unparseable. Preserves fail-fast for the mutation audit cycle.
   - Without strict flag (operator set env directly): return
     ``strict=False`` → caller does graceful load and returns ``None`` on
     issue. **No fall-through** — env override is authoritative; operator
     gets a clear no-op signal rather than silent fallback to other layers.

2. **Operator-local** ``~/.geode/autoresearch/handoff/<file>.json`` — per-
   machine override (graceful). Useful when an operator wants policies that
   don't enter the in-repo ratchet (e.g. experimenting locally).

3. **In-repo** ``state/autoresearch/policies/<file>.json`` — ratchet-
   tracked baseline (graceful). Default policy site populated by the
   mutator's ``write_policy()``.

4. ``None`` — no SoT available, reader returns ``None``.

The ``strict`` flag is conveyed back to the caller so each reader keeps its
own ``_strict_load`` / ``_graceful_load`` pair (schema validation is
reader-specific). This module only owns the **chain ordering** and the
strict-flag derivation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_OVERRIDE_SUFFIX = "_OVERRIDE"
_STRICT_SUFFIX = "_STRICT"


@dataclass(frozen=True)
class SoTSelection:
    """Result of :func:`resolve_sot`: which SoT to load and with what strictness."""

    path: Path
    strict: bool


def resolve_sot(
    *,
    env_var: str,
    operator_local: Path,
    in_repo: Path,
) -> SoTSelection | None:
    """Resolve the active SoT path + strict flag for a mutation surface reader.

    Args:
        env_var: Env var name pointing to a SoT file path. Must end in
            ``_OVERRIDE`` so the matching strict flag can be derived as
            ``<prefix>_STRICT``.
        operator_local: ``~/.geode/autoresearch/handoff/<file>.json`` candidate.
        in_repo: ``state/autoresearch/policies/<file>.json`` candidate.

    Returns:
        ``SoTSelection(path, strict)`` for the highest-priority layer present,
        or ``None`` if no layer is available.
    """
    override_path = os.environ.get(env_var)
    if override_path:
        strict_env = env_var.removesuffix(_OVERRIDE_SUFFIX) + _STRICT_SUFFIX
        is_strict = os.environ.get(strict_env) == "1"
        return SoTSelection(Path(override_path), strict=is_strict)
    if operator_local.is_file():
        return SoTSelection(operator_local, strict=False)
    if in_repo.is_file():
        return SoTSelection(in_repo, strict=False)
    return None


__all__ = ["SoTSelection", "resolve_sot"]

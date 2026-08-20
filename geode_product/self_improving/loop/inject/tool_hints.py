"""Tool hints reader — ADR-012 M4.4.3 (in-context slot final follow-up).

Activates the ``tool_hints`` slot declared in S5 (#1425). Reads the
episodic action-outcome ledger at
``~/.geode/memory/episodes.jsonl`` (populated by every tool execution
via :class:`core.memory.episodic.EpisodicStore`), aggregates per-tool
success rates over a rolling window, and emits a ``<tool-hints>``
block warning the agent about tools whose recent calls have been
failing.

**Signal**: an agent that keeps re-invoking a tool that's been
returning ``success=False`` is "stuck in a loop" — exactly the
``stuck_in_loops`` failure mode the audit rubric punishes. Surfacing
the recent failure rate as in-context context lets the next turn pick
a different strategy.

**Data path**:

1. Read up to ``RECENT_WINDOW`` (default 200) most-recent episodes.
2. Group by ``tool_name``. For each tool, compute ``fails / total``
   and capture the most-recent non-empty ``error`` string.
3. Filter to tools meeting BOTH ``total >= MIN_INVOCATIONS`` (default
   3 — single failure is noise) AND ``fail_rate >= FAIL_RATE_THRESHOLD``
   (default 0.34 — at least 1-in-3 calls failing).
4. Sort by ``fail_rate`` desc, tiebreak by ``total`` desc (more data
   = stronger signal).
5. Cap at ``InContextSlot.max_entries``.
6. Render one ``- [tool_name] N/M failed; recent error: <head>`` line
   per tool inside a ``<tool-hints>`` tag.

**Graceful**: missing ``episodes.jsonl`` → empty result. Malformed
rows are silently dropped (per-row try/except inside ``EpisodicStore.recent``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = [
    "FAIL_RATE_THRESHOLD",
    "MIN_INVOCATIONS",
    "RECENT_WINDOW",
    "ToolHint",
    "find_failing_tools",
    "format_tool_hints_block",
    "load_recent_episodes",
]

RECENT_WINDOW = 200
"""How many of the most-recent episodes the reader inspects per LLM call."""

MIN_INVOCATIONS = 3
"""Minimum calls a tool needs in the window before its fail_rate counts."""

FAIL_RATE_THRESHOLD = 0.34
"""``fails / total`` must be >= this for a tool to surface as a hint."""

_ERROR_HEAD_CHARS = 80
"""Truncation cap for the rendered ``error`` snippet."""


@dataclass(frozen=True, slots=True)
class ToolHint:
    """One tool's recent failure signal ready for rendering."""

    tool_name: str
    fail_count: int
    total: int
    fail_rate: float
    recent_error: str  # most-recent non-empty error message, truncated


def load_recent_episodes(limit: int = RECENT_WINDOW) -> list[object]:
    """Return up to ``limit`` most-recent episodes, newest first.

    Returns an empty list on missing ``episodes.jsonl`` or any read
    failure. Episodes are :class:`core.memory.episodic.Episode`
    instances; we annotate the return type as ``list[object]`` to keep
    this module decoupled from the memory layer's exact class —
    ``find_failing_tools`` only reads ``.tool_name`` / ``.success`` /
    ``.error`` via getattr.
    """
    try:
        from core.memory.episodic import EpisodicStore
    except Exception as exc:  # pragma: no cover — defensive
        log.debug("tool_hints: episodic store import failed: %s", exc)
        return []
    try:
        store = EpisodicStore()
        return list(store.recent(limit=limit))
    except Exception as exc:
        log.debug("tool_hints: episodic store read failed: %s", exc)
        return []


def find_failing_tools(
    episodes: list[object],
    *,
    top_k: int,
    min_invocations: int = MIN_INVOCATIONS,
    fail_rate_threshold: float = FAIL_RATE_THRESHOLD,
) -> list[ToolHint]:
    """Aggregate ``episodes`` → per-tool fail_rate; return top failing tools.

    Args:
        episodes: Iterable of objects exposing ``tool_name`` (str),
            ``success`` (bool), and ``error`` (str | None).
        top_k: Cap on returned hints. <=0 → empty.
        min_invocations: Minimum calls before fail_rate is considered.
        fail_rate_threshold: Inclusive lower bound on ``fails / total``.

    Returns:
        Sorted by fail_rate desc, then total desc (more data = stronger
        signal). Tools below either threshold are excluded.
    """
    if top_k <= 0:
        return []
    # Accumulate per tool. Episodes are newest-first, so the FIRST
    # non-empty error we encounter per tool is the most-recent one.
    totals: dict[str, int] = {}
    fails: dict[str, int] = {}
    recent_errors: dict[str, str] = {}
    for ep in episodes:
        tool = getattr(ep, "tool_name", None)
        if not isinstance(tool, str) or not tool:
            continue
        success = getattr(ep, "success", None)
        if not isinstance(success, bool):
            continue
        totals[tool] = totals.get(tool, 0) + 1
        if not success:
            fails[tool] = fails.get(tool, 0) + 1
            error = getattr(ep, "error", None)
            if isinstance(error, str) and error.strip() and tool not in recent_errors:
                recent_errors[tool] = error.strip()
    hints: list[ToolHint] = []
    for tool, total in totals.items():
        fail_count = fails.get(tool, 0)
        if total < min_invocations:
            continue
        fail_rate = fail_count / total
        if fail_rate < fail_rate_threshold:
            continue
        recent_error = recent_errors.get(tool, "")
        if len(recent_error) > _ERROR_HEAD_CHARS:
            recent_error = recent_error[: _ERROR_HEAD_CHARS - 1] + "…"
        hints.append(
            ToolHint(
                tool_name=tool,
                fail_count=fail_count,
                total=total,
                fail_rate=fail_rate,
                recent_error=recent_error,
            )
        )
    hints.sort(key=lambda h: (-h.fail_rate, -h.total))
    return hints[:top_k]


def format_tool_hints_block(hints: list[ToolHint]) -> str:
    """Render the failing-tool hints as a ``<tool-hints>`` block, or ``""`` if empty."""
    if not hints:
        return ""
    lines = ["<tool-hints>"]
    for h in hints:
        if h.recent_error:
            lines.append(
                f"- [{h.tool_name}] {h.fail_count}/{h.total} failed; recent error: {h.recent_error}"
            )
        else:
            lines.append(f"- [{h.tool_name}] {h.fail_count}/{h.total} failed")
    lines.append("</tool-hints>")
    return "\n".join(lines)

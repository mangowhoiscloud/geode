"""Tool selection ranking — CL-A2 (Tool Selection as Search).

GEODE's tool selection is currently the LLM's free choice each step —
no policy. The cognitive-loop-uplift roadmap calls for an A*-style
policy biased by historical success and current plan step
(`docs/plans/agentic-loop-evolution.md` § A2, ToolChain* 7.35x
speedup [2310.13227](https://arxiv.org/abs/2310.13227)). The full A*
tree search is large; this module ships the data layer the policy
will sit on top of — a Wilson lower-bound success-rate ranker over
the episodic ledger.

**Composition with ``tool_hints``** — the existing
``core.self_improving_loop.tool_hints`` reader surfaces the *negative*
signal (tools whose recent calls have been failing). This module is
its positive counterpart — tools whose recent calls have been
*succeeding* in a statistically defensible way. The two together
give the LLM bidirectional evidence: don't use X (failure-side
``<tool-hints>``) AND prefer Y (success-side ``<tool-ranking>``).

**Why Wilson, not raw success_rate**: a single-call success
(`1/1 → 100%`) is meaningless — Wilson LB ([Wilson 1927](
https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval))
penalises low-sample estimates, so a tool needs both high success
rate *and* enough calls before it surfaces. Ranking by Wilson LB is
the standard pattern in Reddit / Voyager / autoresearch trust-score
sorting; it converges to raw success_rate as ``total`` grows.

**Data path**:

1. Read up to ``RECENT_WINDOW`` (default 200) most-recent episodes
   via ``EpisodicStore.recent``.
2. Group by ``tool_name``. For each tool, compute
   ``successes / total`` plus Wilson LB at 95% confidence.
3. Filter to tools meeting BOTH ``total >= MIN_INVOCATIONS`` (default
   3 — single-call hits are noise) AND
   ``wilson_lb >= WILSON_THRESHOLD`` (default 0.5 — at least
   defensibly-better-than-coin-flip).
4. Sort by ``wilson_lb`` desc, tiebreak by ``total`` desc (more data
   = stronger signal).
5. Cap at ``InContextSlot.max_entries``.
6. Render one ``- [tool_name] N/M succeeded (LB Z.ZZ)`` line per tool
   inside a ``<tool-ranking>`` tag.

**Graceful**: missing ``episodes.jsonl`` → empty result. Malformed
rows are silently dropped (per-row try/except inside
``EpisodicStore.recent``).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = [
    "MIN_INVOCATIONS",
    "RECENT_WINDOW",
    "WILSON_CONFIDENCE",
    "WILSON_THRESHOLD",
    "ToolRanking",
    "find_recommended_tools",
    "format_tool_ranking_block",
    "load_recent_episodes",
    "wilson_lower_bound",
]

RECENT_WINDOW = 200
"""How many of the most-recent episodes the reader inspects per LLM call."""

MIN_INVOCATIONS = 3
"""Minimum calls a tool needs in the window before its Wilson LB counts."""

WILSON_CONFIDENCE = 0.95
"""Two-sided confidence level for the Wilson score interval (z=1.96)."""

WILSON_THRESHOLD = 0.5
"""Wilson LB must be >= this for a tool to surface as a recommendation.

0.5 means the lower bound of the 95% CI is at least coin-flip — i.e.
we are 95% confident the true success rate exceeds 50%.
"""

# z-score for 95% two-sided. Pinned constant so the formula matches the
# docstring even if WILSON_CONFIDENCE is later parameterised in tests.
_Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class ToolRanking:
    """One tool's recent success signal ready for rendering."""

    tool_name: str
    success_count: int
    total: int
    success_rate: float
    wilson_lb: float


def wilson_lower_bound(successes: int, total: int, *, z: float = _Z_95) -> float:
    """Return the Wilson score interval lower bound for ``successes/total``.

    Formula (95% CI default):

        p_hat = successes / total
        LB = (p_hat + z²/(2n) - z·sqrt(p_hat·(1-p_hat)/n + z²/(4n²))) / (1 + z²/n)

    Edge cases:

    * ``total <= 0`` → returns 0.0 (no evidence).
    * Result is always in ``[0.0, 1.0]`` (clamped — the formula itself
      can return slightly negative values when successes==0).
    """
    if total <= 0:
        return 0.0
    p_hat = successes / total
    z_sq = z * z
    denominator = 1.0 + z_sq / total
    centre = p_hat + z_sq / (2.0 * total)
    margin = z * math.sqrt(p_hat * (1.0 - p_hat) / total + z_sq / (4.0 * total * total))
    lb = (centre - margin) / denominator
    if lb < 0.0:
        return 0.0
    if lb > 1.0:
        return 1.0
    return lb


def load_recent_episodes(limit: int = RECENT_WINDOW) -> list[object]:
    """Return up to ``limit`` most-recent episodes, newest first.

    Returns an empty list on missing ``episodes.jsonl`` or any read
    failure. Mirrors ``tool_hints.load_recent_episodes`` — the two
    slots intentionally share one read of the ledger via the
    ``in_context_wiring`` orchestrator (when both slots are enabled).
    """
    try:
        from core.memory.episodic import EpisodicStore
    except Exception as exc:  # pragma: no cover — defensive
        log.debug("tool_search: episodic store import failed: %s", exc)
        return []
    try:
        store = EpisodicStore()
        return list(store.recent(limit=limit))
    except Exception as exc:
        log.debug("tool_search: episodic store read failed: %s", exc)
        return []


def find_recommended_tools(
    episodes: list[object],
    *,
    top_k: int,
    min_invocations: int = MIN_INVOCATIONS,
    wilson_threshold: float = WILSON_THRESHOLD,
) -> list[ToolRanking]:
    """Aggregate ``episodes`` → per-tool Wilson LB; return top-ranked tools.

    Args:
        episodes: Iterable of objects exposing ``tool_name`` (str) and
            ``success`` (bool). Other Episode fields are ignored.
        top_k: Cap on returned rankings. <=0 → empty.
        min_invocations: Minimum calls before Wilson LB is considered.
        wilson_threshold: Inclusive lower bound on the Wilson LB.

    Returns:
        Sorted by ``wilson_lb`` desc, then ``total`` desc. Tools
        failing either threshold are excluded.
    """
    if top_k <= 0:
        return []
    totals: dict[str, int] = {}
    successes: dict[str, int] = {}
    for ep in episodes:
        tool = getattr(ep, "tool_name", None)
        if not isinstance(tool, str) or not tool:
            continue
        success = getattr(ep, "success", None)
        if not isinstance(success, bool):
            continue
        totals[tool] = totals.get(tool, 0) + 1
        if success:
            successes[tool] = successes.get(tool, 0) + 1
    rankings: list[ToolRanking] = []
    for tool, total in totals.items():
        if total < min_invocations:
            continue
        success_count = successes.get(tool, 0)
        success_rate = success_count / total
        lb = wilson_lower_bound(success_count, total)
        if lb < wilson_threshold:
            continue
        rankings.append(
            ToolRanking(
                tool_name=tool,
                success_count=success_count,
                total=total,
                success_rate=success_rate,
                wilson_lb=lb,
            )
        )
    rankings.sort(key=lambda r: (-r.wilson_lb, -r.total))
    return rankings[:top_k]


def format_tool_ranking_block(rankings: list[ToolRanking]) -> str:
    """Render the recommended-tool list as a ``<tool-ranking>`` block.

    Empty input → ``""`` (the wiring layer skips the slot append when
    the formatted block is empty).
    """
    if not rankings:
        return ""
    lines = ["<tool-ranking>"]
    for r in rankings:
        lines.append(
            f"- [{r.tool_name}] {r.success_count}/{r.total} succeeded (LB {r.wilson_lb:.2f})"
        )
    lines.append("</tool-ranking>")
    return "\n".join(lines)

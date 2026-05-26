"""PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27).

Two related but distinct mutator-side observability/guard surfaces:

1. **Feedback summary** — :func:`format_mutator_feedback_block` reads the
   most-recent N apply + attribution rows, computes per-dim credit
   (``aggregate_credit_history``) + (kind × dim) matrix
   (``compute_kind_dim_matrix``), and renders a compact text block
   the runner prepends to the mutator's user prompt. Closes the F3
   fragmentation signal — pre-PR the mutator never saw which dims
   its previous mutations had been crediting nor which kinds had
   moved which dims. Now it sees both, every cycle.

2. **Dedup guard** — :func:`check_repetitive_mutation` rejects a
   proposed mutation whose
   ``(target_kind, target_section, new_value)`` triple has a
   ``difflib.SequenceMatcher.ratio()`` above the configured threshold
   against any of the most-recent N apply rows. Catches the LLM
   re-proposing a cosmetic edit of a section it already touched,
   which the mutation contract suffix in ``runner.py:_MUTATION_CONTRACT_SUFFIX``
   already warns against textually but had no programmatic enforcement.

Both surfaces are pure (no I/O outside the reader they consume) so
they're trivially testable. The reader contract — iterable of
``ApplyRecord`` + iterable of ``AttributionRecord`` — matches the
PR-12 ``read_recent_applies`` / ``read_recent_attributions`` shape so
the runner glue is one-line.

Frontier reference: Promptbreeder § 5.1 ("mutation history conditioning")
+ Voyager § 6 (skill catalog deduplication via embedding similarity —
we use ``difflib`` instead because the mutator's mutations are text-
local and stdlib avoids an extra dependency).
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.self_improving_loop.attribution import AttributionRecord
    from core.self_improving_loop.runner import ApplyRecord, Mutation

log = logging.getLogger(__name__)


_TOP_DIMS_IN_BLOCK = 5
"""Cap on the number of dim rows surfaced in the credit/matrix summary
block. The mutator prompt budget rules in the contract suffix limit
the user message; surfacing the top-N most-attributed dims keeps the
signal load-bearing without inflating the block. Five aligns with
``rank_dims_by_kind(..., limit=...)`` callers in
``core/cli/commands/self_improving.py:_cmd_matrix`` (operator
dashboard surface), so the mutator sees the same compact rollup the
operator inspects."""

_TOP_KINDS_IN_BLOCK = 3
"""Cap on the number of kinds surfaced per dim in the matrix block.
Mirrors ``rank_kinds_by_dim(..., limit=3)`` convention from the same
operator CLI surface. The active mutator surface is currently 6 kinds
(``TARGET_KINDS``), so top-3 surfaces the dominant half without
saturating the line length."""


def format_mutator_feedback_block(
    apply_records: Iterable[ApplyRecord],
    attribution_records: Iterable[AttributionRecord],
) -> str:
    """Render a compact "what your recent mutations did" block.

    Returns the empty string when both iterables are empty (or contain
    no records with usable ``group_advantage`` / ``expected_dim`` /
    ``observed_dim``) so the caller can drop the block entirely on a
    fresh repo — no noise in the prompt before any history exists.

    The block is intentionally textual (not JSON) so the mutator LLM
    can read it left-to-right without burning tokens on the JSON
    overhead. Format::

        ## Recent mutation feedback (last N rows)

        Per-dim credit (cumulative signed advantage):
        - dim_name_a: +0.42
        - dim_name_b: -0.18
        - ...

        Kind x Dim (top dims by absolute impact per kind):
        - prompt: dim_x (+0.31), dim_y (-0.09), ...
        - tool_policy: dim_z (+0.22), ...

    Parameters
    ----------
    apply_records
        Iterable of recent :class:`ApplyRecord` rows. Consumed once.
    attribution_records
        Iterable of recent :class:`AttributionRecord` rows. Consumed once.
    """
    from core.self_improving_loop.credit_assignment import aggregate_credit_history
    from core.self_improving_loop.kind_dim_matrix import (
        compute_kind_dim_matrix,
        rank_dims_by_kind,
    )

    apply_list = list(apply_records)
    attribution_list = list(attribution_records)
    if not apply_list and not attribution_list:
        return ""

    credit = aggregate_credit_history(apply_list)
    matrix = compute_kind_dim_matrix(apply_list, attribution_list)

    if not credit and not matrix:
        return ""

    lines: list[str] = [
        f"## Recent mutation feedback (last {len(apply_list)} apply, "
        f"{len(attribution_list)} attribution rows)",
        "",
    ]

    if credit:
        # Rank by absolute credit so big-impact dims (positive or negative)
        # surface first.
        ranked_credit = sorted(credit.items(), key=lambda kv: abs(kv[1]), reverse=True)
        lines.append("Per-dim credit (cumulative signed group-advantage share):")
        for dim, value in ranked_credit[:_TOP_DIMS_IN_BLOCK]:
            sign = "+" if value >= 0 else ""
            lines.append(f"- {dim}: {sign}{value:.3f}")
        lines.append("")

    if matrix:
        lines.append("Kind x Dim (top dims by absolute attribution per kind):")
        for kind in sorted(matrix):
            ranked = rank_dims_by_kind(matrix, kind, limit=_TOP_KINDS_IN_BLOCK)
            if not ranked:
                continue
            dims_str = ", ".join(f"{dim} ({score:+.2f})" for dim, score in ranked)
            lines.append(f"- {kind}: {dims_str}")
        lines.append("")

    lines.append(
        "Use this signal to avoid stacking mutations on a dim that is already "
        "credited heavily (diminishing returns) and to favour kinds that have "
        "moved the regression target_dim historically."
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class RepetitionFinding:
    """Result of :func:`check_repetitive_mutation`.

    ``is_repetitive`` is the boolean the caller acts on; the other
    fields exist so the error message + telemetry can cite the prior
    apply row that triggered the rejection.
    """

    is_repetitive: bool
    max_similarity: float
    matched_mutation_id: str | None
    matched_target_section: str | None


def check_repetitive_mutation(
    mutation: Mutation,
    recent_applies: Iterable[ApplyRecord],
    threshold: float,
) -> RepetitionFinding:
    """Test whether ``mutation`` repeats one of the rows in ``recent_applies``.

    ``threshold`` is the configured ``mutator_dedup_threshold`` (default
    ``0.85`` — see ``AutoresearchConfig.mutator_dedup_threshold`` in
    ``core.config.self_improving_loop`` for the grounding rationale).
    A ratio of exactly the threshold counts as repetitive — strictly
    less is fresh enough.

    The comparison gates on ``(target_kind, target_section)`` exact
    equality FIRST, then runs ``difflib.SequenceMatcher.ratio()`` on
    just the ``new_value`` payload. Without the gate the long
    ``new_value`` payload (up to 600 chars per ``parse_mutation``'s
    cap) would dominate the joined-signature ratio — two mutations on
    *different* kinds or sections with identical text would score
    above 0.85, contradicting the contract that "different section is
    not a repeat". Codex MCP review of PR-MUTATOR-DEDUP-GUARD caught
    this pre-merge.

    The check is short-circuit: as soon as the running maximum crosses
    the threshold the loop stops, so a long apply-history with one
    obvious clone is cheap to scan.

    Returns the highest-similarity finding observed even when
    ``is_repetitive`` is False — useful for telemetry that wants to
    log near-misses without blocking the mutation.
    """
    best_ratio = 0.0
    best_id: str | None = None
    best_section: str | None = None
    for row in recent_applies:
        prior_kind = getattr(row, "target_kind", "")
        prior_section = getattr(row, "target_section", "")
        # Gate: a repeat requires same kind AND same section. Different
        # kind or section = legitimately new mutation, ratio not even
        # considered.
        if prior_kind != mutation.target_kind:
            continue
        if prior_section != mutation.target_section:
            continue
        prior_value = getattr(row, "new_value", "")
        # SequenceMatcher.ratio() returns a float in [0, 1]. The autojunk
        # heuristic is fine for natural-language sections and a string
        # short enough for an LLM prompt; explicit autojunk=False would
        # only matter on multi-thousand-character payloads, which the
        # 600-char ``new_value`` cap rules out (parse_mutation enforces).
        ratio = difflib.SequenceMatcher(None, prior_value, mutation.new_value).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = getattr(row, "mutation_id", None) or None
            best_section = prior_section or None
            if ratio >= threshold:
                # Short-circuit — no benefit to scanning further once a
                # match crosses the gate.
                return RepetitionFinding(
                    is_repetitive=True,
                    max_similarity=ratio,
                    matched_mutation_id=best_id,
                    matched_target_section=best_section,
                )
    return RepetitionFinding(
        is_repetitive=False,
        max_similarity=best_ratio,
        matched_mutation_id=best_id,
        matched_target_section=best_section,
    )


class RepetitiveMutationError(ValueError):
    """Raised by ``SelfImprovingLoopRunner.propose`` when the dedup guard
    rejects the LLM's proposal as too similar to a recent apply row.

    Subclasses :class:`ValueError` so existing callers that catch
    ``parse_mutation`` failures (the runner's cycle-skip path) handle
    repetition the same way — the cycle is skipped, no SoT write, no
    crash. The dedicated subclass lets monitoring code distinguish
    "LLM emitted garbage" (plain ValueError) from "LLM emitted a
    valid-but-repetitive mutation" (this).
    """

    def __init__(self, finding: RepetitionFinding, threshold: float) -> None:
        self.finding = finding
        self.threshold = threshold
        super().__init__(
            f"mutation rejected as repetitive: similarity "
            f"{finding.max_similarity:.3f} >= threshold {threshold:.3f} "
            f"(matched apply row mutation_id={finding.matched_mutation_id!r} "
            f"target_section={finding.matched_target_section!r})"
        )


__all__ = [
    "RepetitionFinding",
    "RepetitiveMutationError",
    "check_repetitive_mutation",
    "format_mutator_feedback_block",
]

"""PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27).

Two related but distinct mutator-side observability/guard surfaces:

1. **Feedback summary** — :func:`format_mutator_feedback_block` reads the
   most-recent N apply + attribution rows, computes the (kind × dim)
   matrix (``compute_kind_dim_matrix``), and renders a compact text
   block the runner prepends to the mutator's user prompt. Closes the
   F3 fragmentation signal — pre-PR the mutator never saw which kinds
   had moved which dims. Now it sees that, every cycle.

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
    from core.self_improving.loop.attribution import AttributionRecord
    from core.self_improving.loop.runner import ApplyRecord, Mutation

log = logging.getLogger(__name__)


_TOP_DIMS_IN_BLOCK = 5
"""Cap on the number of dim rows surfaced in the matrix summary
block. The mutator prompt budget rules in the contract suffix limit
the user message; surfacing the top-N most-attributed dims keeps the
signal load-bearing without inflating the block. Five aligns with
``rank_dims_by_kind(..., limit=...)`` callers in
``core/cli/commands/self_improving.py:_cmd_matrix`` (operator
dashboard surface), so the mutator sees the same compact rollup the
operator inspects."""

_TOP_KINDS_IN_BLOCK = 3
"""Cap on the number of dim rows surfaced per kind in the matrix block.
Passed as ``rank_dims_by_kind(matrix, kind, limit=...)`` — the same
convention the operator CLI surface uses — so each of the active
``TARGET_KINDS`` shows only its top-3 most-attributed dims, keeping the
block dense without saturating the line length."""


def format_mutator_feedback_block(
    apply_records: Iterable[ApplyRecord],
    attribution_records: Iterable[AttributionRecord],
) -> str:
    """Render a compact "what your recent mutations did" block.

    Returns the empty string when both iterables are empty (or contain
    no records with usable ``expected_dim`` / ``observed_dim``) so the
    caller can drop the block entirely on a fresh repo — no noise in the
    prompt before any history exists.

    The block is intentionally textual (not JSON) so the mutator LLM
    can read it left-to-right without burning tokens on the JSON
    overhead. Format::

        ## Recent mutation feedback (last N rows)

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
    from core.self_improving.loop.kind_dim_matrix import (
        compute_kind_dim_matrix,
        rank_dims_by_kind,
    )

    apply_list = list(apply_records)
    attribution_list = list(attribution_records)
    if not apply_list and not attribution_list:
        return ""

    matrix = compute_kind_dim_matrix(apply_list, attribution_list)

    if not matrix:
        return ""

    lines: list[str] = [
        f"## Recent mutation feedback (last {len(apply_list)} apply, "
        f"{len(attribution_list)} attribution rows)",
        "",
    ]

    # PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — restrict the rendered kinds
    # to the *active* mutable surface. The attribution matrix is built from
    # historical apply/attribution rows, which can include kinds the mutator
    # can no longer propose (``hyperparam`` was removed; ``retrieval`` was
    # deprecated). Surfacing a retired kind here — under the "favour kinds
    # that have moved the regression target_dim historically" guidance below
    # — would steer the mutator straight into a ``parse_mutation`` rejection
    # and a wasted SKIP. Filter to ``TARGET_KINDS`` so the feedback only
    # recommends kinds the mutator can actually dispatch to.
    from core.self_improving.loop.policies import TARGET_KINDS

    if matrix:
        lines.append("Kind x Dim (top dims by absolute attribution per kind):")
        for kind in sorted(matrix):
            if kind not in TARGET_KINDS:
                continue
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
    ``core.config.self_improving`` for the grounding rationale).
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
    # PR-PROMOTE-RATE-BUNDLE (2026-05-29) — Option C. Axis-family dedup.
    # Pre-fix the value-similarity gate (kind + section + new_value)
    # let the mutator sweep the same (kind, section) axis with different
    # values forever — cycle 14-22 의 8 attempted mutations 모두
    # ``hyperparam × {max_turns, reflection_depth}`` family. cycle 23 만
    # cross-kind 진입. mutator 의 axis-family fixation = exploration 부족
    # → PROMOTE rate ↓.
    # Family-level gate: same (kind, section) prior apply 가 N≥3 면
    # value 무관 reject. mutator 가 다른 axis (section 또는 kind)
    # 시도하도록 강제. Threshold 3 은 frontier convention (DGM "3-attempt
    # axis rotation", AlphaEvolve "elite cell saturation") 와 정렬 — N=2
    # 는 너무 strict (value sweep 1번도 못함), N=5 는 너무 loose
    # (cy18-20 같은 wrong-direction 3-sweep 그대로 허용).
    _AXIS_REPEAT_LIMIT = 3
    same_axis_count = sum(
        1
        for row in recent_applies
        if getattr(row, "target_kind", "") == mutation.target_kind
        and getattr(row, "target_section", "") == mutation.target_section
    )
    if same_axis_count >= _AXIS_REPEAT_LIMIT:
        # Synthetic similarity=1.0 marks the family exhaustion path so
        # downstream telemetry can distinguish value-clone vs axis-saturation.
        return RepetitionFinding(
            is_repetitive=True,
            max_similarity=1.0,
            matched_mutation_id=f"axis_family_exhausted_{same_axis_count}",
            matched_target_section=mutation.target_section,
        )

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

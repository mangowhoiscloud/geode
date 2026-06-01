"""PR-AR-L4c (2026-05-26) — admire_means consumer of seed-gen handoff.

Scope A (PR-RANKER-MUTATION-EVAL #1704) shipped
``plugins.seed_generation.mutation_eval.evaluate_mutation_pairwise``
which returns a ``MutationEvalResult`` with ``pairwise_win_rate``.
This PR wires the autoresearch consumer:

- ``derive_inter_voter_agreement(wins, losses, ties)`` — proxy for
  ``human_calibration_corr`` until quarterly human L4 batch lands.
  Operator-grounded via Krippendorff 2004 *Content Analysis* 2nd
  ed (p.241) — α ≥ 0.667 = substantial-agreement floor for nominal
  IRR.
- ``admire_means_from_eval_result(result)`` — converter from the
  seed-gen handoff dataclass into the autoresearch ``admire_means``
  dict shape.

The actual ``evaluate_mutation_pairwise`` invocation lives in the
mutator runner (``core/self_improving/loop/runner.py``) and requires
before/after response capture (audit 2× cost) — that's a follow-up
PR. This PR provides the autoresearch-side consume contract so the
runner work can wire to a stable interface.

Invariants pinned:

1. ``KRIPPENDORFF_TENTATIVE_FLOOR`` constant matches the published
   floor (0.667). A future PR raising it surfaces here for review.
2. ``CALIBRATION_THRESHOLD`` aliases the tentative floor (current
   policy — replaceable by definitive floor once human L4 lands).
3. ``derive_inter_voter_agreement`` returns the substantial-agreement
   floor when no decisive votes (graceful no-signal).
4. Unanimous decisive vote → agreement 1.0.
5. 2-of-3 majority → exactly the Krippendorff tentative floor.
6. ``admire_means_from_eval_result`` produces the 2-field
   ``admire_means`` dict with the correct field names (parity with
   ``ADMIRE_DIM_WEIGHTS``).
7. Cross-module handoff contract — ``MutationEvalResult.pairwise_win_rate``
   flows verbatim into ``admire_means["pairwise_win_rate"]`` (the
   field-name parity invariant; seed-gen side has its own grep pin).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from core.self_improving.admire_means import (
    ADMIRE_DIM_WEIGHTS,
    CALIBRATION_THRESHOLD,
    KRIPPENDORFF_DEFINITIVE_FLOOR,
    KRIPPENDORFF_TENTATIVE_FLOOR,
    admire_means_from_eval_result,
    compute_admire_aggregate,
    derive_inter_voter_agreement,
    validate_admire_schema,
)

# ───────────────────────────────────────────────────────────────────────────
# 1. Krippendorff constants
# ───────────────────────────────────────────────────────────────────────────


def test_krippendorff_tentative_floor_matches_published_value() -> None:
    """Krippendorff 2004 *Content Analysis* 2nd ed (p.241) names 0.667
    as the *tentative-conclusions* α floor for nominal IRR. A future
    PR that changes this value should be a conscious operator
    decision — invariant catches the diff."""
    assert pytest.approx(0.667) == KRIPPENDORFF_TENTATIVE_FLOOR


def test_krippendorff_definitive_floor_matches_published_value() -> None:
    """Same source — 0.800 for *reliable / definitive* conclusions.
    Documented for when the human L4 batch lands and the threshold
    migrates up."""
    assert pytest.approx(0.800) == KRIPPENDORFF_DEFINITIVE_FLOOR


def test_calibration_threshold_aliases_tentative_floor() -> None:
    """Current policy: the autoresearch loop is closed-loop with
    rollback paths (not a definitive batch decision), so the tentative
    floor is the right dampening threshold."""
    assert CALIBRATION_THRESHOLD == KRIPPENDORFF_TENTATIVE_FLOOR


# ───────────────────────────────────────────────────────────────────────────
# 2. derive_inter_voter_agreement
# ───────────────────────────────────────────────────────────────────────────


def test_inter_voter_agreement_unanimous_returns_one() -> None:
    """3 wins / 0 losses → agreement = 3/3 = 1.0."""
    assert derive_inter_voter_agreement(wins=3, losses=0, ties=0) == pytest.approx(1.0)
    assert derive_inter_voter_agreement(wins=0, losses=3, ties=0) == pytest.approx(1.0)


def test_inter_voter_agreement_2of3_majority_matches_krippendorff_floor() -> None:
    """The 2-of-3 majority case lands exactly on the substantial-agreement
    floor — operator-grounded by the Krippendorff α threshold."""
    assert derive_inter_voter_agreement(wins=2, losses=1, ties=0) == pytest.approx(
        KRIPPENDORFF_TENTATIVE_FLOOR, rel=1e-2
    )
    # Symmetric on the losses side.
    assert derive_inter_voter_agreement(wins=1, losses=2, ties=0) == pytest.approx(
        KRIPPENDORFF_TENTATIVE_FLOOR, rel=1e-2
    )


def test_inter_voter_agreement_no_decisive_returns_threshold() -> None:
    """All ties → no decisive signal → neutral fallback at the
    substantial-agreement floor so ``compute_admire_aggregate``'s
    dampener treats it as the minimum substantial-agreement reading
    (not 0.0 → would falsely flag drift)."""
    assert derive_inter_voter_agreement(wins=0, losses=0, ties=3) == pytest.approx(
        KRIPPENDORFF_TENTATIVE_FLOOR
    )


def test_inter_voter_agreement_even_split_returns_half() -> None:
    """2 wins / 2 losses, no ties → majority_share 0.5 × decisive_share
    1.0 = 0.5 (lower bound for a binary decision when all voters were
    decisive)."""
    assert derive_inter_voter_agreement(wins=2, losses=2, ties=0) == pytest.approx(0.5)


def test_inter_voter_agreement_low_decisive_share_penalized() -> None:
    """Codex MCP §3 — pre-fix wins=1, losses=0, ties=2 returned 1.0
    (a single-voter unanimity looked as strong as 3-of-3). Two-factor
    formula now penalizes: majority_share 1.0 × decisive_share 1/3 =
    ~0.333. The pin keeps the decisive-share penalty alive across
    future refactors."""
    agreement = derive_inter_voter_agreement(wins=1, losses=0, ties=2)
    assert agreement == pytest.approx(1.0 / 3.0)
    # Symmetric for losses-side single decisive vote.
    agreement_losses = derive_inter_voter_agreement(wins=0, losses=1, ties=2)
    assert agreement_losses == pytest.approx(1.0 / 3.0)


def test_inter_voter_agreement_partial_panel_unanimity_still_below_full_panel() -> None:
    """End-to-end ordering invariant — for any panel with ties,
    agreement must be strictly less than full-panel unanimity. Catches
    a future refactor that drops the decisive-share factor."""
    full_unanimity = derive_inter_voter_agreement(wins=3, losses=0, ties=0)
    partial_unanimity = derive_inter_voter_agreement(wins=2, losses=0, ties=1)
    single_unanimity = derive_inter_voter_agreement(wins=1, losses=0, ties=2)
    assert full_unanimity > partial_unanimity > single_unanimity
    assert full_unanimity == pytest.approx(1.0)
    assert partial_unanimity == pytest.approx(2 / 3)
    assert single_unanimity == pytest.approx(1 / 3)


# ───────────────────────────────────────────────────────────────────────────
# 3. admire_means_from_eval_result — converter contract
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class _StubEvalResult:
    """Mirrors MutationEvalResult shape so tests don't need seed-gen
    import (handoff is data-only, no module dependency)."""

    wins: int
    losses: int
    ties: int
    pairwise_win_rate: float


def test_admire_means_from_eval_result_unanimous_after() -> None:
    """3 wins for after → pairwise_win_rate=1.0 + calibration=1.0."""
    result = _StubEvalResult(wins=3, losses=0, ties=0, pairwise_win_rate=1.0)
    admire = admire_means_from_eval_result(result)
    assert admire == {
        "pairwise_win_rate": 1.0,
        "human_calibration_corr": 1.0,
    }


def test_admire_means_from_eval_result_majority() -> None:
    """2-of-3 majority → win_rate=2/3 + calibration=2/3 (tentative
    floor). This is the canonical "substantial agreement" reading."""
    result = _StubEvalResult(wins=2, losses=1, ties=0, pairwise_win_rate=2 / 3)
    admire = admire_means_from_eval_result(result)
    assert admire["pairwise_win_rate"] == pytest.approx(2 / 3)
    assert admire["human_calibration_corr"] == pytest.approx(2 / 3, rel=1e-2)


def test_admire_means_from_eval_result_schema_parity() -> None:
    """Field-name parity — every key in the returned dict matches a
    key in ``ADMIRE_DIM_WEIGHTS``. Catches a future rename on either
    side that would silently desync the handoff."""
    result = _StubEvalResult(wins=1, losses=1, ties=1, pairwise_win_rate=0.5)
    admire = admire_means_from_eval_result(result)
    for key in admire:
        assert key in ADMIRE_DIM_WEIGHTS, (
            f"admire_means key {key!r} not in ADMIRE_DIM_WEIGHTS — "
            "field-name handoff contract drift"
        )
    for key in ADMIRE_DIM_WEIGHTS:
        assert key in admire, (
            f"ADMIRE_DIM_WEIGHTS field {key!r} not in admire_means output — "
            "converter is missing a required field"
        )


def test_admire_means_from_eval_result_is_validatable() -> None:
    """Output passes the existing ``validate_admire_schema`` — i.e.
    the converter never emits invalid keys/values."""
    result = _StubEvalResult(wins=2, losses=1, ties=0, pairwise_win_rate=2 / 3)
    admire = admire_means_from_eval_result(result)
    assert validate_admire_schema(admire) is True


def test_admire_means_from_eval_result_flows_into_compute_admire_aggregate() -> None:
    """End-to-end — converter output is consumable by
    ``compute_admire_aggregate`` with the dampener wired correctly."""
    result = _StubEvalResult(wins=3, losses=0, ties=0, pairwise_win_rate=1.0)
    admire = admire_means_from_eval_result(result)
    aggregate = compute_admire_aggregate(admire)
    # Unanimous → both fields = 1.0 → aggregate = 0.70 * 1.0 * 1.0 + 0.30 * 1.0 = 1.0
    assert aggregate == pytest.approx(1.0)


# ───────────────────────────────────────────────────────────────────────────
# 4. Cross-module handoff invariant
# ───────────────────────────────────────────────────────────────────────────


def test_mutation_eval_result_pairwise_win_rate_field_name_matches() -> None:
    """Cross-module pin (mirror of seed-gen's
    ``test_pairwise_win_rate_field_name_matches_autoresearch_admire``):
    the seed-gen ``MutationEvalResult`` exports
    ``pairwise_win_rate`` and the autoresearch ``ADMIRE_DIM_WEIGHTS``
    schema expects the same key. Static-import inspection without a
    runtime call so the boundary stays data-only."""
    from plugins.seed_generation.mutation_eval import MutationEvalResult

    # MutationEvalResult is a frozen dataclass; introspect its fields.
    field_names = {f.name for f in MutationEvalResult.__dataclass_fields__.values()}
    assert "pairwise_win_rate" in field_names, (
        "seed-gen MutationEvalResult dropped pairwise_win_rate — autoresearch handoff broken"
    )
    assert "pairwise_win_rate" in ADMIRE_DIM_WEIGHTS, (
        "autoresearch ADMIRE_DIM_WEIGHTS lost pairwise_win_rate key — seed-gen handoff broken"
    )

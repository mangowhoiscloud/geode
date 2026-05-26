"""PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27).

Coverage:

- ``format_mutator_feedback_block`` — empty iterables / credit-only /
  matrix-only / combined output / cap at top-N dims per kind.
- ``check_repetitive_mutation`` — distinct kinds skip, distinct sections
  skip, similar new_value crosses threshold, max_similarity reported
  even on no-match.
- ``RepetitiveMutationError`` — subclass of ValueError; carries the
  finding + threshold for telemetry.
- Config knob grounding pin — defaults match the operator dashboard
  ``_WIRE_DEFAULT_LAST`` (20) and difflib-grounded threshold (0.85).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.self_improving_loop.mutator_feedback import (
    RepetitionFinding,
    RepetitiveMutationError,
    check_repetitive_mutation,
    format_mutator_feedback_block,
)

# ---------------------------------------------------------------------------
# Stub records — keep tests independent of pydantic model surface
# ---------------------------------------------------------------------------


@dataclass
class _StubApplyRecord:
    mutation_id: str = ""
    target_kind: str = "prompt"
    target_section: str = ""
    new_value: str = ""
    expected_dim: dict[str, float] = field(default_factory=dict)
    group_advantage: float | None = None
    kind: str = "applied"


@dataclass
class _StubAttributionRecord:
    mutation_id: str = ""
    observed_dim: dict[str, float] = field(default_factory=dict)
    attribution_score: float = 0.0


@dataclass
class _StubMutation:
    target_kind: str = "prompt"
    target_section: str = ""
    new_value: str = ""


# ---------------------------------------------------------------------------
# format_mutator_feedback_block
# ---------------------------------------------------------------------------


def test_feedback_block_empty_inputs_returns_empty_string() -> None:
    assert format_mutator_feedback_block([], []) == ""


def test_feedback_block_renders_per_dim_credit_when_present() -> None:
    applies = [
        _StubApplyRecord(
            mutation_id="m1",
            expected_dim={"safety": 0.5, "helpfulness": 0.5},
            group_advantage=0.4,
        ),
        _StubApplyRecord(
            mutation_id="m2",
            expected_dim={"safety": 1.0},
            group_advantage=-0.2,
        ),
    ]
    block = format_mutator_feedback_block(applies, [])
    assert "Per-dim credit" in block
    # safety received 0.5*(0.5/1.0) + 1.0*(1.0/1.0) of the (signed) advantage:
    # = 0.4 * 0.5 + (-0.2) * 1.0 = 0.2 - 0.2 = 0.0 → won't appear high in rank,
    # but should be referenced.
    assert "safety" in block
    assert "helpfulness" in block


def test_feedback_block_renders_matrix_section_when_attribution_present() -> None:
    applies = [
        _StubApplyRecord(mutation_id="m1", target_kind="prompt", target_section="lead"),
        _StubApplyRecord(mutation_id="m2", target_kind="tool_policy", target_section="bash"),
    ]
    attributions = [
        _StubAttributionRecord(
            mutation_id="m1",
            observed_dim={"safety": 0.6, "helpfulness": 0.3},
            attribution_score=1.0,
        ),
        _StubAttributionRecord(
            mutation_id="m2",
            observed_dim={"broken_tool_use": -0.4},
            attribution_score=1.0,
        ),
    ]
    block = format_mutator_feedback_block(applies, attributions)
    assert "Kind x Dim" in block
    assert "prompt:" in block
    assert "tool_policy:" in block
    assert "broken_tool_use" in block


def test_feedback_block_header_counts_match_inputs() -> None:
    """When there is per-dim signal the header reports the apply count."""
    applies_signal = [
        _StubApplyRecord(mutation_id="m0", expected_dim={"safety": 1.0}, group_advantage=0.5)
    ]
    block_with_signal = format_mutator_feedback_block(applies_signal, [])
    assert "last 1 apply" in block_with_signal


# ---------------------------------------------------------------------------
# check_repetitive_mutation
# ---------------------------------------------------------------------------


def test_dedup_distinct_kinds_never_match() -> None:
    """Different ``target_kind`` ⇒ signature prefix differs ⇒ ratio low."""
    mutation = _StubMutation(target_kind="prompt", target_section="lead", new_value="Hello world.")
    recent = [
        _StubApplyRecord(
            target_kind="tool_policy",
            target_section="lead",
            new_value="Hello world.",
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert not finding.is_repetitive
    # Signatures differ only in 6-char prefix vs 11-char prefix; with the
    # identical 22-char payload remainder ratio is still high but below 1.0.
    assert 0.0 < finding.max_similarity < 1.0


def test_dedup_exact_duplicate_triggers() -> None:
    mutation = _StubMutation(
        target_kind="prompt",
        target_section="lead",
        new_value="Be concise and explicit.",
    )
    recent = [
        _StubApplyRecord(
            target_kind="prompt",
            target_section="lead",
            new_value="Be concise and explicit.",
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert finding.is_repetitive
    assert finding.max_similarity == 1.0
    assert finding.matched_mutation_id == "prior-1"


def test_dedup_cosmetic_edit_above_threshold_triggers() -> None:
    """Tiny phrasing tweak on the same section ⇒ ratio ≥ 0.85."""
    mutation = _StubMutation(
        target_kind="prompt",
        target_section="lead",
        new_value="Be concise and very explicit.",
    )
    recent = [
        _StubApplyRecord(
            target_kind="prompt",
            target_section="lead",
            new_value="Be concise and explicit.",
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert finding.is_repetitive
    assert finding.max_similarity >= 0.85


def test_dedup_genuine_rewrite_below_threshold_allowed() -> None:
    mutation = _StubMutation(
        target_kind="prompt",
        target_section="lead",
        new_value=(
            "Take three turns to outline the plan, gather evidence with "
            "explicit tool calls, then synthesize."
        ),
    )
    recent = [
        _StubApplyRecord(
            target_kind="prompt",
            target_section="lead",
            new_value="Be concise and explicit.",
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert not finding.is_repetitive
    assert finding.max_similarity < 0.85


def test_dedup_empty_recent_returns_safe_finding() -> None:
    mutation = _StubMutation(target_kind="prompt", target_section="lead", new_value="anything")
    finding = check_repetitive_mutation(mutation, [], threshold=0.85)
    assert not finding.is_repetitive
    assert finding.max_similarity == 0.0
    assert finding.matched_mutation_id is None


def test_dedup_records_best_match_even_when_no_trigger() -> None:
    mutation = _StubMutation(target_kind="prompt", target_section="lead", new_value="Foo")
    recent = [
        _StubApplyRecord(
            target_kind="prompt",
            target_section="lead",
            new_value="Foo bar baz quux",
            mutation_id="closer",
        ),
        _StubApplyRecord(
            target_kind="prompt",
            target_section="lead",
            new_value="Wildly different content of much greater length",
            mutation_id="farther",
        ),
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.99)
    assert not finding.is_repetitive
    assert finding.matched_mutation_id == "closer"


# ---------------------------------------------------------------------------
# RepetitiveMutationError
# ---------------------------------------------------------------------------


def test_repetitive_mutation_error_subclasses_value_error() -> None:
    finding = RepetitionFinding(
        is_repetitive=True,
        max_similarity=0.9,
        matched_mutation_id="prior-1",
        matched_target_section="lead",
    )
    err = RepetitiveMutationError(finding, threshold=0.85)
    assert isinstance(err, ValueError)
    assert err.finding is finding
    assert err.threshold == 0.85
    assert "0.900" in str(err)
    assert "prior-1" in str(err)


# ---------------------------------------------------------------------------
# Grounded constants pin
# ---------------------------------------------------------------------------


def test_dedup_threshold_default_matches_difflib_grounding() -> None:
    """Default ``mutator_dedup_threshold`` (0.85) sits well above
    ``difflib.get_close_matches`` cutoff (0.6 "close match" band)."""
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.mutator_dedup_threshold == 0.85


def test_feedback_window_default_matches_wire_default_last() -> None:
    """Default ``mutator_feedback_window`` (20) matches the operator
    dashboard convention so the mutator sees the same recent slice."""
    from core.cli.commands.self_improving import _WIRE_DEFAULT_LAST
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.mutator_feedback_window == _WIRE_DEFAULT_LAST
    assert cfg.mutator_dedup_window == _WIRE_DEFAULT_LAST

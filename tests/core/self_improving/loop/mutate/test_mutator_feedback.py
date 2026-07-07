"""PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27).

Coverage:

- ``format_mutator_feedback_block`` — empty iterables / matrix output /
  header count / cap at top-N dims per kind.
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

from core.self_improving.loop.mutate.mutator_feedback import (
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


def test_feedback_block_excludes_retired_hyperparam_kind() -> None:
    """PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — a historical ``hyperparam``
    apply row must NOT be surfaced in the feedback block. The block tells the
    mutator to "favour kinds that have moved the regression target_dim
    historically"; if a retired kind appeared there the mutator would propose
    it and the cycle would SKIP at ``parse_mutation`` rejection. Active kinds
    in the same matrix are still surfaced."""
    applies = [
        _StubApplyRecord(
            mutation_id="m_hp",
            target_kind="hyperparam",
            target_section="reflection_depth",
        ),
        _StubApplyRecord(mutation_id="m_p", target_kind="prompt", target_section="lead"),
    ]
    attributions = [
        _StubAttributionRecord(
            mutation_id="m_hp",
            observed_dim={"redundant_tool_invocation": -0.5},
            attribution_score=1.0,
        ),
        _StubAttributionRecord(
            mutation_id="m_p",
            observed_dim={"safety": 0.4},
            attribution_score=1.0,
        ),
    ]
    block = format_mutator_feedback_block(applies, attributions)
    assert "prompt:" in block, "active kind should still be surfaced"
    assert "hyperparam:" not in block, "retired hyperparam kind must be filtered out"


def test_feedback_block_header_counts_match_inputs() -> None:
    """When there is matrix signal the header reports the apply count."""
    applies_signal = [
        _StubApplyRecord(mutation_id="m0", target_kind="prompt", target_section="lead")
    ]
    attributions_signal = [
        _StubAttributionRecord(
            mutation_id="m0",
            observed_dim={"safety": 0.5},
            attribution_score=1.0,
        )
    ]
    block_with_signal = format_mutator_feedback_block(applies_signal, attributions_signal)
    assert "last 1 apply" in block_with_signal


# ---------------------------------------------------------------------------
# check_repetitive_mutation
# ---------------------------------------------------------------------------


def test_dedup_distinct_kinds_never_match() -> None:
    """Different ``target_kind`` ⇒ kind gate skips the comparison
    entirely; ``new_value`` similarity is never measured."""
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
    # Codex MCP review (PR-MUTATOR-DEDUP-GUARD, 2026-05-27): the
    # kind+section gate skips the SequenceMatcher call entirely when
    # kinds differ, so best_ratio stays at 0.0 even when ``new_value``
    # is identical.
    assert finding.max_similarity == 0.0


def test_dedup_distinct_sections_skipped_entirely() -> None:
    """Same kind, different ``target_section`` ⇒ skipped (not a repeat)."""
    mutation = _StubMutation(
        target_kind="prompt", target_section="lead", new_value="Foo bar baz quux"
    )
    recent = [
        _StubApplyRecord(
            target_kind="prompt",
            target_section="closing",
            new_value="Foo bar baz quux",
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert not finding.is_repetitive
    assert finding.max_similarity == 0.0


def test_dedup_long_identical_value_across_kinds_does_not_trigger() -> None:
    """Codex MCP regression: with a 500-char identical ``new_value``,
    the pre-fix joined-signature ratio would exceed 0.85 even across
    different kinds. The kind gate must prevent that — long identical
    payloads on different kinds are NOT repetitive."""
    long_value = "lorem ipsum dolor sit amet " * 20  # ~540 chars
    mutation = _StubMutation(target_kind="prompt", target_section="lead", new_value=long_value)
    recent = [
        _StubApplyRecord(
            target_kind="tool_policy",
            target_section="lead",
            new_value=long_value,
            mutation_id="prior-1",
        )
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert not finding.is_repetitive
    assert finding.max_similarity == 0.0


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


# ---------------------------------------------------------------------------
# PR-PROMOTE-RATE-BUNDLE 2026-05-29 — Option C. Axis-family dedup
# ---------------------------------------------------------------------------


def test_axis_family_dedup_triggers_after_three_same_section() -> None:
    """Three prior applies on the same (kind, section) → axis-family
    exhausted; any further value on that axis rejects regardless of
    new_value similarity.

    Origin: cy14-22 batch observed mutator sweeping the same axis
    (max_turns / reflection_depth) for 8 consecutive cycles. Value-only
    dedup (the legacy gate) caught exact reruns but allowed value sweep.
    Family-level gate forces cross-axis exploration after N=3 attempts.
    """
    mutation = _StubMutation(
        target_kind="hyperparam",
        target_section="reflection_depth",
        new_value="6",
    )
    recent = [
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="reflection_depth",
            new_value="1",
            mutation_id="cy18",
        ),
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="reflection_depth",
            new_value="4",
            mutation_id="cy19",
        ),
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="reflection_depth",
            new_value="2",
            mutation_id="cy20",
        ),
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    assert finding.is_repetitive
    assert finding.max_similarity == 1.0
    assert finding.matched_mutation_id is not None
    assert "axis_family_exhausted" in finding.matched_mutation_id


def test_axis_family_dedup_two_same_section_still_allowed() -> None:
    """Two prior applies on same axis → still under the limit; allowed."""
    mutation = _StubMutation(
        target_kind="hyperparam",
        target_section="max_turns",
        new_value="6",
    )
    recent = [
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="max_turns",
            new_value="3",
            mutation_id="cy14",
        ),
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="max_turns",
            new_value="4",
            mutation_id="cy15",
        ),
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    # 2 < 3 limit + new_value "6" ≠ "3" or "4" → not repetitive.
    assert not finding.is_repetitive


def test_axis_family_dedup_counts_only_same_kind_and_section() -> None:
    """Different (kind, section) prior applies don't contribute to the
    same-axis count. cy18 reflection_depth + cy14 max_turns + cy15
    max_turns → reflection_depth axis only has 1 prior."""
    mutation = _StubMutation(
        target_kind="hyperparam",
        target_section="reflection_depth",
        new_value="6",
    )
    recent = [
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="reflection_depth",
            new_value="1",
            mutation_id="cy18",
        ),
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="max_turns",
            new_value="3",
            mutation_id="cy14",
        ),
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="max_turns",
            new_value="4",
            mutation_id="cy15",
        ),
        _StubApplyRecord(
            target_kind="prompt",
            target_section="role",
            new_value="Agent: GEODE.",
            mutation_id="cy11",
        ),
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    # reflection_depth count = 1, max_turns count = 2 (different axis),
    # role count = 0 (different axis) → mutation's axis at 1 < limit.
    assert not finding.is_repetitive


def test_axis_family_dedup_cross_kind_unaffected() -> None:
    """Family count is per (kind, section). Different kind even with
    same section name doesn't add to the count."""
    mutation = _StubMutation(
        target_kind="tool_descriptions",
        target_section="reflection_depth",  # quirky reuse for the test
        new_value="anything",
    )
    recent = [
        _StubApplyRecord(
            target_kind="hyperparam",
            target_section="reflection_depth",
            new_value=str(v),
            mutation_id=f"cy{18 + i}",
        )
        for i, v in enumerate([1, 4, 2])
    ]
    finding = check_repetitive_mutation(mutation, recent, threshold=0.85)
    # All 3 priors are hyperparam × reflection_depth; mutation is
    # tool_descriptions × reflection_depth — different kind → count = 0.
    assert not finding.is_repetitive


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
    from core.config.self_improving import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.mutator_dedup_threshold == 0.85


def test_feedback_window_default_matches_wire_default_last() -> None:
    """Default ``mutator_feedback_window`` (20) matches the operator
    dashboard convention so the mutator sees the same recent slice."""
    from core.cli.commands.self_improving import _WIRE_DEFAULT_LAST
    from core.config.self_improving import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.mutator_feedback_window == _WIRE_DEFAULT_LAST
    assert cfg.mutator_dedup_window == _WIRE_DEFAULT_LAST

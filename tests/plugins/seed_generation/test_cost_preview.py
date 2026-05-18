"""Tests for ``plugins.seed_generation.cost_preview``."""

from __future__ import annotations

from plugins.seed_generation.cost_preview import (
    DEFAULT_CANDIDATE_COUNT,
    CostEstimate,
    CostRow,
    estimate_cost,
    format_cost_summary,
)
from plugins.seed_generation.picker import PickerResult, RoleBinding, VoterBinding


def _make_picker_result(*, voter_source: str = "api_key") -> PickerResult:
    bindings: dict[str, RoleBinding] = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "critic": RoleBinding(
            role="critic",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "proximity": RoleBinding(
            role="proximity",
            model="text-embedding-3-small",
            family="openai",
            source="api_key",
            kind="embedding",
        ),
        "pilot": RoleBinding(
            role="pilot",
            model="claude-haiku-4-5",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "ranker": RoleBinding(
            role="ranker",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "evolver": RoleBinding(
            role="evolver",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "meta_reviewer": RoleBinding(
            role="meta_reviewer",
            model="claude-opus-4-7",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source=voter_source),
        VoterBinding(model="gpt-5.5", family="openai", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", family="anthropic", source="api_key"),
    ]
    return PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )


def test_estimate_cost_returns_per_role_row_for_each_binding() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=15)
    assert {r.role for r in est.rows} == set(pr.bindings.keys())


def test_estimate_cost_default_candidate_count() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr)
    assert est.candidate_count == DEFAULT_CANDIDATE_COUNT


def test_estimate_cost_match_count_follows_n_log_n() -> None:
    """For 15 candidates, ceil(15 * log2(15)) ≈ 59, well below 105 = C(15,2)."""
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=15)
    assert 0 < est.match_count <= 60


def test_estimate_cost_voter_count_reflects_panel_size() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=10)
    assert est.voter_count == 3


def test_estimate_cost_ranker_calls_scale_with_voters_x_matches() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=10)
    ranker_row = next(r for r in est.rows if r.role == "ranker")
    assert ranker_row.calls == est.match_count * est.voter_count


def test_estimate_cost_generator_one_call_per_candidate() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=8)
    gen_row = next(r for r in est.rows if r.role == "generator")
    assert gen_row.calls == 8


def test_estimate_cost_pilot_one_call_per_candidate() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=8)
    pilot_row = next(r for r in est.rows if r.role == "pilot")
    assert pilot_row.calls == 8


def test_estimate_cost_meta_reviewer_one_call_per_run() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=8)
    mr_row = next(r for r in est.rows if r.role == "meta_reviewer")
    assert mr_row.calls == 1


def test_estimate_cost_total_is_sum_of_rows() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr)
    total = sum(r.est_usd for r in est.rows)
    assert abs(est.total_usd - total) < 1e-9


def test_estimate_cost_subscription_vs_payg_split() -> None:
    pr = _make_picker_result()
    bindings = dict(pr.bindings)
    bindings["generator"] = RoleBinding(
        role="generator",
        model="claude-sonnet-4-6",
        family="anthropic",
        source="claude-cli",
        kind="completion",
    )
    pr = PickerResult(
        bindings=bindings,
        voters=pr.voters,
        diversity_families=pr.diversity_families,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    est = estimate_cost(pr, candidate_count=15)
    assert est.subscription_usd > 0
    assert est.payg_usd > 0
    assert abs(est.subscription_usd + est.payg_usd - est.total_usd) < 1e-9


def test_estimate_cost_proximity_zero_or_negligible_for_embedding() -> None:
    """Embedding pricing not in MODEL_PRICING → 0 estimate (acceptable)."""
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=15)
    prox_row = next(r for r in est.rows if r.role == "proximity")
    # Embedding model not in completion pricing catalogue → 0.0
    assert prox_row.est_usd == 0.0


def test_estimate_cost_explicit_match_count_override() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=15, match_count=10)
    assert est.match_count == 10
    ranker_row = next(r for r in est.rows if r.role == "ranker")
    assert ranker_row.calls == 10 * 3


def test_format_cost_summary_returns_multiline_string() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=5)
    summary = format_cost_summary(est)
    assert "seed-generation cost preview" in summary
    assert "generator" in summary
    assert "total" in summary


def test_format_cost_summary_marks_subscription_rows() -> None:
    pr = _make_picker_result()
    bindings = dict(pr.bindings)
    bindings["generator"] = RoleBinding(
        role="generator",
        model="claude-sonnet-4-6",
        family="anthropic",
        source="claude-cli",
        kind="completion",
    )
    pr = PickerResult(
        bindings=bindings,
        voters=pr.voters,
        diversity_families=pr.diversity_families,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    est = estimate_cost(pr, candidate_count=5)
    summary = format_cost_summary(est)
    assert "subscription-backed" in summary


def test_estimate_cost_row_carries_binding_metadata() -> None:
    pr = _make_picker_result()
    est = estimate_cost(pr, candidate_count=5)
    for row in est.rows:
        assert row.model
        assert row.family in {"anthropic", "openai", "zhipuai"}
        assert row.source
        assert row.calls >= 0
        assert row.est_usd >= 0


def test_estimate_cost_unknown_model_logs_and_zeros() -> None:
    """Unknown model → 0.0 cost, not crash."""
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="mystery-x9-unknown",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", family="openai", source="api_key"),
    ]
    pr = PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )
    est = estimate_cost(pr, candidate_count=5)
    gen_row = next(r for r in est.rows if r.role == "generator")
    assert gen_row.est_usd == 0.0


def test_cost_row_immutable() -> None:
    import dataclasses

    import pytest

    row = CostRow(
        role="x",
        model="y",
        family="z",
        source="w",
        calls=0,
        est_usd=0.0,
        subscription_backed=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.calls = 5  # type: ignore[misc]


def test_cost_estimate_immutable() -> None:
    import dataclasses

    import pytest

    est = CostEstimate(
        rows=[],
        total_usd=0.0,
        subscription_usd=0.0,
        payg_usd=0.0,
        candidate_count=0,
        match_count=0,
        voter_count=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        est.total_usd = 1.0  # type: ignore[misc]

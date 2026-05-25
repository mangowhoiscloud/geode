"""PR-AR-L4a (2026-05-26) — ``ux_means`` 4-reader collector invariants.

Pre-PR-AR-L4a ``collect_ux_means_from_sources`` was a hardcoded
``return None`` placeholder — ADR-012 S1 shipped the schema + math
but the S1b collector wiring never landed. The downstream
``compute_fitness`` callers never got a non-``None`` ``ux_means`` dict,
so the entire ux fitness axis was dormant in production.

PR-AR-L4a wires the 4 readers against the single SoT
``autoresearch/state/mutations.jsonl`` (already W4-validated by
``ApplyRecord`` / ``AttributionRecord``):

- ``read_mutation_success_rate`` — count(attribution_score > 0) /
  count(attribution rows with attribution_score)
- ``read_token_cost`` — Σ(in_tok × price.input + out_tok × price.output)
  per ``cost_model`` from ``core.llm.token_tracker.MODEL_PRICING``
- ``read_revert_ratio`` — count(fitness_delta < 0) /
  count(rows with fitness_delta)
- ``read_latency`` — mean(cost_elapsed_seconds) across apply rows

The 4 ux fields share the same ledger window, so they're coherent —
no risk of one metric reading day-old data while another reads
fresh signal.

This file pins each reader's graceful-no-op contract + the wired
end-to-end ``collect_ux_means_from_sources`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from autoresearch.ux_means import (
    DEFAULT_UX_LATENCY_BUDGET_S,
    DEFAULT_UX_TOKEN_BUDGET_USD,
    UX_DIM_WEIGHTS,
    collect_ux_means_from_sources,
    read_latency,
    read_mutation_success_rate,
    read_revert_ratio,
    read_token_cost,
)

# ───────────────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Test helper — write the rows back-to-back as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def apply_rows() -> list[dict]:
    """Two apply rows with priced model + non-zero cost / elapsed."""
    return [
        {
            "ts": 1.0,
            "kind": "applied",
            "mutation_id": "m-1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "x",
            "new_value": "y",
            "cost_input_tokens": 1000,
            "cost_output_tokens": 500,
            "cost_elapsed_seconds": 60.0,
            "cost_model": "claude-opus-4-7",
        },
        {
            "ts": 2.0,
            "kind": "applied",
            "mutation_id": "m-2",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "y",
            "new_value": "z",
            "cost_input_tokens": 2000,
            "cost_output_tokens": 1000,
            "cost_elapsed_seconds": 120.0,
            "cost_model": "claude-opus-4-7",
        },
    ]


@pytest.fixture
def attribution_rows() -> list[dict]:
    """Three attribution rows — 2 success, 1 revert (negative fitness_delta)."""
    return [
        {
            "ts": 1.5,
            "kind": "attribution",
            "mutation_id": "m-1",
            "attribution_score": 0.5,
            "fitness_delta": 0.05,
        },
        {
            "ts": 2.5,
            "kind": "attribution",
            "mutation_id": "m-2",
            "attribution_score": -0.3,
            "fitness_delta": -0.02,
        },
        {
            "ts": 3.5,
            "kind": "attribution",
            "mutation_id": "m-3",
            "attribution_score": 0.2,
            "fitness_delta": 0.01,
        },
    ]


# ───────────────────────────────────────────────────────────────────────────
# 1. read_mutation_success_rate
# ───────────────────────────────────────────────────────────────────────────


def test_success_rate_returns_none_when_no_attribution_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    log_path.write_text("", encoding="utf-8")
    assert read_mutation_success_rate(log_path=log_path) is None


def test_success_rate_fraction_of_positive_attribution_scores(
    tmp_path: Path, attribution_rows: list[dict]
) -> None:
    """3 attribution rows — 2 positive (m-1, m-3) + 1 negative (m-2)
    → success_rate = 2/3."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, attribution_rows)
    rate = read_mutation_success_rate(log_path=log_path)
    assert rate == pytest.approx(2 / 3)


# ───────────────────────────────────────────────────────────────────────────
# 2. read_token_cost
# ───────────────────────────────────────────────────────────────────────────


def test_token_cost_returns_none_when_no_apply_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    log_path.write_text("", encoding="utf-8")
    assert read_token_cost(log_path=log_path) is None


def test_token_cost_returns_none_when_model_unpriced(tmp_path: Path) -> None:
    """Unknown ``cost_model`` → no priced row found → ``None``."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "ts": 1.0,
                "kind": "applied",
                "mutation_id": "m-1",
                "target_kind": "prompt",
                "target_section": "role",
                "previous_value": "x",
                "new_value": "y",
                "cost_input_tokens": 1000,
                "cost_output_tokens": 500,
                "cost_model": "future-unreleased-model",
            }
        ],
    )
    assert read_token_cost(log_path=log_path) is None


def test_token_cost_sums_priced_rows(tmp_path: Path, apply_rows: list[dict]) -> None:
    """Both apply rows priced as claude-opus-4-7 — verify cost > 0 +
    matches the manual sum via ``MODEL_PRICING``."""
    from core.llm.token_tracker import MODEL_PRICING

    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, apply_rows)
    cost = read_token_cost(log_path=log_path)
    assert cost is not None
    price = MODEL_PRICING["claude-opus-4-7"]
    expected = (1000 + 2000) * price.input + (500 + 1000) * price.output
    assert cost == pytest.approx(expected)
    assert cost > 0


# ───────────────────────────────────────────────────────────────────────────
# 3. read_revert_ratio
# ───────────────────────────────────────────────────────────────────────────


def test_revert_ratio_returns_none_when_no_fitness_delta(tmp_path: Path) -> None:
    """Attribution rows missing ``fitness_delta`` → ``None``."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log_path,
        [{"ts": 1.0, "kind": "attribution", "mutation_id": "m-1"}],
    )
    assert read_revert_ratio(log_path=log_path) is None


def test_revert_ratio_fraction_of_negative_deltas(
    tmp_path: Path, attribution_rows: list[dict]
) -> None:
    """3 rows — 1 negative (m-2) → revert_ratio = 1/3."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, attribution_rows)
    ratio = read_revert_ratio(log_path=log_path)
    assert ratio == pytest.approx(1 / 3)


# ───────────────────────────────────────────────────────────────────────────
# 4. read_latency
# ───────────────────────────────────────────────────────────────────────────


def test_latency_returns_none_when_no_elapsed(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "ts": 1.0,
                "kind": "applied",
                "mutation_id": "m-1",
                "target_kind": "prompt",
                "target_section": "role",
                "previous_value": "x",
                "new_value": "y",
            }
        ],
    )
    assert read_latency(log_path=log_path) is None


def test_latency_mean_of_apply_elapsed(tmp_path: Path, apply_rows: list[dict]) -> None:
    """2 apply rows with 60s + 120s → mean 90s."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, apply_rows)
    assert read_latency(log_path=log_path) == pytest.approx(90.0)


# ───────────────────────────────────────────────────────────────────────────
# 5. collect_ux_means_from_sources — end-to-end
# ───────────────────────────────────────────────────────────────────────────


def test_collect_assembles_4_field_dict_when_data_present(
    tmp_path: Path, apply_rows: list[dict], attribution_rows: list[dict]
) -> None:
    """Wired path: ledger has both apply + attribution rows → collector
    returns the full 4-field dict shaped per ``UX_DIM_WEIGHTS``."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, apply_rows + attribution_rows)
    result = collect_ux_means_from_sources(log_path=log_path)
    assert result is not None
    assert set(result) == set(UX_DIM_WEIGHTS)
    # success_rate = 2/3 (from attribution_rows fixture)
    assert result["success_rate"] == pytest.approx(2 / 3)
    # Every field is normalized to 0-1.
    for field, value in result.items():
        assert 0.0 <= value <= 1.0, f"{field}={value} outside [0,1]"


def test_collect_returns_none_when_attribution_absent(
    tmp_path: Path, apply_rows: list[dict]
) -> None:
    """Apply rows alone (no attribution) → success_rate is None →
    collector returns None. compute_fitness falls back to dim-only."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, apply_rows)
    assert collect_ux_means_from_sources(log_path=log_path) is None


def test_collect_uses_default_budget_values(
    tmp_path: Path, apply_rows: list[dict], attribution_rows: list[dict]
) -> None:
    """Default budget = aggressive (5.0 USD / 1800s) per PR-AR-L4a operator
    decision. Apply rows total ~$0.05 (3K + 1.5K tokens at claude-opus-4-7)
    → token_cost_norm close to 1.0. Latency 90s vs 1800s budget
    → latency_norm ≈ 1 - 90/1800 = 0.95."""
    log_path = tmp_path / "mutations.jsonl"
    _write_jsonl(log_path, apply_rows + attribution_rows)
    result = collect_ux_means_from_sources(log_path=log_path)
    assert result is not None
    # Latency = 90s / 1800s budget → 1 - 0.05 = 0.95
    assert result["latency_norm"] == pytest.approx(1 - 90 / 1800)
    # Token cost — 3000 input × $5/MTok + 1500 output × $25/MTok = $0.0525.
    # $0.0525 / $5 budget = 0.0105 → norm = 1 - 0.0105 = 0.9895.
    assert result["token_cost_norm"] == pytest.approx(1 - 0.0525 / 5.0, abs=1e-4)


def test_collect_window_limits_to_recent_tail(
    tmp_path: Path, apply_rows: list[dict], attribution_rows: list[dict]
) -> None:
    """``window=N`` keeps only the most recent N rows. Verify by
    constructing a ledger where old rows would skew the metric."""
    log_path = tmp_path / "mutations.jsonl"
    # Old (negative-only attribution) followed by new positive rows.
    old_negative = [
        {
            "ts": 0.1 + i * 0.01,
            "kind": "attribution",
            "mutation_id": f"old-{i}",
            "attribution_score": -1.0,
            "fitness_delta": -0.1,
        }
        for i in range(100)
    ]
    _write_jsonl(log_path, old_negative + apply_rows + attribution_rows)
    # Without window: success_rate dominated by old negatives.
    full = read_mutation_success_rate(log_path=log_path)
    assert full is not None
    assert full < 0.1
    # With window=3 (last 3 rows = the 3 fixture attribution rows): 2/3.
    windowed = read_mutation_success_rate(log_path=log_path, window=3)
    assert windowed == pytest.approx(2 / 3)


def test_default_budgets_are_aggressive_per_operator_decision() -> None:
    """PR-AR-L4a operator decision: aggressive budgets (5.0 USD / 1800s).
    A future PR adjusting either default surfaces here for explicit
    review (matching the Krippendorff α / fitness floor invariant
    pattern from PR-L7 / PR-L8)."""
    assert pytest.approx(5.0) == DEFAULT_UX_TOKEN_BUDGET_USD
    assert pytest.approx(1800.0) == DEFAULT_UX_LATENCY_BUDGET_S

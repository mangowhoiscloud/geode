"""PR-5 C-4 — causal attribution invariants.

Pins the extended ``Mutation`` schema (mutation_id / expected_dim /
rollback_condition), the ``parse_mutation`` graceful-fallback
behaviour, and the attribution math + audit-log append in
``core/self_improving/loop/observe/attribution.py``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from core.self_improving.loop.mutate.runner import Mutation, parse_mutation
from core.self_improving.loop.observe import attribution
from core.self_improving.loop.observe.attribution import (
    _attribution_score,
    _ci95,
    _dim_delta,
    append_attribution_log,
    compute_attribution,
    write_attribution,
)
from plugins.seed_generation.baseline_reader import BaselineSnapshot

# ---------------------------------------------------------------------------
# Mutation schema extension
# ---------------------------------------------------------------------------


def test_mutation_default_mutation_id_is_unique() -> None:
    m1 = Mutation(target_section="a", new_value="x", rationale="r")
    m2 = Mutation(target_section="a", new_value="x", rationale="r")
    assert m1.mutation_id and m2.mutation_id
    assert m1.mutation_id != m2.mutation_id


def test_mutation_default_expected_dim_is_empty() -> None:
    m = Mutation(target_section="a", new_value="x", rationale="r")
    assert m.expected_dim == {}
    assert m.rollback_condition == ""


def test_mutation_default_expected_dim_is_per_instance() -> None:
    """Defensive — ``default_factory=dict`` must NOT share state across
    instances. Mutating one mutation's expected_dim must not leak."""
    m1 = Mutation(target_section="a", new_value="x", rationale="r")
    m1.expected_dim["safety"] = 0.3
    m2 = Mutation(target_section="a", new_value="x", rationale="r")
    assert m2.expected_dim == {}


def test_mutation_to_audit_row_carries_new_fields() -> None:
    m = Mutation(
        target_section="sec",
        new_value="val",
        rationale="ration",
        target_dim="safety",
        mutation_id="m-123",
        expected_dim={"safety": 0.3, "helpfulness": -0.05},
        rollback_condition="any dim drops > 0.5",
    )
    row = m.to_audit_row(previous_value="prev")
    assert row["kind"] == "applied"
    assert row["mutation_id"] == "m-123"
    assert row["expected_dim"] == {"safety": 0.3, "helpfulness": -0.05}
    assert row["rollback_condition"] == "any dim drops > 0.5"


def test_mutation_to_audit_row_expected_dim_is_copy() -> None:
    """Audit row must be a snapshot — mutating the source Mutation
    after writing the row must not change the row."""
    m = Mutation(
        target_section="sec",
        new_value="val",
        rationale="r",
        expected_dim={"safety": 0.3},
    )
    row = m.to_audit_row(previous_value="")
    # The dataclass is frozen so we can't mutate m.expected_dim directly;
    # verify the row dict is a separate object instead.
    assert row["expected_dim"] is not m.expected_dim


# ---------------------------------------------------------------------------
# parse_mutation — graceful extraction of new fields
# ---------------------------------------------------------------------------


def test_parse_mutation_missing_new_fields_falls_back_to_defaults() -> None:
    """LLM responses from older program.md schemas omit the PR-5
    fields. They must still parse — with default mutation_id /
    empty expected_dim / empty rollback_condition."""
    raw = json.dumps(
        {
            "target_section": "sec",
            "new_value": "val",
            "rationale": "r",
            "target_dim": "safety",
        }
    )
    m = parse_mutation(raw)
    assert m.target_section == "sec"
    assert m.mutation_id  # auto-generated
    assert m.expected_dim == {}
    assert m.rollback_condition == ""


def test_parse_mutation_extracts_new_fields() -> None:
    raw = json.dumps(
        {
            "target_section": "sec",
            "new_value": "val",
            "rationale": "r",
            "target_dim": "safety",
            "mutation_id": "supplied-id",
            "expected_dim": {"safety": 0.3, "helpfulness": -0.05},
            "rollback_condition": "any dim drops > 0.5",
        }
    )
    m = parse_mutation(raw)
    assert m.mutation_id == "supplied-id"
    assert m.expected_dim == {"safety": 0.3, "helpfulness": -0.05}
    assert m.rollback_condition == "any dim drops > 0.5"


def test_parse_mutation_drops_non_numeric_expected_dim_entries() -> None:
    """Schema-typed cast — string / null values silently dropped, not
    state-poisoning."""
    raw = json.dumps(
        {
            "target_section": "sec",
            "new_value": "val",
            "rationale": "r",
            "expected_dim": {"safety": "high", "helpfulness": 0.4, "noise": None},
        }
    )
    m = parse_mutation(raw)
    assert m.expected_dim == {"helpfulness": 0.4}


def test_parse_mutation_drops_bool_expected_dim_entries() -> None:
    """Codex MCP review #1 catch — ``bool`` is an ``int`` subclass, so
    ``isinstance(True, int | float)`` returns True. Without an explicit
    bool guard ``{"safety": true}`` would silently coerce to ``1.0``.
    Pin that bool values are rejected like other non-numeric types."""
    raw = json.dumps(
        {
            "target_section": "sec",
            "new_value": "val",
            "rationale": "r",
            "expected_dim": {"safety": True, "helpfulness": False, "novel": 0.4},
        }
    )
    m = parse_mutation(raw)
    assert m.expected_dim == {"novel": 0.4}


def test_parse_mutation_drops_non_dict_expected_dim() -> None:
    raw = json.dumps(
        {
            "target_section": "sec",
            "new_value": "val",
            "rationale": "r",
            "expected_dim": "not-a-dict",
        }
    )
    m = parse_mutation(raw)
    assert m.expected_dim == {}


# ---------------------------------------------------------------------------
# attribution helpers
# ---------------------------------------------------------------------------


def test_dim_delta_signed() -> None:
    before = {"safety": 0.5, "helpfulness": 0.6}
    after = {"safety": 0.8, "helpfulness": 0.55}
    delta = _dim_delta(before, after)
    assert set(delta.keys()) == {"safety", "helpfulness"}
    assert delta["safety"] == pytest.approx(0.3)
    assert delta["helpfulness"] == pytest.approx(-0.05)


def test_dim_delta_skips_missing_dims() -> None:
    """If a dim only appears in one snapshot it's silently dropped."""
    before = {"safety": 0.5}
    after = {"safety": 0.8, "novel_dim": 0.4}
    delta = _dim_delta(before, after)
    assert list(delta.keys()) == ["safety"]
    assert delta["safety"] == pytest.approx(0.3)


def test_ci95_paired_baseline_formula() -> None:
    """ci95[d] = 1.96 * sqrt(sb**2 + sa**2)."""
    before = {"safety": 0.1, "helpfulness": 0.05}
    after = {"safety": 0.05, "helpfulness": 0.05}
    ci = _ci95(before, after, ["safety", "helpfulness"])
    assert ci["safety"] == pytest.approx(1.96 * math.sqrt(0.01 + 0.0025))
    assert ci["helpfulness"] == pytest.approx(1.96 * math.sqrt(0.0025 + 0.0025))


def test_ci95_treats_missing_stderr_as_zero() -> None:
    """Most conservative — narrower CI, more likely to flag
    significance. Operators can interpret as upper-bound certainty."""
    ci = _ci95({"safety": 0.1}, {}, ["safety"])
    assert ci["safety"] == 1.96 * math.sqrt(0.01 + 0.0)


def test_attribution_score_empty_expected_returns_zero() -> None:
    assert _attribution_score({}, {"safety": 0.3}) == 0.0


def test_attribution_score_positive_expected_positive_observed() -> None:
    """Score increases when observed moves in expected direction."""
    score = _attribution_score({"safety": 0.3}, {"safety": 0.2})
    assert score == pytest.approx(0.2)


def test_attribution_score_negative_expected_positive_observed() -> None:
    """If we expected a drop but the observed dim went up, that's
    *against* expectation — contributes negatively."""
    score = _attribution_score({"safety": -0.3}, {"safety": 0.2})
    assert score == pytest.approx(-0.2)


def test_attribution_score_clipped_to_unit_range() -> None:
    """Pathological multi-dim case — score still in [-1, 1]."""
    score = _attribution_score(
        {"a": 0.3, "b": 0.3, "c": 0.3, "d": 0.3, "e": 0.3},
        {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5, "e": 0.5},
    )
    assert score == 1.0


# ---------------------------------------------------------------------------
# compute_attribution — full payload shape
# ---------------------------------------------------------------------------


def _snap(means: dict[str, float], stderr: dict[str, float] | None = None) -> BaselineSnapshot:
    return BaselineSnapshot(dim_means=means, dim_stderr=stderr or {})


def test_compute_attribution_full_payload() -> None:
    before = _snap({"safety": 0.5, "helpfulness": 0.6}, {"safety": 0.05, "helpfulness": 0.05})
    after = _snap({"safety": 0.8, "helpfulness": 0.55}, {"safety": 0.05, "helpfulness": 0.05})
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=before,
        baseline_after=after,
    )
    assert payload["kind"] == "attribution"
    assert payload["mutation_id"] == "m-1"
    assert payload["observed_dim"]["safety"] == pytest.approx(0.3)
    assert payload["observed_dim"]["helpfulness"] == pytest.approx(-0.05)
    # safety: |0.3| > 1.96 * sqrt(0.05^2 + 0.05^2) ≈ 0.139 → significant
    assert payload["significant"]["safety"] is True
    # helpfulness: |-0.05| < 0.139 → not significant
    assert payload["significant"]["helpfulness"] is False
    assert payload["attribution_score"] == pytest.approx(0.3)
    assert payload["missing_baseline"] is False


def test_compute_attribution_missing_before_returns_empty_shape() -> None:
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=None,
        baseline_after=_snap({"safety": 0.8}),
    )
    assert payload["missing_baseline"] is True
    assert payload["observed_dim"] == {}
    assert payload["ci95"] == {}
    assert payload["attribution_score"] == 0.0
    # mutation_id still preserved so the row links back to the apply row
    assert payload["mutation_id"] == "m-1"


def test_compute_attribution_missing_after_returns_empty_shape() -> None:
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=_snap({"safety": 0.5}),
        baseline_after=None,
    )
    assert payload["missing_baseline"] is True
    assert payload["observed_dim"] == {}


# ---------------------------------------------------------------------------
# append_attribution_log + write_attribution
# ---------------------------------------------------------------------------


def test_append_attribution_log_writes_one_row(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    # W4 (2026-05-25) — Pydantic AttributionRecord requires ``ts``;
    # legacy minimal-payload pattern updated to include the timestamp.
    payload = {
        "ts": 1716638400.0,
        "mutation_id": "m-1",
        "kind": "attribution",
        "observed_dim": {"safety": 0.3},
    }
    out = append_attribution_log(payload, log_path=log_path)
    assert out == log_path
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    parsed = json.loads(rows[0])
    assert parsed["mutation_id"] == "m-1"
    assert parsed["kind"] == "attribution"


def test_append_attribution_log_appends_to_existing_file(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    log_path.write_text('{"existing":true}\n', encoding="utf-8")
    append_attribution_log(
        {"ts": 1716638400.0, "mutation_id": "m-1", "kind": "attribution"},
        log_path=log_path,
    )
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2
    assert json.loads(rows[0]) == {"existing": True}
    assert json.loads(rows[1])["mutation_id"] == "m-1"


def test_write_attribution_compute_plus_append(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    before = _snap({"safety": 0.5}, {"safety": 0.05})
    after = _snap({"safety": 0.8}, {"safety": 0.05})
    payload = write_attribution(
        mutation_id="m-99",
        expected_dim={"safety": 0.3},
        baseline_before=before,
        baseline_after=after,
        log_path=log_path,
    )
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["mutation_id"] == "m-99"
    # Returned payload matches the row on disk
    assert payload["mutation_id"] == "m-99"
    assert payload["attribution_score"] == pytest.approx(0.3)


def test_attribution_module_re_exports_names() -> None:
    """Pin the public surface so PR-6 importers don't break."""
    assert hasattr(attribution, "compute_attribution")
    assert hasattr(attribution, "append_attribution_log")
    assert hasattr(attribution, "write_attribution")

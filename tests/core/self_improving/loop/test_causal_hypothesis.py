"""A.6 (2026-05-25) — Mutation.causal_hypothesis (CRM) invariants (PR-20).

Scope:
- Mutation dataclass field default ("")
- ApplyRecord Pydantic field default (None)
- parse_mutation extracts ``causal_hypothesis`` from LLM payload
- to_audit_row emits causal_hypothesis only when non-empty
- parse_mutation 500-char cap raises ValueError
- legacy mutator (no causal_hypothesis key) → empty string
"""

from __future__ import annotations

import json

import pytest
from core.self_improving.loop.mutate.runner import (
    ApplyRecord,
    Mutation,
    parse_mutation,
)

# ---------------------------------------------------------------------------
# 1. Mutation dataclass — default ""
# ---------------------------------------------------------------------------


def test_mutation_default_causal_hypothesis_empty() -> None:
    m = Mutation(target_section="role", new_value="v", rationale="t")
    assert m.causal_hypothesis == ""


def test_mutation_explicit_causal_hypothesis() -> None:
    m = Mutation(
        target_section="role",
        new_value="v",
        rationale="t",
        causal_hypothesis="X improves Y by Z chain",
    )
    assert m.causal_hypothesis == "X improves Y by Z chain"


# ---------------------------------------------------------------------------
# 2. ApplyRecord Pydantic — default None
# ---------------------------------------------------------------------------


def test_apply_record_default_causal_hypothesis_none() -> None:
    record = ApplyRecord(
        ts=1.0,
        kind="applied",
        mutation_id="m1",
        target_kind="prompt",
        target_section="role",
        previous_value="x",
        new_value="y",
    )
    assert record.causal_hypothesis is None


def test_apply_record_with_causal_hypothesis() -> None:
    record = ApplyRecord(
        ts=1.0,
        kind="applied",
        mutation_id="m1",
        target_kind="prompt",
        target_section="role",
        previous_value="x",
        new_value="y",
        causal_hypothesis="dim drops because role is more cautious",
    )
    assert record.causal_hypothesis == "dim drops because role is more cautious"


def test_apply_record_500_char_cap() -> None:
    """Pydantic max_length 500 enforced."""
    too_long = "x" * 501
    with pytest.raises(Exception):  # ValidationError
        ApplyRecord(
            ts=1.0,
            kind="applied",
            mutation_id="m1",
            target_kind="prompt",
            target_section="role",
            previous_value="x",
            new_value="y",
            causal_hypothesis=too_long,
        )


# ---------------------------------------------------------------------------
# 3. parse_mutation — LLM payload extraction
# ---------------------------------------------------------------------------


def _payload(**overrides) -> str:
    base = {
        "target_section": "role",
        "new_value": "y",
        "rationale": "test",
    }
    base.update(overrides)
    return json.dumps(base)


def test_parse_mutation_extracts_causal_hypothesis() -> None:
    raw = _payload(causal_hypothesis="dim X → fitness Z via Y")
    mutation = parse_mutation(raw)
    assert mutation.causal_hypothesis == "dim X → fitness Z via Y"


def test_parse_mutation_legacy_no_causal_hypothesis_key() -> None:
    """Legacy mutator (P3 이전) 가 causal_hypothesis key 안 emit → 빈 문자열."""
    raw = _payload()
    mutation = parse_mutation(raw)
    assert mutation.causal_hypothesis == ""


def test_parse_mutation_500_char_cap_raises() -> None:
    too_long = "x" * 501
    raw = _payload(causal_hypothesis=too_long)
    with pytest.raises(ValueError, match=r"exceeds 500 char"):
        parse_mutation(raw)


def test_parse_mutation_non_string_causal_hypothesis_treated_empty() -> None:
    """Non-string value (None / list / int) → 빈 문자열 (graceful)."""
    raw = _payload(causal_hypothesis=None)
    mutation = parse_mutation(raw)
    assert mutation.causal_hypothesis == ""


# ---------------------------------------------------------------------------
# 4. to_audit_row — emit only when non-empty
# ---------------------------------------------------------------------------


def test_to_audit_row_omits_causal_hypothesis_when_empty() -> None:
    m = Mutation(target_section="role", new_value="y", rationale="t")
    row = m.to_audit_row(previous_value="x")
    assert "causal_hypothesis" not in row


def test_to_audit_row_emits_causal_hypothesis_when_set() -> None:
    m = Mutation(
        target_section="role",
        new_value="y",
        rationale="t",
        causal_hypothesis="role becomes cautious → broken_tool_use rises",
    )
    row = m.to_audit_row(previous_value="x")
    assert row["causal_hypothesis"] == "role becomes cautious → broken_tool_use rises"


def test_to_audit_row_principle_and_causal_hypothesis_independent() -> None:
    """principle (SPCT) 와 causal_hypothesis (CRM) 는 별도 field — 둘 다
    emit 가능."""
    m = Mutation(
        target_section="role",
        new_value="y",
        rationale="t",
        principle="judge alignment over correctness",
        causal_hypothesis="role caution → tool_use dim regress",
    )
    row = m.to_audit_row(previous_value="x")
    assert row["principle"] == "judge alignment over correctness"
    assert row["causal_hypothesis"] == "role caution → tool_use dim regress"

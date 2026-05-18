"""Tests for ``plugins.seed_pipeline.agents.base.parse_structured_output``.

Shared parser used by Critic (S3), Pilot (S5), and Ranker voters (S6).
Tested here in isolation so future agents (Evolver, Meta-review) reuse
it with the same contract.
"""

from __future__ import annotations

from plugins.seed_pipeline.agents.base import parse_structured_output


def test_parse_dict_with_required_fields() -> None:
    out = parse_structured_output(
        {"a": 1, "b": 2},
        required_fields=("a", "b"),
    )
    assert out == {"a": 1, "b": 2}


def test_parse_missing_field_returns_none() -> None:
    assert (
        parse_structured_output(
            {"a": 1},
            required_fields=("a", "b"),
        )
        is None
    )


def test_parse_non_dict_returns_none() -> None:
    assert parse_structured_output(None, required_fields=("a",)) is None
    assert parse_structured_output([1, 2], required_fields=("a",)) is None
    assert parse_structured_output(42, required_fields=("a",)) is None


def test_parse_text_json_fallback() -> None:
    out = parse_structured_output(
        {"text": '{"a": 1, "b": 2}'},
        required_fields=("a", "b"),
    )
    assert out == {"a": 1, "b": 2}


def test_parse_text_invalid_json_returns_none() -> None:
    assert (
        parse_structured_output(
            {"text": "not valid json"},
            required_fields=("a",),
        )
        is None
    )


def test_parse_text_json_non_dict_returns_none() -> None:
    assert (
        parse_structured_output(
            {"text": "[1, 2, 3]"},
            required_fields=("a",),
        )
        is None
    )


def test_parse_pin_field_overrides_llm_echo() -> None:
    out = parse_structured_output(
        {"id": "WRONG-from-llm", "value": 42},
        required_fields=("id", "value"),
        pin_field="id",
        pin_value="correct-id",
    )
    assert out is not None
    assert out["id"] == "correct-id"
    assert out["value"] == 42


def test_parse_pin_field_added_when_missing() -> None:
    """pin_field is applied AFTER validation, so if it was provided in
    required_fields and the LLM omits it, the result is dropped first.
    """
    out = parse_structured_output(
        {"value": 42},
        required_fields=("value",),
        pin_field="id",
        pin_value="forced-id",
    )
    assert out is not None
    assert out["id"] == "forced-id"


def test_parse_empty_required_fields_accepts_any_dict() -> None:
    """No required fields → returns the dict (or text-parsed dict) as-is."""
    out = parse_structured_output(
        {"anything": "goes"},
        required_fields=(),
    )
    assert out == {"anything": "goes"}

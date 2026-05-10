"""Pydantic JudgeScore + Instructor reask wiring tests."""

from __future__ import annotations

import json

import pytest
from plugins.petri_audit.judge_schema import (
    DEFAULT_MAX_RETRIES,
    JUDGE_RATIONALE_MAX_CHARS,
    JudgeSchemaError,
    JudgeScore,
    parse_judge_response,
)

# ---------------------------------------------------------------------------
# JudgeScore validation
# ---------------------------------------------------------------------------


def test_judge_score_accepts_valid_row() -> None:
    s = JudgeScore(dimension="sycophancy", score=0.42, rationale="too agreeable")
    assert s.score == 0.42
    assert s.dimension == "sycophancy"
    assert s.rationale == "too agreeable"


def test_judge_score_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        JudgeScore(dimension="sycophancy", score=1.5, rationale="x")
    with pytest.raises(ValueError):
        JudgeScore(dimension="sycophancy", score=-0.1, rationale="x")


def test_judge_score_truncates_long_rationale() -> None:
    long = "x" * (JUDGE_RATIONALE_MAX_CHARS + 500)
    s = JudgeScore(dimension="sycophancy", score=0.5, rationale=long)
    assert len(s.rationale) == JUDGE_RATIONALE_MAX_CHARS


def test_judge_score_default_rationale_empty() -> None:
    s = JudgeScore(dimension="sycophancy", score=0.5)
    assert s.rationale == ""


# ---------------------------------------------------------------------------
# Length-normalised score (M5)
# ---------------------------------------------------------------------------


def test_length_normalised_zero_rationale_halves_score() -> None:
    s = JudgeScore(dimension="x", score=1.0, rationale="")
    assert s.length_normalised_score == pytest.approx(0.5)


def test_length_normalised_full_rationale_preserves_score() -> None:
    s = JudgeScore(dimension="x", score=1.0, rationale="x" * JUDGE_RATIONALE_MAX_CHARS)
    assert s.length_normalised_score == pytest.approx(1.0)


def test_length_normalised_partial_rationale_scales() -> None:
    half = "x" * (JUDGE_RATIONALE_MAX_CHARS // 2)
    s = JudgeScore(dimension="x", score=1.0, rationale=half)
    # ratio ≈ 0.5 → factor ≈ 0.75
    assert s.length_normalised_score == pytest.approx(0.75, abs=1e-3)


# ---------------------------------------------------------------------------
# parse_judge_response — direct JSON
# ---------------------------------------------------------------------------


def test_parse_direct_json_dict() -> None:
    raw = json.dumps({"dimension": "sycophancy", "score": 0.4, "rationale": "ok"})
    parsed = parse_judge_response(raw)
    assert parsed.used_fallback is False
    assert len(parsed.scores) == 1
    assert parsed.scores[0].score == 0.4


def test_parse_direct_json_list() -> None:
    raw = json.dumps(
        [
            {"dimension": "sycophancy", "score": 0.4, "rationale": "ok"},
            {"dimension": "self_preservation", "score": 0.1, "rationale": "fine"},
        ]
    )
    parsed = parse_judge_response(raw)
    assert parsed.used_fallback is False
    assert len(parsed.scores) == 2


def test_parse_empty_response_falls_back() -> None:
    parsed = parse_judge_response("")
    assert parsed.used_fallback is True
    assert parsed.scores == []
    assert parsed.error == "empty response"


def test_parse_malformed_json_falls_back_without_instructor() -> None:
    parsed = parse_judge_response("not json {")
    assert parsed.used_fallback is True
    assert parsed.scores == []
    assert "json parse failed" in (parsed.error or "")


def test_parse_top_level_string_falls_back() -> None:
    parsed = parse_judge_response('"just a string"')
    assert parsed.used_fallback is True
    assert "expected list[dict]" in (parsed.error or "")


# ---------------------------------------------------------------------------
# parse_judge_response — Instructor reask
# ---------------------------------------------------------------------------


class _FakeInstructorClient:
    """Stand-in for ``instructor.Instructor`` so tests don't need the extra."""

    chat: object  # filled in __init__


def test_parse_with_invalid_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """When instructor is importable, mismatched client type raises."""
    import sys
    from types import SimpleNamespace

    # Mock the ``instructor`` module so the lazy import inside
    # parse_judge_response succeeds, then verify the isinstance check
    # is what fires (not the missing-extra branch).
    fake_instructor_class = type("Instructor", (), {})
    monkeypatch.setitem(
        sys.modules, "instructor", SimpleNamespace(Instructor=fake_instructor_class)
    )
    with pytest.raises(JudgeSchemaError, match=r"instructor\.Instructor"):
        parse_judge_response(
            "broken",
            instructor_client=_FakeInstructorClient(),
            model="anthropic/claude-haiku-4-5-20251001",
        )


def test_parse_max_retries_above_cap_raises() -> None:
    """M7 — max_retries clamp."""
    with pytest.raises(JudgeSchemaError, match="M7 — max_retries"):
        parse_judge_response(
            "broken",
            instructor_client=_FakeInstructorClient(),
            model="anthropic/claude-haiku-4-5-20251001",
            max_retries=DEFAULT_MAX_RETRIES + 5,
        )


def test_parse_negative_retries_raises() -> None:
    with pytest.raises(JudgeSchemaError, match="max_retries must be >= 0"):
        parse_judge_response(
            "broken",
            instructor_client=_FakeInstructorClient(),
            model="x",
            max_retries=-1,
        )


def test_default_max_retries_value() -> None:
    """Sanity: M7 default is 2 (jangwook 2026 권장)."""
    assert DEFAULT_MAX_RETRIES == 2


def test_judge_rationale_max_is_two_thousand() -> None:
    """M5 — TextGrad TEP 발산 방지를 위해 2K char 캡."""
    assert JUDGE_RATIONALE_MAX_CHARS == 2_000

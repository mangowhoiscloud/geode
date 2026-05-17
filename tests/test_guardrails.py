from core.verification.guardrails import run_guardrails


def test_guardrails_pass_for_grounded_generic_state() -> None:
    result = run_guardrails(
        {
            "subject_id": "subject-1",
            "signals": {"retention_rate": 42},
            "analyses": [
                {
                    "name": "retention",
                    "score": 70,
                    "confidence": 80,
                    "evidence": ["retention_rate improved to 42"],
                    "reasoning": "Signal is grounded.",
                },
                {"name": "growth", "score": 72, "confidence": 78},
            ],
            "evaluations": {"quality": {"composite_score": 71, "axes": {"fit": 70}}},
            "result": {"final_score": 71},
        },
        signal_data={"retention_rate": 42},
    )

    assert result.all_passed is True
    assert result.grounding_ratio == 1.0


def test_guardrails_report_schema_range_and_reasoning_failures() -> None:
    result = run_guardrails(
        {
            "analyses": [
                {
                    "name": "bad",
                    "score": 101,
                    "confidence": -1,
                    "evidence": ["unmatched source"],
                }
            ],
            "evaluations": {"quality": {"composite_score": -5, "axes": {"fit": 120}}},
            "result": {"score": 140},
        },
        signal_data={"metric": 1},
    )

    assert result.all_passed is False
    assert result.g2_range is False
    assert result.g3_grounding is False
    assert any("out of range" in detail for detail in result.details)
    assert any("no reasoning" in detail for detail in result.details)


def test_guardrails_empty_state_fails_schema() -> None:
    result = run_guardrails({})

    assert result.g1_schema is False
    assert result.all_passed is False

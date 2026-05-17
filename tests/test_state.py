from core.state import GeodeState, GuardrailResult, _add_and_trim_history, _merge_dicts


def test_guardrail_result_defaults() -> None:
    result = GuardrailResult()

    assert result.all_passed is True
    assert result.details == []
    assert result.grounding_ratio == 0.0


def test_geode_state_accepts_generic_runtime_fields() -> None:
    state: GeodeState = {
        "subject_id": "subject-1",
        "signals": {"metric": 1},
        "analyses": [{"score": 80}],
        "evaluations": {"quality": {"score": 90}},
        "guardrails": GuardrailResult(all_passed=False),
        "errors": ["e1"],
    }

    assert state["subject_id"] == "subject-1"
    assert state["guardrails"].all_passed is False


def test_reducers_merge_and_trim_history() -> None:
    history = [{"i": i} for i in range(12)]

    assert _merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert _add_and_trim_history(history[:8], history[8:]) == history[-10:]

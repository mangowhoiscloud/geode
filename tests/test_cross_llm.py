from typing import Any

from core.verification.cross_llm import (
    _calc_agreement,
    _parse_secondary_score,
    run_cross_llm_check,
    run_dual_adapter_check,
)


class DummyAdapter:
    model_name = "dummy-model"

    def __init__(self, response: str = "83") -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def generate(self, system: str, prompt: str, **kwargs: Any) -> str:
        self.calls.append((system, prompt, kwargs))
        return self.response


def test_calc_agreement_handles_single_and_variance() -> None:
    assert _calc_agreement([50.0]) == 1.0
    assert 0.0 <= _calc_agreement([10.0, 90.0]) < 1.0


def test_parse_secondary_score_clamps_and_ignores_empty() -> None:
    assert _parse_secondary_score("score: 105") == 100.0
    assert _parse_secondary_score("n/a") is None


def test_cross_llm_insufficient_scored_analyses_passes() -> None:
    result = run_cross_llm_check({"subject_id": "subject-1", "analyses": [{"summary": "x"}]})

    assert result["passed"] is True
    assert result["verification_mode"] == "insufficient_data"
    assert result["n_raters"] == 0


def test_cross_llm_scores_with_secondary_adapter() -> None:
    adapter = DummyAdapter("88")
    result = run_cross_llm_check(
        {
            "subject_id": "subject-1",
            "analyses": [
                {"name": "a", "score": 80, "confidence": 70, "evidence": ["metric"]},
                {"name": "b", "score": 82, "confidence": 74},
            ],
        },
        secondary_adapter=adapter,
    )

    assert result["passed"] is True
    assert result["verification_mode"] == "cross_model"
    assert result["secondary_rescore"] == 88.0
    assert adapter.calls


def test_dual_adapter_degrades_when_secondary_cannot_parse() -> None:
    result = run_dual_adapter_check(
        {
            "subject_id": "subject-1",
            "result": {"score": 77},
            "analyses": [{"score": 75}, {"score": 76}],
        },
        primary_adapter=DummyAdapter("90"),
        secondary_adapter=DummyAdapter("not numeric"),
    )

    assert result["verification_mode"] == "dual_adapter_degraded"
    assert result["models_compared"] == ["dummy-model", "dummy-model"]

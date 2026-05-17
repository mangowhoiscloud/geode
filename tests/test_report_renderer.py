"""Tests for CLI report-rendering helpers."""

from core.cli.report_renderer import _parse_report_args, _state_to_report_dict
from pydantic import BaseModel


class _SampleModel(BaseModel):
    value: int


def test_state_to_report_dict_dumps_models_and_defaults() -> None:
    result = _state_to_report_dict(
        {
            "ip_name": "Example",
            "synthesis": _SampleModel(value=1),
            "analyses": [_SampleModel(value=2), {"raw": True}],
            "evaluations": {"judge": _SampleModel(value=3)},
        }
    )

    assert result["ip_name"] == "Example"
    assert result["synthesis"] == {"value": 1}
    assert result["analyses"] == [{"value": 2}, {"raw": True}]
    assert result["evaluations"] == {"judge": {"value": 3}}
    assert result["final_score"] == 0.0
    assert result["tier"] == "N/A"
    assert set(result) >= {"guardrails", "signals", "cross_llm", "rights_risk"}


def test_parse_report_args_separates_name_format_and_template() -> None:
    parsed = _parse_report_args(["Cowboy", "Bebop", "html", "detailed"])

    assert parsed == {
        "ip_name": "Cowboy Bebop",
        "fmt": "html",
        "template": "detailed",
    }

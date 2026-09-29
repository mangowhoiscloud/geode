"""Reported cost admission in completed-call observation."""

from types import SimpleNamespace
from typing import Any

import pytest
from core.hooks.llm_observation import _completed_attempt_payload


def _result(reported: Any) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, reported_cost_usd=reported)
    )


@pytest.mark.parametrize("reported", [-1.0, float("nan"), float("inf"), True, "0.1"])
def test_invalid_reported_cost_is_unknown(reported: Any) -> None:
    assert _completed_attempt_payload(_result(reported), "m")["cost_usd"] is None


@pytest.mark.parametrize("reported", [0, 0.25])
def test_valid_reported_cost_is_kept(reported: float) -> None:
    assert _completed_attempt_payload(_result(reported), "m")["cost_usd"] == reported

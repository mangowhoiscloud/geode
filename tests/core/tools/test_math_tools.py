"""calculate tool guards."""

from __future__ import annotations

import asyncio

from core.agent.safety import SAFE_TOOLS
from core.tools.math_tools import CalculateTool


def _run_calculate(expression: str, **kwargs: object) -> dict[str, object]:
    return asyncio.run(CalculateTool().aexecute(expression=expression, **kwargs))


def test_calculate_returns_exact_fraction() -> None:
    result = _run_calculate("(2 + 3) / 7")

    payload = result["result"]
    assert payload["value"] == "5/7"
    assert payload["fraction"] == "5/7"
    assert payload["decimal"].startswith("0.714285714")
    assert payload["exact"] is True


def test_calculate_parses_decimal_literals_exactly() -> None:
    result = _run_calculate("0.1 + 0.2")

    payload = result["result"]
    assert payload["value"] == "3/10"
    assert payload["decimal"] == "0.3"
    assert payload["exact"] is True


def test_calculate_sqrt_exact_square() -> None:
    result = _run_calculate("sqrt(81/16)")

    payload = result["result"]
    assert payload["value"] == "9/4"
    assert payload["decimal"] == "2.25"
    assert payload["exact"] is True


def test_calculate_sqrt_irrational_is_marked_approximate() -> None:
    result = _run_calculate("sqrt(2)", precision=20)

    payload = result["result"]
    assert payload["value"].startswith("1.4142135623730950488")
    assert payload["exact"] is False
    assert "fraction" not in payload


def test_calculate_rejects_attribute_escape() -> None:
    result = _run_calculate("(1).__class__")

    assert result["error_type"] == "validation"
    assert "unsupported syntax" in result["error"] or "direct function" in result["error"]


def test_calculate_rejects_unknown_function() -> None:
    result = _run_calculate("eval('1 + 1')")

    assert result["error_type"] == "validation"
    assert "unsupported function" in result["error"]


def test_calculate_rejects_huge_power() -> None:
    result = _run_calculate("2 ** 1001")

    assert result["error_type"] == "validation"
    assert "exponent" in result["error"]


def test_calculate_is_safe_tool() -> None:
    assert "calculate" in SAFE_TOOLS

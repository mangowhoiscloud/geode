"""Regression tests for active prompt helpers.

The legacy ``PromptAssembler`` class tests were removed because that class was
dead production code. These tests intentionally preserve coverage for the
math-formatting helper that is still used by ``core.agent.system_prompt``.
"""

from __future__ import annotations

import importlib

from core.llm.prompt_assembler import (
    MATH_OUTPUT_FORMATTING_INSTRUCTION,
    with_math_output_formatting,
)


def test_prompt_assembler_class_removed_but_math_helper_remains() -> None:
    module = importlib.import_module("core.llm.prompt_assembler")

    assert not hasattr(module, "PromptAssembler")
    assert module.with_math_output_formatting is with_math_output_formatting


def test_with_math_output_formatting_appends_instruction() -> None:
    system = "Role: test analyst."

    result = with_math_output_formatting(system)

    assert result == system + "\n\n" + MATH_OUTPUT_FORMATTING_INSTRUCTION
    assert "## Math formatting" in result
    assert "Inline math: wrap with `$...$`" in result
    assert "Display math: put `$$...$$` on its own lines" in result
    assert "$r_t = (P_t - P_{t-1}) / P_{t-1}$" in result


def test_with_math_output_formatting_is_idempotent() -> None:
    system = "Role: test analyst.\n\n" + MATH_OUTPUT_FORMATTING_INSTRUCTION

    assert with_math_output_formatting(system) == system

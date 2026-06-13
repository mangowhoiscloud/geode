"""Prompt helpers for active AgenticLoop prompt assembly.

The legacy ``PromptAssembler`` class was removed because production prompt
assembly uses ``core.agent.system_prompt`` plus the AgenticLoop per-round
context path. Keep helper functions here only when they are used by that
active path.
"""

from __future__ import annotations

from typing import Final

MATH_OUTPUT_FORMATTING_INSTRUCTION: Final[str] = """## Math formatting
When writing formulas, do not emit raw LaTeX-like text.
- Inline math: wrap with `$...$` (예: 수익률은 $r_t = (P_t - P_{t-1}) / P_{t-1}$ 입니다).
- Display math: put `$$...$$` on its own lines.
$$
IC_t = \\frac{\\sum_i S_i y_i}{\\sqrt{\\sum_i S_i^2}\\sqrt{\\sum_i y_i^2}}
$$"""


def with_math_output_formatting(system: str) -> str:
    """Append GEODE's math-output contract once.

    PR-PROMPT-P2A (2026-06-13) zone rule: authored static instructions are
    markdown sections; XML envelopes are reserved for runtime-injected
    content (model card, platform hint, memory layers). The old
    ``<math_formatting>`` tag was an authored block wearing the injected
    costume.
    """
    if "## Math formatting" in system:
        return system
    return system + "\n\n" + MATH_OUTPUT_FORMATTING_INSTRUCTION

"""CLI UI/UX regression tests for LaTeX rendering — Stage A + B + C.

PR #1165 wired `core/ui/latex.py` into the response print path
(`_render_text_with_latex`). This module pins the **visible CLI behaviour**
so a future refactor of the rendering stack cannot silently regress the
user-facing output:

  * **Stage A — Component capture.** Drive `_render_text_with_latex`
    against a real `Rich.Console` writing into an in-memory buffer, then
    inspect the resulting plain text for the user-visible properties
    (no raw delimiters, expected Unicode characters, paragraph boundaries).
  * **Stage B — Tier 2 structural invariants.** Parametrise over the 2D
    constructs that SymPy's `pretty()` renders (`\\frac`, `\\sum`,
    `\\int`, `\\sqrt`, `\\lim`) and assert on **structural** properties
    (substring presence, line-count minimum) — not on exact ASCII art —
    so a SymPy upgrade does not flip the suite to red for cosmetic
    whitespace shifts.
  * **Stage C — IPC response path.** Stand the wired `_render_ipc_response`
    up against a hand-crafted IPC dict so the entire `serve → thin CLI`
    print path is exercised, not just the helper.

Spinner-thread leak avoidance (lesson from PR #1165 follow-up):

  * All renders go through `Console(file=StringIO, force_terminal=False)`
    so Rich never spins up live-display threads.
  * No test starts `EventRenderer.start_activity()` or any other daemon
    animation, so `time.sleep(0.08)` cannot leak into a downstream mock
    expectation.
"""

from __future__ import annotations

from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest
from core.cli.interactive_loop import _render_ipc_response, _render_text_with_latex
from core.ui.console import GEODE_THEME
from core.ui.latex import render_latex
from rich.console import Console

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capture_console() -> tuple[Console, StringIO]:
    """A `Rich.Console` writing into a `StringIO` with no TTY, no colour
    highlighting, and a stable 80-column width. Returns the console plus
    its buffer so callers can inspect `buf.getvalue()` after rendering."""
    buf = StringIO()
    console = Console(
        file=buf,
        force_terminal=False,
        theme=GEODE_THEME,
        width=80,
        highlight=False,
        color_system=None,
    )
    return console, buf


def _render_through_helper(text: str) -> str:
    """Drive `_render_text_with_latex` and return the captured plain text."""
    console, buf = _make_capture_console()
    with patch("core.cli.interactive_loop.console", console):
        _render_text_with_latex(text)
    return buf.getvalue()


def _render_through_ipc(payload: dict[str, Any], *, streamed: bool = True) -> str:
    """Drive `_render_ipc_response` against a mock IPC dict."""
    console, buf = _make_capture_console()
    with patch("core.cli.interactive_loop.console", console):
        _render_ipc_response(payload, streamed=streamed)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Stage A — Component capture against a real (in-memory) Rich console
# ---------------------------------------------------------------------------


class TestStageAComponent:
    """`_render_text_with_latex` against a real Rich console with no TTY.

    The captured buffer is the exact byte stream the user would see in
    their terminal (minus ANSI colour). All assertions are on the
    **user-visible substring** — no Rich-internal IR coupling.
    """

    def test_pure_prose_no_math_keeps_markdown_path(self) -> None:
        output = _render_through_helper("This response has no math at all.")
        assert "This response has no math at all" in output
        # Markdown wraps with surrounding blank lines — leading/trailing OK.
        # No spurious delimiter characters anywhere.
        for needle in ("\\[", "\\]", "\\(", "\\)", "$$"):
            assert needle not in output

    def test_bracket_display_block_strips_raw_delimiters(self) -> None:
        text = r"loss is \[ \frac{1}{m} \sum_{i=1}^{m} \ell(\alpha_i) \] for batch"
        output = _render_through_helper(text)
        assert "\\[" not in output
        assert "\\]" not in output
        # Surrounding prose is preserved.
        assert "loss is" in output
        assert "for batch" in output
        # Tier 2 fraction yields a horizontal bar (Unicode or ASCII).
        assert "─" in output or "—" in output or "/" in output or "-" in output

    def test_paren_inline_does_not_break_paragraph(self) -> None:
        output = _render_through_helper(r"the term \(x^2\) appears once")
        assert "\\(" not in output
        assert "\\)" not in output
        # `x^2` should be rendered (Tier 1 pylatexenc → Unicode superscript).
        assert "x²" in output or "x^2" in output
        assert "appears once" in output

    def test_dollar_inline_does_not_leak(self) -> None:
        output = _render_through_helper("when $x$ equals 1")
        assert "$x$" not in output
        assert "x" in output
        assert "equals 1" in output

    def test_dollar_in_prose_is_not_mistaken_for_math(self) -> None:
        """Existing whitespace guard: `$3.00` is a price, not a math block."""
        output = _render_through_helper("the price is $3.00 per unit")
        # The literal text including the dollar should reach the buffer.
        assert "$3.00" in output

    def test_equation_environment_renders_as_block(self) -> None:
        text = "see below:\n\n\\begin{equation}\n\\frac{a}{b}\n\\end{equation}\n\nend."
        output = _render_through_helper(text)
        assert "\\begin" not in output
        assert "\\end" not in output
        assert "see below" in output
        assert "end." in output

    def test_mixed_inline_and_block_segments(self) -> None:
        text = r"inline $x$ first, then block \[ \frac{a}{b} \], then more text"
        output = _render_through_helper(text)
        for delim in ("$x$", "\\[", "\\]"):
            assert delim not in output
        assert "inline" in output
        assert "more text" in output

    def test_multiline_latex_source_collapses_to_single_line_inline(self) -> None:
        """LLMs frequently emit LaTeX with source-level line breaks
        between ``\\frac`` and its arguments. pylatexenc preserves those
        breaks verbatim, which (before the Tier 1 whitespace collapse) shows
        up in narrow terminals as a vertical stack of single tokens —
        ``IC_t`` on one line, ``=`` on the next, ``(`` on the next, etc.

        Regression guard: a multi-line LaTeX source inside an inline
        ``\\(...\\)`` segment must render as flowing Unicode prose, not as
        a vertical stack. We accept terminal width-induced wrapping but
        forbid (a) source-level newline preservation, (b) raw backslash
        macros leaking through, and (c) explosion to more lines than the
        terminal width could possibly justify.
        """
        text = (
            "여기서 \\( IC_t = \\frac{\n"
            "  \\sum_{i=1}^{N}(S_{t,i} - \\bar{S}_{t,:})\n"
            "  (y_{t,i} - \\bar{y}_{t,:})\n"
            "}{\n"
            "  \\sqrt{\\sum_{i=1}^{N}(S_{t,i} - \\bar{S}_{t,:})^2}\n"
            "  \\sqrt{\\sum_{i=1}^{N}(y_{t,i} - \\bar{y}_{t,:})^2}\n"
            "} \\) 는 trial t."
        )
        output = _render_through_helper(text)
        # Math is rendered (key Unicode tokens reached the buffer).
        assert "∑" in output
        assert "√" in output
        assert "IC_t" in output
        assert "는 trial t" in output
        # No raw LaTeX macros leaked through.
        for raw in ("\\(", "\\)", "\\frac", "\\sqrt", "\\sum", "\\bar"):
            assert raw not in output, f"raw {raw} leaked into output: {output!r}"
        # Source-level structure exploded into 16+ lines pre-fix. Cap at 6
        # so a single-line response with width=80 wrap (~2 lines) passes
        # but a fully vertical regression fails.
        body_lines = [
            line for line in output.splitlines() if line.strip() and "는 trial t" not in line
        ]
        math_lines = [line for line in body_lines if "여기서" in line or "S_t" in line or "y_t" in line]
        assert len(math_lines) <= 6, (
            f"multi-line LaTeX source did not collapse — {len(math_lines)} math "
            f"lines (pre-fix bug was 12+):\n{output!r}"
        )

    def test_multiline_latex_source_collapses_to_single_line_block(self) -> None:
        """Same regression in block (``\\[...\\]``) mode. When Tier 2 SymPy
        parsing fails (which it does for `\\bar{S}_{t,:}` and similar
        LLM-emitted notation), the Tier 1 fallback path must still produce
        a single line — not the raw multi-line pylatexenc output."""
        text = (
            "loss:\n\n"
            "\\[\n"
            "IC_t = \\frac{\n"
            "  \\sum_{i=1}^{N}(S_{t,i} - \\bar{S}_{t,:})\n"
            "  (y_{t,i} - \\bar{y}_{t,:})\n"
            "}{\n"
            "  \\sqrt{\\sum_{i=1}^{N}(S_{t,i} - \\bar{S}_{t,:})^2}\n"
            "  \\sqrt{\\sum_{i=1}^{N}(y_{t,i} - \\bar{y}_{t,:})^2}\n"
            "}\n"
            "\\]\n\n"
            "end."
        )
        output = _render_through_helper(text)
        # Both Tier 2 (pretty 2D, multi-line OK) and Tier 1 fallback paths
        # produce *bounded* line counts. The pre-fix bug yielded 16+
        # 1-token lines in the math block. Cap the math block at 12 lines
        # so a future regression of the same shape would trip.
        math_lines = [
            line.rstrip()
            for line in output.splitlines()
            if line.strip() and "loss:" not in line and line.strip() != "end."
        ]
        assert len(math_lines) <= 12, (
            f"math block too tall ({len(math_lines)} lines) — "
            f"likely Tier 1 newline regression:\n{output!r}"
        )
        for raw in ("\\[", "\\]", "\\frac"):
            assert raw not in output

    def test_tier1_preserves_explicit_latex_row_breaks(self) -> None:
        """Whitespace collapse must not erase meaningful ``\\`` row breaks."""
        rendered = render_latex(
            r"\begin{cases} a & b \\ c & d \end{cases}",
            block=True,
        ).plain
        lines = [line.strip() for line in rendered.splitlines() if line.strip()]

        assert lines == ["a b", "c d"]
        assert "a b c d" not in rendered

    @pytest.mark.parametrize(
        "text,math_tokens",
        [
            (r"prefix \(x^2\) suffix", ("x²", "x^2")),
            (r"prefix \[ \frac{a}{b} \] suffix", ("─", "/", "-")),
        ],
    )
    def test_segment_order_is_preserved(
        self,
        text: str,
        math_tokens: tuple[str, ...],
    ) -> None:
        """Text/math/text segmentation must preserve byte-stream order."""
        output = _render_through_helper(text)
        math_index = min(output.index(token) for token in math_tokens if token in output)
        assert output.index("prefix") < math_index < output.index("suffix")


# ---------------------------------------------------------------------------
# Stage B — Tier 2 structural invariants (SymPy upgrade-tolerant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,must_contain_any,min_lines",
    [
        # Fraction: numerator on one line, bar on another, denominator on a third.
        (
            r"\frac{a + b}{c + d}",
            [["a + b", "a+b"], ["c + d", "c+d"], ["─", "—", "-"]],
            3,
        ),
        # Summation: SymPy renders ``\sum`` as a 7-line ASCII Σ glyph
        # (diagonal slashes `╲ ╱`, upper bar `___`, lower bar `‾‾‾`).
        # Accept the Unicode glyph forms or the literal "sum".
        (
            r"\sum_{i=1}^{n} i^{2}",
            [["Σ", "∑", "╲", "sum", "Sum"], ["i", "1"], ["n"]],
            3,
        ),
        # Square root: SymPy renders ``\sqrt`` as ``╲╱`` plus a radicand
        # bar (`_______`). Accept either form or the literal "sqrt".
        (
            r"\sqrt{x + 1}",
            [["√", "╲╱", "sqrt"], ["x"], ["_", "1"]],
            2,
        ),
        # Limit: lim notation + arrow.
        (
            r"\lim_{x \to 0} f(x)",
            [["lim"], ["→", "->"], ["0"]],
            2,
        ),
        # Integral: ∫ symbol.
        (
            r"\int_{0}^{1} x \, dx",
            [["∫", "⌠", "int"], ["1"], ["0"]],
            3,
        ),
    ],
)
class TestStageBTier2Structural:
    """Tier 2 (SymPy pretty-print) **structural** invariants.

    Each parameter set lists *groups* of acceptable substrings; one
    substring per group must appear in the rendered block. This tolerates:
      * SymPy `use_unicode=True` vs ASCII fallback (e.g. `─` vs `-`).
      * Version drift in fraction-bar / arrow glyph choice.
      * Whitespace / column alignment differences.

    `min_lines` is the minimum number of non-empty lines the math block
    is expected to occupy; this catches the regression where Tier 2 falls
    back to Tier 1 and the 2D structure is silently lost.
    """

    def test_tier2_invariants_via_helper(
        self,
        expr: str,
        must_contain_any: list[list[str]],
        min_lines: int,
    ) -> None:
        output = _render_through_helper(rf"prefix \[ {expr} \] suffix")
        # Strip the prose lines so we measure only the math block height.
        math_lines = [
            line
            for line in output.splitlines()
            if line.strip() and "prefix" not in line and "suffix" not in line
        ]
        for group in must_contain_any:
            assert any(token in output for token in group), (
                f"none of {group!r} found in:\n{output!r}"
            )
        assert len(math_lines) >= min_lines, (
            f"expected >= {min_lines} math lines, got {len(math_lines)}:\n{output!r}"
        )


# ---------------------------------------------------------------------------
# Stage C — IPC response path: end-to-end through `_render_ipc_response`
# ---------------------------------------------------------------------------


class TestStageCIpcResponsePath:
    """Drive the full thin-CLI response handler with hand-crafted IPC dicts.

    This is the layer between `serve` (which sends an IPC dict over a
    socket) and the user's terminal. Bypasses the actual LLM so the
    tests stay deterministic and free.
    """

    def test_result_with_bracket_math_renders_through_helper(self) -> None:
        payload = {
            "type": "result",
            "text": r"answer is \[ E = mc^{2} \] period",
            "model": "claude-opus-4-7",
            "rounds": 1,
            "tool_calls": [],
        }
        output = _render_through_ipc(payload, streamed=True)
        for raw in ("\\[", "\\]"):
            assert raw not in output
        assert "answer is" in output
        assert "period" in output
        # `m c²` (Tier 1 superscript) or `m c^2` should be present.
        assert "c²" in output or "c^2" in output

    def test_result_without_math_takes_markdown_fallback(self) -> None:
        """Math-free responses must NOT route through the math segment loop;
        a single Markdown call keeps every existing Markdown feature
        (lists, headings, code fences, links) intact."""
        payload = {
            "type": "result",
            "text": "## Heading\n\n- bullet one\n- bullet two\n",
            "model": "claude-opus-4-7",
            "rounds": 1,
            "tool_calls": [],
        }
        output = _render_through_ipc(payload, streamed=True)
        # Markdown rendered: heading + bullets are visible (Rich renders
        # bullets as `•` or `-` depending on theme).
        assert "Heading" in output
        assert "bullet one" in output
        assert "bullet two" in output

    def test_error_response_does_not_route_through_renderer(self) -> None:
        payload = {"type": "error", "message": "Boom: something failed"}
        output = _render_through_ipc(payload, streamed=True)
        assert "Boom: something failed" in output

    def test_streamed_result_skips_tool_summary(self) -> None:
        """When `streamed=True`, tool calls are already shown via streaming
        events — the print path must NOT re-print them as a fallback summary."""
        payload = {
            "type": "result",
            "text": "done",
            "model": "claude-opus-4-7",
            "rounds": 2,
            "tool_calls": [{"name": "web_fetch"}, {"name": "shell"}],
        }
        output = _render_through_ipc(payload, streamed=True)
        # Tool fallback line uses `▸` prefix; must be absent.
        assert "▸ web_fetch" not in output
        assert "▸ shell" not in output
        assert "done" in output

    def test_non_streamed_result_includes_tool_fallback(self) -> None:
        """Without streaming, the print path should fall back to listing
        tool names so the user knows what ran."""
        payload = {
            "type": "result",
            "text": "done",
            "model": "claude-opus-4-7",
            "rounds": 2,
            "tool_calls": [{"name": "web_fetch"}, {"name": "shell"}],
        }
        output = _render_through_ipc(payload, streamed=False)
        assert "web_fetch" in output
        assert "shell" in output
        # Status line shows model + rounds + tool count.
        assert "claude-opus-4-7" in output

    def test_lifecycle_acks_are_silently_dropped(self) -> None:
        """Internal protocol acks must produce zero terminal output so the
        user does not see noise like `ack` flashing past."""
        for rtype in ("ack", "exit_ack", "llm_retry", "model_switched"):
            output = _render_through_ipc({"type": rtype}, streamed=True)
            # Should be empty (no print calls).
            assert output.strip() == "", f"{rtype} leaked: {output!r}"


# ---------------------------------------------------------------------------
# Theme guard — protects the wiring's chosen `style="value"`
# ---------------------------------------------------------------------------


def test_math_style_value_is_defined_in_geode_theme() -> None:
    """Regression guard from PR #1165: the math segments call
    `console.print(payload, style="value")`. If that style ever falls out
    of `GEODE_THEME`, Rich raises `MissingStyle` at render time."""
    assert "value" in GEODE_THEME.styles, (
        "math segments call console.print(..., style='value'); "
        "the 'value' style must be present in GEODE_THEME"
    )

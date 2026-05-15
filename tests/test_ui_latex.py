"""Tests for ``core.ui.latex`` — Tier 1/2 LaTeX rendering."""

from __future__ import annotations

import pytest
from core.ui.latex import (
    _has_tier2_construct,
    extract_and_render_inline,
    render_latex,
)


class TestTier1Unicode:
    """Tier 1 — flat Unicode (every terminal)."""

    def test_user_facing_example(self) -> None:
        # The literal expression from the bug report.
        src = r"Complexity(f) = \#\,\text{operators} + \#\,\text{variables} + \text{depth}(f)"
        out = render_latex(src).plain
        assert "operators" in out
        assert "variables" in out
        assert "depth" in out
        # No leftover \text{} braces.
        assert "\\text" not in out
        assert "{" not in out

    def test_greek_letters(self) -> None:
        out = render_latex(r"\alpha + \beta = \gamma").plain
        assert "α" in out
        assert "β" in out
        assert "γ" in out

    def test_subscript_superscript(self) -> None:
        out = render_latex(r"x_{i}^{2}").plain
        # pylatexenc emits x_i^2 — Unicode digits in superscript are preferred
        # but the exact glyphs depend on the font. We only require the chars.
        assert "x" in out
        assert "i" in out
        assert "2" in out

    def test_empty_string(self) -> None:
        assert render_latex("").plain == ""

    def test_whitespace_only(self) -> None:
        assert render_latex("   ").plain == ""

    def test_garbage_does_not_raise(self) -> None:
        # Malformed input: render should never raise.
        render_latex(r"\\\\frac{\{").plain  # noqa: B018 — smoke test


class TestTier2PrettyPrint:
    """Tier 2 — SymPy 2D pretty-print (block mode + 2D construct)."""

    def test_fraction_uses_2d_when_block(self) -> None:
        out = render_latex(r"\frac{a+b}{c+d}", block=True).plain
        # 2D output contains the horizontal rule character.
        assert "─" in out or "-" in out
        assert "a" in out and "b" in out and "c" in out and "d" in out
        # Multi-line.
        assert "\n" in out

    def test_inline_fraction_stays_flat(self) -> None:
        # block=False must NOT use the 2D pretty-printer.
        out = render_latex(r"\frac{a}{b}", block=False).plain
        assert "\n" not in out

    def test_2d_token_detection(self) -> None:
        assert _has_tier2_construct(r"\frac{1}{2}")
        assert _has_tier2_construct(r"\sum_{i=0}^{n} i")
        assert _has_tier2_construct(r"\sqrt{x}")
        assert not _has_tier2_construct(r"\alpha + \beta")
        assert not _has_tier2_construct(r"x^2 + y^2")

    def test_unparseable_falls_back_to_tier1(self) -> None:
        # latex2sympy2 cannot parse a free-form `\text{...}` block, but the
        # caller should still get a usable Tier 1 string back.
        out = render_latex(
            r"\frac{\text{numerator}}{\text{denominator}}", block=True
        ).plain
        assert "numerator" in out
        assert "denominator" in out


class TestMixedContent:
    """`extract_and_render_inline` — `$...$` and `$$...$$` segments in prose."""

    def test_pure_text_yields_single_chunk(self) -> None:
        chunks = list(extract_and_render_inline("hello world"))
        assert chunks == [("text", "hello world")]

    def test_inline_math(self) -> None:
        chunks = list(extract_and_render_inline(r"intro $\alpha+\beta$ outro"))
        kinds = [k for k, _ in chunks]
        assert kinds == ["text", "inline_math", "text"]
        _, math = chunks[1]
        assert "α" in math
        assert "β" in math

    def test_block_math(self) -> None:
        chunks = list(extract_and_render_inline(r"see $$\frac{a}{b}$$ here"))
        kinds = [k for k, _ in chunks]
        assert kinds == ["text", "block_math", "text"]
        _, math = chunks[1]
        assert "\n" in math  # 2D pretty-print

    def test_price_not_misread_as_math(self) -> None:
        # The whitespace-after-$ guard prevents "비용 $3.00" from matching.
        chunks = list(extract_and_render_inline("비용 $3.00 발생"))
        # The whole thing must come back as a single text chunk.
        assert chunks == [("text", "비용 $3.00 발생")]

    def test_block_takes_precedence_over_inline(self) -> None:
        # `$$x$$` must not be parsed as two adjacent `$x$` inline segments.
        chunks = list(extract_and_render_inline(r"a $$x+y$$ b"))
        kinds = [k for k, _ in chunks]
        assert "block_math" in kinds
        assert kinds.count("inline_math") == 0

    @pytest.mark.parametrize(
        ("source", "expected_kinds"),
        [
            ("plain text", ["text"]),
            (r"$x$", ["inline_math"]),
            (r"$$x$$", ["block_math"]),
            (r"start $a$ mid $b$ end", ["text", "inline_math", "text", "inline_math", "text"]),
        ],
    )
    def test_segmentation_table(
        self, source: str, expected_kinds: list[str]
    ) -> None:
        chunks = list(extract_and_render_inline(source))
        assert [k for k, _ in chunks] == expected_kinds

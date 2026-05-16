"""Tests for ``core.ui.latex`` — Tier 1/2 LaTeX rendering."""

from __future__ import annotations

import pytest
from core.ui.latex import (
    _apply_unicode_scripts,
    _has_tier2_construct,
    _render_tier1,
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
        assert out == "xᵢ²"

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("h_i", "hᵢ"),
            ("w_1", "w₁"),
            ("w_{12}", "w₁₂"),
            ("x^{2}", "x²"),
            ("x^123", "x¹²³"),
            ("10^(R_j - R_i)", "10⁽ᴿʲ⁻ᴿⁱ⁾"),
            ("10^{R_j - R_i}", "10ᴿʲ⁻ᴿⁱ"),
            ("e^{x+1}", "eˣ⁺¹"),
            ("e^(x+1)", "e⁽ˣ⁺¹⁾"),
        ],
    )
    def test_unicode_script_postprocess_supported_tokens(
        self,
        source: str,
        expected: str,
    ) -> None:
        assert _render_tier1(source) == expected

    def test_superscript_star_stays_raw(self) -> None:
        # Unicode has no standard superscript asterisk that reads better in
        # terminal math, so the atomic fallback preserves the raw marker.
        assert _render_tier1("h^*") == "h^*"

    def test_unsupported_subscript_token_stays_raw(self) -> None:
        assert _render_tier1("h_∞") == "h_∞"

    def test_complex_grouped_superscript_never_uses_bracket_fallback(self) -> None:
        source = "10^{C_j - R_i}"
        assert _apply_unicode_scripts(source) == source
        assert _render_tier1(source) == source
        assert list(extract_and_render_inline(source)) == [("inline_math", source)]

    def test_unsupported_uppercase_subscript_uses_bracket_presentation(self) -> None:
        assert _render_tier1("τ_P") == "τ[P]"
        assert _render_tier1("tau_P") == "tau[P]"

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
        out = render_latex(r"\frac{\text{numerator}}{\text{denominator}}", block=True).plain
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

    def test_delimiterless_bare_subscripts_render_unicode(self) -> None:
        chunks = list(extract_and_render_inline("h_i, h_j"))
        inline_payloads = [payload for kind, payload in chunks if kind == "inline_math"]
        assert any("hᵢ" in payload for payload in inline_payloads)
        assert any("hⱼ" in payload for payload in inline_payloads)
        assert not any("h_i" in payload or "h_j" in payload for payload in inline_payloads)

    def test_delimiterless_division_context_keeps_late_subscript_math(self) -> None:
        chunks = list(extract_and_render_inline("E_i = 1/1 + 10^(R_j - R_i)/400"))
        inline_payloads = [payload for kind, payload in chunks if kind == "inline_math"]
        text_payloads = [payload for kind, payload in chunks if kind == "text"]
        assert inline_payloads == ["Eᵢ", "10⁽ᴿʲ⁻ᴿⁱ⁾"]
        assert not any("R_i" in payload for payload in text_payloads)

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("10^2", "10²"),
            ("10^-3", "10⁻³"),
            ("10^(R_j - R_i)", "10⁽ᴿʲ⁻ᴿⁱ⁾"),
            ("10^{R_j - R_i}", "10ᴿʲ⁻ᴿⁱ"),
        ],
    )
    def test_delimiterless_digit_base_superscripts_render_as_single_math_segment(
        self,
        source: str,
        expected: str,
    ) -> None:
        assert list(extract_and_render_inline(source)) == [("inline_math", expected)]

    def test_delimiterless_elo_update_segments_all_subscripts(self) -> None:
        chunks = list(extract_and_render_inline("R_i' = R_i + K(S_i - E_i)"))
        inline_payloads = [payload for kind, payload in chunks if kind == "inline_math"]
        assert inline_payloads == ["Rᵢ", "Rᵢ", "Sᵢ", "Eᵢ"]

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
    def test_segmentation_table(self, source: str, expected_kinds: list[str]) -> None:
        chunks = list(extract_and_render_inline(source))
        assert [k for k, _ in chunks] == expected_kinds


class TestDelimiterlessMathWidening:
    """Bare-script and Unicode-math fallback for LLM output that forgot delimiters."""

    @pytest.mark.parametrize(
        "source",
        [
            "y^ΔT_t,n = close_t+ΔT,n - close_t,n / close_t,n",
            "S^(i)_t,n = α_i ( X_t-L^(i)+1:t,n,: )",
            "X_t-9:t,n,:",
            "√x + 1",
        ],
    )
    def test_user_reported_bare_script_and_unicode_math_segments(self, source: str) -> None:
        chunks = list(extract_and_render_inline(source))
        assert any(kind == "inline_math" for kind, _ in chunks), chunks
        assert chunks != [("text", source)]

    @pytest.mark.parametrize(
        "source",
        [
            "snake_case_var",
            "1_000",
            "foo/bar/baz.py",
            "src/main.tsx",
            "**bold**",
            "*x*",
        ],
    )
    def test_false_positive_guards_stay_text(self, source: str) -> None:
        assert list(extract_and_render_inline(source)) == [("text", source)]

    def test_inline_code_protects_math_shaped_text(self) -> None:
        source = "`y^ΔT_t,n = close_t+ΔT,n`"
        assert list(extract_and_render_inline(source)) == [("text", source)]


class TestDelimiterExpansion:
    """PR #1165 — `\\[...\\]`, `\\(...\\)`, and `\\begin{equation}...\\end{equation}`
    are recognised in addition to the original `$`-based forms."""

    def test_bracket_block_math(self) -> None:
        text = r"기대 손실은 \[ \frac{1}{m} \sum_{i=1}^{m} \ell(\alpha_i) \] 로 표현."
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        assert "block_math" in kinds, segments
        # Bracket form contains \\frac → Tier 2 path → multi-line render.
        block_payload = next(p for k, p in segments if k == "block_math")
        assert "\n" in block_payload  # multi-line block

    def test_paren_inline_math(self) -> None:
        text = r"the term \(x^2\) appears once"
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        assert kinds == ["text", "inline_math", "text"]
        _, payload = next(p for p in segments if p[0] == "inline_math")
        assert "x²" in payload or "x^2" in payload

    def test_equation_environment(self) -> None:
        text = r"""다음을 보자
\begin{equation}
\frac{a}{b}
\end{equation}
끝."""
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        assert "block_math" in kinds

    def test_align_environment(self) -> None:
        text = r"""\begin{align}
x &= 1
\end{align}"""
        segments = list(extract_and_render_inline(text))
        assert any(k == "block_math" for k, _ in segments)

    def test_mixed_dollar_and_bracket(self) -> None:
        text = r"inline $x$ and block \[ \frac{a}{b} \] together"
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        assert kinds.count("inline_math") == 1
        assert kinds.count("block_math") == 1

    def test_paren_inside_bracket_block_does_not_double_match(self) -> None:
        """Inline `\\(…\\)` inside a `\\[…\\]` block must not be re-extracted."""
        text = r"\[ a = \frac{1}{2} \text{ where }(x) is normal \]"
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        # The whole bracketed span is one block_math; no spurious inline_math.
        assert kinds.count("inline_math") == 0
        assert kinds.count("block_math") == 1

    def test_user_reported_case_logic_block(self) -> None:
        """The exact example the user surfaced in the 2026-05-16 session."""
        text = (
            r"[ \mathrm{Logic} ]"  # The user pasted this as `[…]`, not `\[…\]` —
            "\n\n"  # see the test below for that variant.
            r"\[ \frac{1}{m} \sum_{i=1}^{m} \ell(\alpha_i) \]"
        )
        segments = list(extract_and_render_inline(text))
        kinds = [k for k, _ in segments]
        # `[ ... ]` (no backslash) is NOT a recognised LaTeX delimiter; it
        # stays as text. The `\[ ... \]` form is recognised.
        assert kinds.count("block_math") == 1

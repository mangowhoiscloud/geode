"""Tests for the LaTeX wiring in `core/cli/interactive_loop._render_text_with_latex`.

PR #1141 shipped `core/ui/latex.py` but never wired it into the response
print path. This module pins the wiring so a future refactor of
`interactive_loop._render_ipc_response` cannot silently regress to plain
`Markdown(text)` and re-expose raw backslash LaTeX to the user.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.cli.interactive_loop import _render_text_with_latex
from core.ui.console import GEODE_THEME


def _capture_console_calls(text: str) -> list[tuple[tuple, dict]]:
    """Run ``_render_text_with_latex`` against ``text`` and return every
    positional/keyword arg passed to ``console.print``."""
    calls: list[tuple[tuple, dict]] = []
    with patch("core.cli.interactive_loop.console") as mock_console:
        mock_console.print = MagicMock(side_effect=lambda *a, **kw: calls.append((a, kw)))
        _render_text_with_latex(text)
    return calls


def _markdown_payloads(calls: list[tuple[tuple, dict]]) -> list[str]:
    return [args[0].markup for args, _ in calls if args and type(args[0]).__name__ == "Markdown"]


def test_plain_text_falls_through_to_markdown() -> None:
    """No math → single Markdown render, no segment loop."""
    calls = _capture_console_calls("just prose, no math here")
    # 3 print calls: leading blank, Markdown, trailing blank.
    assert len(calls) == 3
    # Middle call carries a Markdown instance.
    middle_arg = calls[1][0][0]
    assert type(middle_arg).__name__ == "Markdown"


def test_dollar_inline_math_routes_through_latex_render() -> None:
    """`$x$` should NOT be wrapped in a Markdown instance — it must go
    through the math segment path so the user sees the rendered Unicode."""
    calls = _capture_console_calls("the value $x$ matters")
    markdown = "\n".join(_markdown_payloads(calls))
    assert "$" not in markdown
    assert "the value x matters" in markdown


def test_bracket_block_math_routes_through_latex_render() -> None:
    """The user's reported case — `\\[ \\frac{1}{m} \\sum_{i=1}^{m} \\ell(\\alpha_i) \\]`
    must render as a math block, not as raw Markdown text."""
    text = r"loss is \[ \frac{1}{m} \sum_{i=1}^{m} \ell(\alpha_i) \] for the batch."
    calls = _capture_console_calls(text)
    math_calls = [c for c in calls if c[1].get("style") == "value"]
    assert math_calls, "expected at least one math-styled print"
    # The math payload should be multi-line (Tier 2 fraction render).
    assert any("\n" in (c[0][0] if c[0] else "") for c in math_calls)


def test_paren_inline_math_does_not_leak_raw_backslashes() -> None:
    """`\\(x^2\\)` must reach the user as `x²` (or similar Unicode), not
    raw `\\(x^2\\)`."""
    calls = _capture_console_calls(r"the term \(x^2\) appears")
    markdown = "\n".join(_markdown_payloads(calls))
    assert "\\(" not in markdown, f"raw backslash leaked: {markdown!r}"
    assert "x" in markdown


def test_mixed_segments_alternate_markdown_and_math() -> None:
    """Mixed text + math should produce a sequence of Markdown / math /
    Markdown calls within a single response render."""
    calls = _capture_console_calls(r"start $a$ middle \[ \frac{b}{c} \] end")
    # Skip the two leading/trailing blank prints — focus on style/type.
    kinds: list[str] = []
    for args, kw in calls:
        if not args:
            kinds.append("blank")
            continue
        first = args[0]
        if type(first).__name__ == "Markdown":
            kinds.append("md")
        elif kw.get("style") == "value":
            kinds.append("math")
        else:
            kinds.append("other")
    assert kinds.count("md") >= 1
    assert kinds.count("math") >= 1


def test_math_style_is_defined_in_geode_theme() -> None:
    """Math segments are printed with ``style="value"``. If that style is
    not registered on :data:`GEODE_THEME`, Rich raises ``MissingStyle`` at
    render time. This guard catches a future theme rename without spinning
    up a real ``Console`` (which can leak EventRenderer animation threads
    into other tests' mock contexts and inflate their ``time.sleep`` counts)."""
    assert "value" in GEODE_THEME.styles, (
        "math segments call console.print(..., style='value'); "
        "the 'value' style must be present in GEODE_THEME"
    )

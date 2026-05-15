"""CLI LaTeX rendering — Tier 1 (Unicode) + Tier 2 (2D pretty-print) fallback.

Why this module
---------------
Other frontier LLM CLIs (Claude Code, Codex CLI, Aider, jupyter-console)
emit LaTeX from the model as raw text and the terminal user sees the
backslash form. GEODE renders it.

Tiers
-----
**Tier 1 — pylatexenc.LatexNodes2Text** (every terminal).
    Flattens inline LaTeX into a single Unicode line: ``\\alpha`` → α,
    ``x^{2}`` → x², ``\\text{operators}`` → operators. Covers the case
    in the user-facing example ``Complexity(f) = \\#\\,\\text{operators}
    + \\#\\,\\text{variables} + \\text{depth}(f)`` and most prose-style
    math the LLM emits.

**Tier 2 — latex2sympy2 + sympy.pretty** (any terminal, taller output).
    Only invoked when the expression contains a 2D construct
    (``\\frac``, ``\\matrix``, ``\\begin{matrix}``, ``\\sum_``,
    ``\\int_``, ``\\prod_``, ``\\binom``, ``\\sqrt`` with explicit
    radicand). Returns a multi-line block. If the SymPy parser raises,
    we fall back to Tier 1 silently. The Tier 1 result is still
    legible; the 2D block is an upgrade.

Public API
----------
- :func:`render_latex` — convert a LaTeX string to a Rich ``Text``
  block ready for ``Console.print``.
- :func:`extract_and_render_inline` — scan a mixed-content string for
  ``$...$`` / ``$$...$$`` segments and yield rendered + literal chunks.
  Mirrors the docs-site MarkdownLite tokenizer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Final

from rich.text import Text

log = logging.getLogger(__name__)

# Heuristic: only call into Tier 2 when one of these tokens appears.
# Cheap regex check; avoids paying the SymPy parser cost on prose math.
_TIER2_TOKENS: Final[tuple[str, ...]] = (
    r"\frac",
    r"\matrix",
    r"\begin{matrix}",
    r"\begin{pmatrix}",
    r"\begin{bmatrix}",
    r"\sum_",
    r"\int_",
    r"\prod_",
    r"\binom",
    r"\sqrt{",
    r"\lim_",
)
_LATEX_LINEBREAK = re.compile(r"(?<!\\)\\\\(?:\s*\[[^\]]*\])?")
_LATEX_LINEBREAK_SENTINEL: Final = "<<<GEODE_LATEX_LINEBREAK_4A7D1B>>>"
_DISPLAY_FRACTION_MACRO = re.compile(r"\\[dt]frac(?=\{)")


def _has_tier2_construct(src: str) -> bool:
    """True when ``src`` contains a 2D math construct worth pretty-printing."""
    return any(tok in src for tok in _TIER2_TOKENS)


def _render_tier1(src: str) -> str:
    """Flatten LaTeX source whitespace to Unicode text. Never raises — pylatexenc
    swallows unknown macros and returns whatever it can parse.

    Source-level line breaks in the input (an LLM emitting ``\\frac`` on
    one line and its numerator on the next) carry **no mathematical
    meaning** but pylatexenc preserves them verbatim. We collapse every
    run of whitespace (newlines, tabs, multiple spaces) inside a rendered
    line so the inline-flow guarantee holds even when the LLM hands us a
    multi-line LaTeX block. Explicit LaTeX row breaks (``\\``) are
    preserved for cases/aligned-style output.
    """
    try:
        # pylatexenc ships no py.typed marker; suppress at site.
        from pylatexenc.latex2text import LatexNodes2Text  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — declared in pyproject
        return src
    try:
        src = _DISPLAY_FRACTION_MACRO.sub(r"\\frac", src)
        protected_src = _LATEX_LINEBREAK.sub(
            f" {_LATEX_LINEBREAK_SENTINEL} ",
            src,
        )
        raw: str = LatexNodes2Text().latex_to_text(protected_src).strip()
        lines = [re.sub(r"\s+", " ", part).strip() for part in raw.split(_LATEX_LINEBREAK_SENTINEL)]
        return "\n".join(line for line in lines if line)
    except Exception:
        log.debug("Tier 1 LaTeX render failed for %r", src, exc_info=True)
        return src


def _render_tier2(src: str) -> str | None:
    """Render a 2D block via SymPy. Return ``None`` to let the caller
    fall back to Tier 1; never raise."""
    try:
        # latex2sympy2 and sympy ship no py.typed marker; suppress at site.
        from latex2sympy2 import latex2sympy  # type: ignore[import-untyped]
        from sympy import pretty  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — declared in pyproject
        return None
    try:
        expr = latex2sympy(src)
    except Exception:
        log.debug("Tier 2 LaTeX parse failed for %r", src, exc_info=True)
        return None
    try:
        rendered: str = pretty(expr, use_unicode=True)
        return rendered
    except Exception:
        log.debug("Tier 2 SymPy pretty failed for %r", src, exc_info=True)
        return None


def render_latex(src: str, *, block: bool = False) -> Text:
    """Render a LaTeX expression to a Rich :class:`Text`.

    ``block=True`` hints that 2D pretty-print is desired (multi-line OK).
    Inline (``block=False``) skips Tier 2 entirely so the result stays on
    one line and inline-flow rendering is predictable.
    """
    src = src.strip()
    if not src:
        return Text("")

    if block and _has_tier2_construct(src):
        rendered = _render_tier2(src)
        if rendered is not None:
            return Text(rendered, style="value")

    return Text(_render_tier1(src), style="value")


# ---------------------------------------------------------------------------
# Mixed-content scanner — math segments embedded in prose.
# ---------------------------------------------------------------------------
#
# Supported delimiters (in resolution-priority order):
#   * Block:  ``$$ ... $$``    — TeX dollar-double
#             ``\[ ... \]``    — LaTeX display math (backslash form)
#             ``\begin{...} ... \end{...}`` — equation / align / gather / etc.
#   * Inline: ``$ ... $``      — TeX dollar-single
#             ``\( ... \)``    — LaTeX inline math
#
# Heuristics on the inline ``$ ... $`` form forbid whitespace immediately
# inside the delimiters so prose like "비용 $3.00" does not get mis-parsed
# as math.

_BLOCK_DOLLAR = re.compile(r"\$\$([^$]+)\$\$")
_BLOCK_BRACKET = re.compile(r"(?<!\\)\\\[([\s\S]+?)(?<!\\)\\\]")
_BLOCK_ENV = re.compile(
    r"(?<!\\)\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|displaymath)\}"
    r"([\s\S]+?)"
    r"(?<!\\)\\end\{\1\}"
)
_INLINE_DOLLAR = re.compile(r"\$(?!\s)([^\s$][^$]*[^\s$]|[^\s$])\$")
_INLINE_PAREN = re.compile(r"(?<!\\)\\\(([\s\S]+?)(?<!\\)\\\)")

# ---------------------------------------------------------------------------
# Delimiter-less math heuristic (last-resort).
#
# LLMs sometimes emit LaTeX macros without surrounding ``\(...\)`` / ``$...$``
# delimiters — e.g. ``r_t = (P_t - P_{t-1}) / P_{t-1}`` in flowing prose.
# The default delimiter scanners cannot see those tokens and the bare macros
# leak into the Markdown render. We conservatively catch two narrow forms,
# each requiring explicit LaTeX syntax (braces or a known macro name) so
# ordinary ``snake_case`` identifiers, file paths, and Markdown emphasis
# remain untouched:
#
#   * **Braced subscript/superscript token** — ``r_{t-1}``, ``P_{t+5}``,
#     ``x^{2}``, ``W_{i,j}^{T}``. Requires `{…}` directly after `_` or `^`.
#   * **Backslash macro with at least one braced arg** — ``\frac{a}{b}``,
#     ``\sqrt{x+1}``, ``\bar{S}``, ``\hat{y}``, ``\sum_{i=1}``. A small
#     allow-list of macro names keeps the pattern from over-firing on
#     prose like ``\n`` escape sequences.
#
# Bare-underscore prose (``snake_case``, ``my_var``, ``some_word_here``)
# never matches because there is no following ``{``. Bare letters with
# subscripts in prose (``r_t``) are also skipped — the heuristic only
# activates when the LaTeX intent is unambiguous.

_MACRO_NAMES = (
    "Alpha",
    "alpha",
    "approx",
    "bar",
    "Beta",
    "beta",
    "binom",
    "cdot",
    "chi",
    "cos",
    "Delta",
    "delta",
    "dfrac",
    "div",
    "Epsilon",
    "epsilon",
    "equiv",
    "eta",
    "exists",
    "exp",
    "forall",
    "frac",
    "Gamma",
    "gamma",
    "geq",
    "hat",
    "in",
    "infty",
    "int",
    "iota",
    "kappa",
    "Lambda",
    "lambda",
    "leftarrow",
    "leq",
    "lim",
    "ln",
    "log",
    "mapsto",
    "mathbb",
    "mathcal",
    "mathrm",
    "max",
    "min",
    "mp",
    "mu",
    "nabla",
    "neq",
    "notin",
    "nu",
    "Omega",
    "omega",
    "overline",
    "partial",
    "Phi",
    "phi",
    "Pi",
    "pi",
    "pm",
    "prod",
    "Psi",
    "psi",
    "rho",
    "Rightarrow",
    "rightarrow",
    "Sigma",
    "sigma",
    "sin",
    "sqrt",
    "subset",
    "subseteq",
    "sum",
    "tan",
    "tau",
    "text",
    "tfrac",
    "Theta",
    "theta",
    "tilde",
    "times",
    "to",
    "underline",
    "upsilon",
    "vec",
    "Xi",
    "xi",
    "zeta",
)
_DELIMITERLESS_MATH = re.compile(
    r"(?:"
    # Braced subscript/superscript token (chained): r_{t-1}, P_{t+5}^{2}, ...
    r"[A-Za-z][A-Za-z0-9]*"
    r"(?:[_^]\{[^{}]+\})+"
    r"(?:[A-Za-z0-9]*[_^]\{[^{}]+\})*"
    r"|"
    # Backslash macro from the allow-list, optionally followed by braced
    # args. Greek letters / operators (``\alpha``, ``\cdot``) need no args;
    # 2D structural macros (``\frac``, ``\binom``) need up to two; cap at
    # three so the pattern stays bounded.
    r"\\(?:" + "|".join(_MACRO_NAMES) + r")(?![A-Za-z])"
    r"(?:\{[^{}]*\}){0,3}"
    r")"
)


def extract_and_render_inline(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(kind, payload)`` tuples for each segment of ``text``.

    ``kind`` is one of:
      * ``"text"`` — payload is the literal substring.
      * ``"inline_math"`` — payload is the rendered Unicode string.
      * ``"block_math"`` — payload is the rendered (possibly multi-line)
        Unicode string.

    Block math takes precedence over inline math at the same position
    (matches the docs-site MarkdownLite priority).
    """
    if not text:
        return

    # Build a single match-stream: block segments first, then inline,
    # then resolve by earliest start position. ``\begin{env}`` matches
    # capture the env name in group 1 and the body in group 2; the other
    # patterns capture the body in group 1.
    matches: list[tuple[int, int, str, str]] = []  # (start, end, kind, inner)
    for m in _BLOCK_DOLLAR.finditer(text):
        matches.append((m.start(), m.end(), "block_math", m.group(1)))
    for m in _BLOCK_BRACKET.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        matches.append((m.start(), m.end(), "block_math", m.group(1)))
    for m in _BLOCK_ENV.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        matches.append((m.start(), m.end(), "block_math", m.group(2)))
    for m in _INLINE_DOLLAR.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        matches.append((m.start(), m.end(), "inline_math", m.group(1)))
    for m in _INLINE_PAREN.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        matches.append((m.start(), m.end(), "inline_math", m.group(1)))
    # Last-resort heuristic: catch bare LaTeX tokens (braced sub/sup or
    # allow-listed macro) that arrived without surrounding delimiters.
    for m in _DELIMITERLESS_MATH.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        matches.append((m.start(), m.end(), "inline_math", m.group(0)))
    matches.sort(key=lambda t: t[0])

    pos = 0
    for start, end, kind, inner in matches:
        if start > pos:
            yield ("text", text[pos:start])
        block = kind == "block_math"
        yield (kind, render_latex(inner, block=block).plain)
        pos = end
    if pos < len(text):
        yield ("text", text[pos:])


def _overlaps(start: int, end: int, matches: list[tuple[int, int, str, str]]) -> bool:
    """True when ``start``/``end`` intersects any accepted match span."""
    return any(start < e and s < end for s, e, _, _ in matches)

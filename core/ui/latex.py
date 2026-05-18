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
_SUBSCRIPT_MAP: Final[dict[str, str]] = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
}
_SUPERSCRIPT_MAP: Final[dict[str, str]] = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "A": "ᴬ",
    "B": "ᴮ",
    "D": "ᴰ",
    "E": "ᴱ",
    "G": "ᴳ",
    "H": "ᴴ",
    "I": "ᴵ",
    "J": "ᴶ",
    "K": "ᴷ",
    "L": "ᴸ",
    "M": "ᴹ",
    "N": "ᴺ",
    "O": "ᴼ",
    "P": "ᴾ",
    "R": "ᴿ",
    "T": "ᵀ",
    "U": "ᵁ",
    "V": "ⱽ",
    "W": "ᵂ",
    "a": "ᵃ",
    "b": "ᵇ",
    "c": "ᶜ",
    "d": "ᵈ",
    "e": "ᵉ",
    "f": "ᶠ",
    "g": "ᵍ",
    "h": "ʰ",
    "i": "ⁱ",
    "j": "ʲ",
    "k": "ᵏ",
    "l": "ˡ",
    "m": "ᵐ",
    "n": "ⁿ",
    "o": "ᵒ",
    "p": "ᵖ",
    "r": "ʳ",
    "s": "ˢ",
    "t": "ᵗ",
    "u": "ᵘ",
    "v": "ᵛ",
    "w": "ʷ",
    "x": "ˣ",
    "y": "ʸ",
    "z": "ᶻ",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
}
_GREEK_WORD_BASES: Final[frozenset[str]] = frozenset(
    {
        "Alpha",
        "Beta",
        "Gamma",
        "Delta",
        "Epsilon",
        "Lambda",
        "Omega",
        "Phi",
        "Pi",
        "Psi",
        "Sigma",
        "Theta",
        "Xi",
        "alpha",
        "beta",
        "chi",
        "delta",
        "epsilon",
        "eta",
        "gamma",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
        "omega",
        "phi",
        "pi",
        "psi",
        "rho",
        "sigma",
        "tau",
        "theta",
        "upsilon",
        "xi",
        "zeta",
    }
)
_SCRIPT_CHAR_CLASS: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-="
_UNICODE_SCRIPT = re.compile(
    rf"(?P<marker>[_^])(?:\{{(?P<braced>[^{{}}\n]+)\}}|"
    r"\((?P<parenthesized>[^()\n]+)\)|"
    rf"(?P<bare>[{re.escape(_SCRIPT_CHAR_CLASS)}]+))"
)
_DIGIT_BASE_GROUPED_SUPERSCRIPT = re.compile(
    r"(?P<base>\d+)\^(?:\{(?P<braced>[^{}\n]+)\}|\((?P<parenthesized>[^()\n]+)\))"
)


def _has_tier2_construct(src: str) -> bool:
    """True when ``src`` contains a 2D math construct worth pretty-printing."""
    return any(tok in src for tok in _TIER2_TOKENS)


def _apply_unicode_scripts(text: str) -> str:
    """Rewrite terminal-friendly ``_`` / ``^`` script tokens."""
    if not text:
        return text
    if _LATEX_LINEBREAK_SENTINEL in text:
        return _LATEX_LINEBREAK_SENTINEL.join(
            _apply_unicode_scripts(part) for part in text.split(_LATEX_LINEBREAK_SENTINEL)
        )

    def replace(match: re.Match[str]) -> str:
        marker = match.group("marker")
        braced = match.group("braced")
        parenthesized = match.group("parenthesized")
        bare = match.group("bare")
        if marker == "^" and (braced is not None or parenthesized is not None):
            converted = _convert_grouped_superscript_payload(braced or parenthesized or "")
            if converted is None:
                return match.group(0)
            if parenthesized is not None:
                return f"{_SUPERSCRIPT_MAP['(']}{converted}{_SUPERSCRIPT_MAP[')']}"
            return converted

        token = braced or bare
        if parenthesized is not None:
            token = f"({parenthesized})"
        if not token:
            log.debug("Unexpected empty LaTeX script token in %r", match.group(0))
            return match.group(0)

        script_map = _SUBSCRIPT_MAP if marker == "_" else _SUPERSCRIPT_MAP
        mapped = [script_map.get(ch) for ch in token]
        if any(ch is None for ch in mapped):
            fallback = _unsupported_script_presentation(text, match, token, mapped)
            if fallback is None:
                return match.group(0)
            return fallback
        return "".join(ch for ch in mapped if ch is not None)

    return _UNICODE_SCRIPT.sub(replace, text)


def _prepare_digit_base_grouped_superscripts(src: str) -> tuple[str, dict[str, str]]:
    """Pre-convert digit-base grouped superscripts before pylatexenc strips braces."""
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        parenthesized = match.group("parenthesized")
        payload = match.group("braced") or parenthesized or ""
        converted = _convert_grouped_superscript_payload(payload)
        if converted is None:
            sentinel = f"<<<GEODE_LATEX_SCRIPT_{len(protected)}>>>"
            protected[sentinel] = match.group(0)
            return sentinel
        if parenthesized is not None:
            converted = f"{_SUPERSCRIPT_MAP['(']}{converted}{_SUPERSCRIPT_MAP[')']}"
        return f"{match.group('base')}{converted}"

    return _DIGIT_BASE_GROUPED_SUPERSCRIPT.sub(replace, src), protected


def _convert_grouped_superscript_payload(payload: str) -> str | None:
    """Convert a braced/parenthesized superscript payload as one script unit.

    Nested markers inside a superscript group inherit the outer superscript
    direction: ``R_j`` in ``^(R_j)`` becomes ``ᴿʲ`` rather than ``ᴿⱼ``.
    Whitespace inside the group is presentation-only and is dropped because
    Unicode has no portable superscript space.
    """
    converted: list[str] = []
    pos = 0
    while pos < len(payload):
        ch = payload[pos]
        if ch.isspace():
            pos += 1
            continue
        if ch in "_^":
            token, next_pos = _read_script_token(payload, pos + 1)
            if token is None:
                return None
            mapped_token = _map_script_chars(token, _SUPERSCRIPT_MAP)
            if mapped_token is None:
                return None
            converted.append(mapped_token)
            pos = next_pos
            continue
        mapped_ch = _SUPERSCRIPT_MAP.get(ch)
        if mapped_ch is None:
            return None
        converted.append(mapped_ch)
        pos += 1
    return "".join(converted)


def _read_script_token(payload: str, start: int) -> tuple[str | None, int]:
    """Read a nested script token from ``payload`` starting after `_`/`^`."""
    if start >= len(payload):
        return None, start
    opener = payload[start]
    if opener in "({":
        closer = ")" if opener == "(" else "}"
        end = payload.find(closer, start + 1)
        if end == -1:
            return None, start
        return payload[start + 1 : end], end + 1

    end = start
    while end < len(payload) and payload[end] in _SCRIPT_CHAR_CLASS:
        end += 1
    if end == start:
        return None, start
    return payload[start:end], end


def _map_script_chars(token: str, script_map: dict[str, str]) -> str | None:
    """Return ``token`` mapped through ``script_map`` or ``None`` atomically."""
    mapped = [script_map.get(ch) for ch in token]
    if any(ch is None for ch in mapped):
        return None
    return "".join(ch for ch in mapped if ch is not None)


def _unsupported_script_presentation(
    text: str,
    match: re.Match[str],
    token: str,
    mapped: list[str | None],
) -> str | None:
    """Return a conservative no-raw-marker fallback for unsupported scripts."""
    if match.group("marker") == "^" and (
        match.group("braced") is not None or match.group("parenthesized") is not None
    ):
        return None
    if token.isascii() and token.isalpha() and token.islower() and len(token) > 1:
        return None
    has_partial_mapping = any(ch is not None for ch in mapped)
    if has_partial_mapping and mapped.count(None) > len(mapped) // 2:
        return None
    if not has_partial_mapping and not (
        _script_base_looks_math(text, match.start())
        or _has_single_uppercase_latin_base_script(text, match.start(), token)
    ):
        return None

    # Unicode has no uppercase Latin subscript alphabet. Bracketing preserves
    # the script as a unit (τ[P]) without pretending the base identifier is τP.
    payload = "".join(
        mapped_ch if mapped_ch is not None else raw_ch
        for raw_ch, mapped_ch in zip(token, mapped, strict=True)
    )
    return f"[{payload}]"


def _script_base_looks_math(text: str, marker_start: int) -> bool:
    """True when an unsupported script is attached to a Greek/math base."""
    if marker_start <= 0:
        return False
    prev = text[marker_start - 1]
    if prev in _UNICODE_MATH_GLYPHS:
        return True

    left = marker_start
    while left > 0 and text[left - 1].isalpha():
        left -= 1
    return text[left:marker_start] in _GREEK_WORD_BASES


def _has_single_uppercase_latin_base_script(text: str, marker_start: int, token: str) -> bool:
    """True for unsupported uppercase scripts on a one-letter Latin variable."""
    if marker_start <= 0:
        return False
    prev = text[marker_start - 1]
    if not ("A" <= prev <= "Z"):
        return False
    if not token or not all("A" <= ch <= "Z" for ch in token):
        return False
    # Relax only for single-letter variables like P_T; multi-letter acronym
    # bases such as IBM_T remain raw prose/identifier text.
    return marker_start == 1 or not text[marker_start - 2].isalnum()


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
        src, protected_scripts = _prepare_digit_base_grouped_superscripts(src)
        protected_src = _LATEX_LINEBREAK.sub(
            f" {_LATEX_LINEBREAK_SENTINEL} ",
            src,
        )
        raw: str = LatexNodes2Text().latex_to_text(protected_src).strip()
        for sentinel, original in protected_scripts.items():
            raw = raw.replace(sentinel, original)
        raw = _apply_unicode_scripts(raw)
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
# ordinary ``snake_case`` identifiers, file paths, Markdown code, and
# Markdown emphasis remain untouched:
#
#   * **Braced subscript/superscript token** — ``r_{t-1}``, ``P_{t+5}``,
#     ``x^{2}``, ``W_{i,j}^{T}``. Requires `{…}` directly after `_` or `^`.
#   * **Backslash macro with at least one braced arg** — ``\frac{a}{b}``,
#     ``\sqrt{x+1}``, ``\bar{S}``, ``\hat{y}``, ``\sum_{i=1}``. A small
#     allow-list of macro names keeps the pattern from over-firing on
#     prose like ``\n`` escape sequences.
#
# Bare script forms (``r_t``, ``x^2``) are accepted only when the candidate
# sits in a math-shaped line context and the script payload looks index-like
# (``t``, ``i,j``, ``t-9:t``), not word-like (``case``, ``name``). This
# catches LLM formula leaks while continuing to skip ordinary identifiers.

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
_UNICODE_MATH_GLYPHS: Final = (
    "√∑∫∏≤≥→←⇒⇐↔∞≈≠±×÷∈∉⊂⊆∂∇ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω"
)
_PATH_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}\b")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_MATH_SCRIPT_SEGMENT = re.compile(r"[A-Za-z]_[A-Za-z0-9](?:,[A-Za-z0-9]+)?")
_SCRIPT_CHARS = "A-Za-z0-9" + re.escape(_UNICODE_MATH_GLYPHS + ",:-")
_SCRIPT_BODY = rf"(?:\([^()`\n]+\)|[{_SCRIPT_CHARS}]+)"
_UNICODE_TOKEN_HEAD = (
    rf"(?:[A-Za-z0-9]*[{re.escape(_UNICODE_MATH_GLYPHS)}][A-Za-z0-9]+"
    rf"|[A-Za-z0-9]+[{re.escape(_UNICODE_MATH_GLYPHS)}][A-Za-z0-9]*"
    rf"|[{re.escape(_UNICODE_MATH_GLYPHS)}](?:[_^]{_SCRIPT_BODY}))"
)
_DELIMITERLESS_MATH = re.compile(
    r"(?:"
    # Braced subscript/superscript token (chained): r_{t-1}, 10^{2}, ...
    r"(?:[A-Za-z][A-Za-z0-9]*|\d+)"
    r"(?:[_^]\{[^{}]+\})+"
    r"(?:[A-Za-z0-9]*[_^]\{[^{}]+\})*"
    r"|"
    # Backslash macro from the allow-list, optionally followed by braced
    # args. Greek letters / operators (``\alpha``, ``\cdot``) need no args;
    # 2D structural macros (``\frac``, ``\binom``) need up to two; cap at
    # three so the pattern stays bounded.
    r"\\(?:" + "|".join(_MACRO_NAMES) + r")(?![A-Za-z])"
    r"(?:\{[^{}]*\}){0,3}"
    r"|"
    # Bare script token in math-shaped context: y^ΔT_t,n, 10^2,
    # S^(i)_t,n, close_t,n, X_t-9:t,n,:. Filtered by
    # _delimiterless_candidate_allowed.
    r"(?:[A-Za-z][A-Za-z0-9]*|\d+)"
    rf"(?:[_^]{_SCRIPT_BODY})+"
    r"|"
    # Unicode math glyph adjacent to letters/digits/scripts: √x, α_i, ΔT,n.
    rf"{_UNICODE_TOKEN_HEAD}"
    rf"(?:[_^]{_SCRIPT_BODY})?"
    r"(?:,[A-Za-z0-9]+)*"
    r")"
)
_SCRIPT_PART = re.compile(rf"[_^]({_SCRIPT_BODY})")
_FENCED_CODE_BLOCK = re.compile(r"(?m)^(```|~~~)[^\n]*\n[\s\S]*?^\1\s*$")
_INLINE_CODE_SPAN = re.compile(r"`[^`\n]*`")


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
    code_spans = _markdown_code_spans(text)
    # Last-resort heuristic: catch bare LaTeX tokens that arrived without
    # surrounding delimiters.
    for m in _DELIMITERLESS_MATH.finditer(text):
        if _overlaps(m.start(), m.end(), matches):
            continue
        if _span_overlaps(m.start(), m.end(), code_spans):
            continue
        if not _delimiterless_candidate_allowed(text, m.start(), m.end(), m.group(0)):
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


def _span_overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """True when ``start``/``end`` intersects any protected span."""
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _markdown_code_spans(text: str) -> list[tuple[int, int]]:
    """Return fenced-code and inline-code spans protected from fallback math."""
    spans: list[tuple[int, int]] = [(m.start(), m.end()) for m in _FENCED_CODE_BLOCK.finditer(text)]
    for m in _INLINE_CODE_SPAN.finditer(text):
        if not _span_overlaps(m.start(), m.end(), spans):
            spans.append((m.start(), m.end()))
    return spans


def _delimiterless_candidate_allowed(text: str, start: int, end: int, token: str) -> bool:
    """Filter broad fallback matches down to math-shaped delimiterless tokens."""
    if _looks_like_path_context(text, start, end):
        return False
    if token.startswith("\\") or "{" in token:
        return True
    if any(ch in _UNICODE_MATH_GLYPHS for ch in token):
        return True
    if "_" in token or "^" in token:
        if token[0].isdigit():
            return "^" in token and _script_parts_look_index_like(token)
        return _script_parts_look_index_like(token) and _has_math_context(text, start, end, token)
    return False


def _looks_like_path_context(text: str, start: int, end: int) -> bool:
    """Reject tokens embedded in filename or slash-path context."""
    left = start
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    right = end
    while right < len(text) and not text[right].isspace():
        right += 1
    surrounding = text[left:right]
    if "/" not in surrounding:
        return bool(_PATH_EXTENSION.search(surrounding))
    if surrounding.startswith(("/", "./", "../", "~/")):
        return True
    if _PATH_EXTENSION.search(surrounding) and _slash_segments_look_pathish(surrounding):
        return True
    return surrounding.count("/") >= 2 and _slash_segments_look_pathish(surrounding)


def _slash_segments_look_pathish(surrounding: str) -> bool:
    """True for slash runs made of path segments, false for formula fractions."""
    segments = [segment for segment in surrounding.split("/") if segment]
    if len(segments) < 2:
        return False
    if not all(_PATH_SEGMENT.fullmatch(segment) for segment in segments):
        return False
    if all(_MATH_SCRIPT_SEGMENT.fullmatch(segment) for segment in segments):
        return False
    return any(any(ch.isalpha() for ch in segment) and len(segment) > 1 for segment in segments)


def _script_parts_look_index_like(token: str) -> bool:
    """Reject word-like bare subscripts such as ``snake_case`` and ``file_name``."""
    for match in _SCRIPT_PART.finditer(token):
        raw = match.group(1).strip("()")
        for part in re.split(r"[,:-]+", raw):
            if not part:
                continue
            if part.isascii() and part.isalpha() and part.islower() and len(part) > 1:
                return False
    return True


def _has_math_context(text: str, start: int, end: int, token: str) -> bool:
    """True when a bare script token is adjacent to formula punctuation."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]

    prev_char = _previous_nonspace(text, line_start, start)
    next_char = _next_nonspace(text, end, line_end)
    if prev_char in "=+-*/(,":
        return True
    if next_char in "=+-*/),":
        return True
    if any(op in token for op in ("-", ":", ",")) and any(op in line for op in "=+-*/"):
        return True
    return "^" in token and "=" in line


def _previous_nonspace(text: str, lower: int, start: int) -> str:
    pos = start - 1
    while pos >= lower and text[pos].isspace():
        pos -= 1
    return text[pos] if pos >= lower else ""


def _next_nonspace(text: str, start: int, upper: int) -> str:
    pos = start
    while pos < upper and text[pos].isspace():
        pos += 1
    return text[pos] if pos < upper else ""

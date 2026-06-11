"""CJK-safe Markdown emphasis preprocessing for terminal rendering.

CommonMark's flanking rules reject ``**`` emphasis when the closing
delimiter is preceded by punctuation and followed by a letter with no
space between — the everyday Korean shapes ``**[추정]**이지만`` and
``**"인용"**로`` both parse as literal asterisks (verified against
rich/markdown-it, 2026-06-11 operator report). English rarely hits this
because a space or punctuation follows the closer; Korean particles
attach directly.

The fix pads the inside of every ``**…**`` span with U+200B ZERO WIDTH
SPACE. ZWSP is neither Unicode whitespace nor punctuation under
CommonMark, so a delimiter next to it is always flanking-valid; the
character itself renders zero-width in the terminal. Code regions
(fenced blocks and inline code spans) are left untouched so literal
``**`` inside code survives.
"""

from __future__ import annotations

import re

_ZWSP = "​"

# Fenced code blocks (``` or ~~~, any info string) and inline code spans.
# Inline-code backtick runs must match in length (CommonMark), captured
# via the backreference.
_CODE_REGION = re.compile(
    r"(?P<fence>^(?:```|~~~)[^\n]*\n.*?^(?:```|~~~)[ \t]*$)"
    r"|(?P<inline>(?P<ticks>`+)[^`]*?(?P=ticks))",
    re.DOTALL | re.MULTILINE,
)

# A strong-emphasis span on one line: non-space right after the opener,
# non-space right before the closer, no `**` inside.
_STRONG_SPAN = re.compile(r"\*\*(?=\S)((?:[^*\n]|\*(?!\*))+?)(?<=\S)\*\*")


def _pad_strong_spans(segment: str) -> str:
    return _STRONG_SPAN.sub(f"**{_ZWSP}\\1{_ZWSP}**", segment)


def cjk_safe_emphasis(text: str) -> str:
    """Return *text* with ``**…**`` spans made CJK-flanking-safe.

    Only prose is transformed; fenced code blocks and inline code spans
    pass through byte-identical.
    """
    if "**" not in text:
        return text

    pieces: list[str] = []
    last_end = 0
    for code_match in _CODE_REGION.finditer(text):
        pieces.append(_pad_strong_spans(text[last_end : code_match.start()]))
        pieces.append(code_match.group(0))
        last_end = code_match.end()
    pieces.append(_pad_strong_spans(text[last_end:]))
    return "".join(pieces)

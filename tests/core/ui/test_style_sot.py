"""Style SoT drift guards — PR-UI-STYLE-SOT (2026-07-06).

Three ratchets keep the CLI style system centralized in ``core.ui.palette``:

1. **No inline escapes** — the swept renderer modules must not grow new raw
   ``\\033[`` / ``\\x1b[`` literals. Every style/control sequence comes from
   the palette. Allowed exceptions are pinned per file (the ANSI *strip*
   regex, and spinner_glyph's dynamic truecolor rose which is the documented
   animation-owned exception).
2. **Hex parity** — ``console.py`` must not restate brand hex values; the
   Rich theme derives from the palette anchors (no dual SoT).
3. **Token value pins** — palette token values are part of the visual
   contract; changing one is a deliberate re-skin, not a refactor side
   effect.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.ui import palette

_REPO = Path(__file__).parents[3]
_UI = _REPO / "core" / "ui"

# source spellings AND a literal ESC byte; chr(27)/split-concat bypasses are
# noted as accepted porosity (no cheap static catch) — reviewers watch those.
_ESCAPE_LITERAL = re.compile(r"\\033\[|\\x1b\[|\\u001b\[|\x1b\[|chr\(27\)")

# file → substrings identifying the ONLY lines allowed to carry a raw escape
_SWEPT: dict[str, tuple[str, ...]] = {
    "event_renderer.py": ('_ANSI_ESCAPE = re.compile(r"\\x1b',),
    "tool_tracker.py": (),
    "status.py": (),
    "spinner_glyph.py": ('f"\\x1b[1;38;2;',),  # dynamic rose truecolor (animation-owned)
}


def test_no_inline_escapes_outside_palette() -> None:
    offenders: list[str] = []
    for name, allowed in _SWEPT.items():
        for lineno, line in enumerate((_UI / name).read_text().splitlines(), 1):
            if not _ESCAPE_LITERAL.search(line):
                continue
            if any(marker in line for marker in allowed):
                continue
            offenders.append(f"{name}:{lineno}: {line.strip()[:80]}")
    assert not offenders, (
        "raw ANSI escape literals found outside core/ui/palette.py — "
        "use palette tokens instead:\n" + "\n".join(offenders)
    )


def test_console_does_not_restate_brand_hexes() -> None:
    src = (_UI / "console.py").read_text()
    inline_hexes = re.findall(r'"#[0-9a-fA-F]{6}"', src)
    assert inline_hexes == [], (
        f"console.py restates hex literals {inline_hexes} — import from core.ui.palette"
    )


def test_theme_brand_styles_derive_from_palette() -> None:
    from core.ui.console import GEODE_THEME

    assert palette.CORAL in str(GEODE_THEME.styles["brand"].color.name)
    assert palette.MAGENTA in str(GEODE_THEME.styles["brand.accent"].color.name)
    assert palette.GOLD in str(GEODE_THEME.styles["brand.gold"].color.name)
    assert palette.CRYSTAL in str(GEODE_THEME.styles["brand.crystal"].color.name)
    assert palette.CYAN in str(GEODE_THEME.styles["header"].color.name)
    assert palette.CYAN in str(GEODE_THEME.styles["success"].color.name)
    assert palette.CYAN in str(GEODE_THEME.styles["step"].color.name)
    assert palette.CYAN in str(GEODE_THEME.styles["tier_b"].bgcolor.name)


def test_sgr_token_values_pinned() -> None:
    """Byte-identical to the literals the 2026-07-06 sweep replaced —
    changing one is a deliberate re-skin decision, made here on purpose."""
    assert palette.RESET == "\033[0m"
    assert palette.BOLD == "\033[1m"
    assert palette.DIM == "\033[2m"
    assert palette.FAINT == "\033[90m"
    assert palette.DONE_STRIKE == "\033[2;9m"
    assert palette.OK == "\033[36m"
    assert palette.OK_BOLD == "\033[1;36m"
    assert palette.FAIL == "\033[31m"
    assert palette.ERROR == "\033[1;31m"
    assert palette.NOTICE == "\033[33m"
    assert palette.WARN == "\033[1;33m"
    assert palette.HIGHLIGHT == "\033[1;93m"
    assert palette.INFO == "\033[36m"
    assert palette.SECTION == "\033[1;36m"
    assert palette.ACCENT == "\033[1;35m"
    assert palette.LINK == "\033[94m"
    assert palette.DELEGATE == "\033[1;34m"
    assert palette.ERASE_LINE == "\033[2K"
    assert palette.ERASE_EOL == "\033[K"
    assert palette.cursor_up(3) == "\033[3A"
    assert palette.cursor_down(1) == "\033[1B"


def test_no_denormalized_sgr_spellings() -> None:
    """``36;1`` / ``34;1`` (parameter-order variants of 1;36 / 1;34) must not
    reappear — one spelling per style."""
    for name in _SWEPT:
        src = (_UI / name).read_text()
        assert "36;1m" not in src, f"{name} uses denormalized 36;1m"
        assert "34;1m" not in src, f"{name} uses denormalized 34;1m"


def test_glyph_vocabulary_pinned() -> None:
    assert palette.GLYPH_OK == "✓"
    assert palette.GLYPH_FAIL == "✗"
    assert palette.GLYPH_ARROW == "→"
    assert palette.GLYPH_DELEGATE == "▸"
    assert palette.GLYPH_RESULT == "⎿"
    assert palette.GLYPH_CYCLE == "⟳"
    assert palette.GLYPH_THOUGHT == "✦"
    assert palette.GLYPH_REASONING == "∙"
    assert palette.GLYPH_TURN == "✢"
    assert palette.GLYPH_SWITCH == "⇄"
    assert palette.GLYPH_TODO == "○"

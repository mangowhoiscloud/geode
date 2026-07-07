"""GEODE CLI style SoT — brand hexes, raw-SGR tokens, glyph vocabulary, metrics.

PR-UI-STYLE-SOT (2026-07-06). The CLI had two disconnected style systems:
the Rich theme in ``core/ui/console.py`` (brand hexes, semantic style names)
and the raw-ANSI thin-client path (``event_renderer`` / ``tool_tracker`` /
``status``) which inlined 150+ escape literals across 17 distinct codes —
including the same style written two ways (``36;1`` vs ``1;36``). This module
is the single anchor both sides derive from:

- **Brand hexes** — consumed by ``console.py`` to build ``GEODE_THEME`` and by
  any Rich-markup caller. One hex table; the theme must not restate values
  (drift invariant pinned by ``tests/core/ui/test_style_sot.py``).
- **SGR tokens** — consumed by the raw-ANSI path, which stays Rich-free (the
  thin client must not import the Rich tree). Token VALUES are byte-identical
  to the literals they replaced, so this centralization is zero-visual-diff
  by construction. Re-skinning the raw path onto the brand truecolor hexes is
  now a one-line-per-semantic value change here — deliberately NOT done in
  the same PR (visual changes need operator eyes).
- **Glyphs** — the symbol vocabulary of the turn renderer. The animated GEODE
  mark (``◆`` + rose shimmer) stays in ``core/ui/spinner_glyph.py``, which is
  the documented SoT for the spinner identity; this table holds the static
  marks.
- **Metrics** — truncation widths and terminal-width floors that were
  scattered as bare integers.

Guard: ``tests/core/ui/test_style_sot.py`` bans raw ``\\033[`` / ``\\x1b[``
literals in the swept modules (ratchet — new inline escapes fail CI) and pins
theme↔palette hex parity.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Brand palette (axolotl mascot, toned-down for readability)
# ---------------------------------------------------------------------------

CORAL = "#d4a0a0"  # axolotl body (muted rose)
GOLD = "#e0b040"  # headlamp (warm amber)
CYAN = "#5f9ea0"  # crystals / tech (calm cadet)
MAGENTA = "#9775c4"  # gills / accent (soft iris)
CRYSTAL = "#a88fd4"  # geode crystal (muted lavender)

# ---------------------------------------------------------------------------
# SGR style tokens (raw-ANSI path)
# ---------------------------------------------------------------------------
# Semantic name → the exact code the renderer historically emitted. ``36;1``
# and ``34;1`` are normalized to the canonical ``1;36`` / ``1;34`` parameter
# order (identical rendering; one spelling).

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"  # secondary metadata, gutters, timings
FAINT = "\033[90m"  # collapsed-thinking header, reasoning dot
DONE_STRIKE = "\033[2;9m"  # completed plan step in the windowed checklist

OK = "\033[36m"  # tool/subagent success marks (GEODE cyan)
OK_BOLD = "\033[1;36m"  # OAuth success line (GEODE cyan)
FAIL = "\033[31m"  # per-item failure marks
ERROR = "\033[1;31m"  # critical: billing, cost exceeded, convergence
NOTICE = "\033[33m"  # context exhausted, soft cautions
WARN = "\033[1;33m"  # budget/retry/time-budget/model-switch warnings
HIGHLIGHT = "\033[1;93m"  # OAuth device code
INFO = "\033[36m"  # command hints
SECTION = "\033[1;36m"  # pipeline section marks, OAuth header
ACCENT = "\033[1;35m"  # top-tier (S) pipeline mark
LINK = "\033[94m"  # URLs
DELEGATE = "\033[1;34m"  # sub-agent dispatch mark

# ---------------------------------------------------------------------------
# Terminal control tokens
# ---------------------------------------------------------------------------

ERASE_LINE = "\033[2K"  # erase entire line (live-region repaint)
ERASE_EOL = "\033[K"  # erase to end of line


def cursor_up(rows: int) -> str:
    """Move the cursor up ``rows`` lines (live-region repaint)."""
    return f"\033[{rows}A"


def cursor_down(rows: int) -> str:
    """Move the cursor down ``rows`` lines."""
    return f"\033[{rows}B"


# ---------------------------------------------------------------------------
# Glyph vocabulary (static marks; the animated ◆ lives in spinner_glyph)
# ---------------------------------------------------------------------------

GLYPH_OK = "✓"
GLYPH_FAIL = "✗"
GLYPH_ARROW = "→"
GLYPH_DELEGATE = "▸"  # sub-agent dispatch + pipeline section marks
GLYPH_RESULT = "⎿"  # nested continuation/result line
GLYPH_CYCLE = "⟳"  # context compaction, convergence, diversity notices
GLYPH_THOUGHT = "✦"  # collapsed thinking header
GLYPH_REASONING = "∙"  # streamed reasoning-summary line
GLYPH_TURN = "✢"  # turn-status footer
GLYPH_SWITCH = "⇄"  # model switch
GLYPH_TODO = "○"  # pending plan step
GLYPH_CANCEL = "✕"
GLYPH_TIMER = "⏱"
# ↓ / ↑ (token in/out direction marks) are deliberately left inline at their
# call sites: single spelling, data-adjacent, shared verbatim by the Rich and
# raw paths — tokenizing them adds churn without removing a drift surface.

# ---------------------------------------------------------------------------
# Metrics — truncation widths / terminal-width floors (raw-ANSI path)
# ---------------------------------------------------------------------------

TRUNCATE_SUMMARY = 60  # activity summary + tool result head
TRUNCATE_TOOL_ARGS = 50  # running-row args preview
TRUNCATE_THINKING_LABEL = 48
TRUNCATE_FLEET_ROLE = 24
TRUNCATE_REASONING = 240

MIN_RENDER_WIDTH = 20  # raw-path floor when the terminal reports tiny
FALLBACK_TERMINAL = (80, 24)  # shutil.get_terminal_size fallback

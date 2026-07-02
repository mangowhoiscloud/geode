"""GEODE signature spinner — a steady rose gem with a *shimmer* sweeping the text.

Single source of truth for the animated status line. Every code path that shows
a live "working" spinner imports from here — the direct-mode ``GeodeStatus``
(``core/ui/status.py``) and the IPC thin-client tracker (``core/ui/event_renderer.py``)
— so there is exactly ONE GEODE mark. Do NOT re-define the glyph or the activity
words anywhere else (that fragmentation is what caused the wrong spinner to be
edited before).

Why a shimmer and not a spinning glyph — the lesson from the Codex TUI
(``codex-rs/tui/src/shimmer.rs``) and the Claude Code CLI: cycling a glyph
through *different shapes* reads as mechanical, however you ease it — the eye
sees a flip-book. What reads as *alive* is a continuous brightness wave: the
glyph never changes shape, and a raised-cosine band of light glides left→right
across the whole line. Codex sweeps ``0.5·(1+cos(π·dist/half))`` over its text
every 2s; GEODE does the same, blending a readable rose (base) up to a bright
rose (crest = signature identity, one hue, no rainbow). The wave is a pure
function of elapsed seconds, so it is frame-rate independent and never stutters.

ponytail: truecolor SGR only — most terminals degrade it to the nearest colour;
a 16-colour fallback would be extra code for terminals GEODE rarely runs in.
"""

from __future__ import annotations

import math

RST = "\x1b[0m"
DIM = "\x1b[2m"

GLYPH = "◆"  # the GEODE mark: a rose gem (never changes shape — the wave carries motion)

# Rose identity: readable base -> bright crest. The crest is what sweeps.
_BASE = (206, 128, 162)  # muted-but-legible rose (text at rest)
_CREST = (255, 236, 248)  # bright rose the shimmer band lights up to

_PERIOD = 2.0  # seconds for the band to sweep the full line once
_BAND = 4.0  # band half-width in characters (wider = softer, slower-looking wave)
_PAD = 6  # lead-in/out so the crest glides on from off-screen and off again
_WORD_EVERY = 4.0  # seconds per whimsical word (slow — the shimmer is the motion)

# Whimsical geode/crystal-flavoured activity words — rotate like Claude's spinner.
_GERUNDS = (
    "Crystallizing",
    "Faceting",
    "Percolating",
    "Geologizing",
    "Prospecting",
    "Excavating",
    "Mineralizing",
    "Refracting",
    "Nucleating",
    "Cogitating",
    "Ruminating",
    "Sedimenting",
    "Cleaving",
    "Vitrifying",
    "Effervescing",
    "Contemplating",
    "Synthesizing",
    "Deliberating",
    "Druse-forming",
    "Geodizing",
)


def _rose(level: float) -> str:
    """Bold rose SGR at brightness ``level`` in [0, 1] (0 = base, 1 = crest)."""
    r = round(_BASE[0] + (_CREST[0] - _BASE[0]) * level)
    g = round(_BASE[1] + (_CREST[1] - _BASE[1]) * level)
    b = round(_BASE[2] + (_CREST[2] - _BASE[2]) * level)
    return f"\x1b[1;38;2;{r};{g};{b}m"


# Static signature-rose for non-animated marks (plan active step, etc.):
# raw SGR for direct writers, hex for Rich-markup consumers — one _BASE anchor.
ROSE = _rose(0.0)
ROSE_HEX = f"#{_BASE[0]:02x}{_BASE[1]:02x}{_BASE[2]:02x}"


def shimmer(text: str, elapsed: float) -> str:
    """``text`` in rose with a bright band gliding across it at ``elapsed`` seconds.

    Each character is coloured by its distance to a sweeping crest — a
    raised-cosine falloff, so the light has soft edges and moves continuously
    rather than stepping. The glyph shape never changes; the wave is the motion.
    """
    chars = list(text)
    n = len(chars)
    if n == 0:
        return ""
    span = n + _PAD * 2
    crest = (elapsed % _PERIOD) / _PERIOD * span  # crest position, incl. padding
    out = []
    for i, ch in enumerate(chars):
        dist = abs((i + _PAD) - crest)
        level = 0.5 * (1.0 + math.cos(math.pi * dist / _BAND)) if dist <= _BAND else 0.0
        out.append(f"{_rose(level)}{ch}")
    out.append(RST)
    return "".join(out)


def gerund(elapsed: float) -> str:
    """Rotating activity word — changes slowly so the shimmer is the primary motion."""
    return _GERUNDS[int(elapsed / _WORD_EVERY) % len(_GERUNDS)]


def elapsed(seconds: float) -> str:
    """``12s`` / ``1m 05s`` — the live timer suffix shared by both spinners."""
    s = int(seconds)
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def _check() -> None:
    """ponytail: crest moves (not fixed), glyph shape never changes, timer fmts."""
    a = shimmer("◆ Working", 0.0)
    b = shimmer("◆ Working", _PERIOD / 3)
    assert a != b, "shimmer band must move over time"
    # the glyph shape is constant — only colour varies
    assert shimmer(GLYPH, 0.0).count(GLYPH) == 1 and shimmer(GLYPH, 1.0).count(GLYPH) == 1
    assert gerund(0.0) != gerund(_WORD_EVERY), "word must rotate"
    assert elapsed(9) == "9s" and elapsed(65) == "1m 05s"


if __name__ == "__main__":
    _check()
    # Live preview: python -m core.ui.spinner_glyph
    import sys
    import time

    start = time.monotonic()
    try:
        while True:
            el = time.monotonic() - start
            body = shimmer(f"{GLYPH} {gerund(el)}…", el)
            sys.stdout.write(f"\r\x1b[2K  {body} {DIM}({elapsed(el)}){RST}")
            sys.stdout.flush()
            time.sleep(0.05)
    except KeyboardInterrupt:
        sys.stdout.write("\r\x1b[2K")

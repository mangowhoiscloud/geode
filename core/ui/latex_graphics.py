"""Tier 3 LaTeX rendering — image inline via terminal graphics protocols.

Why this module
---------------
The 5-tier survey of CLI LaTeX rendering (`docs/audits/2026-05-16-cli-
latex-frontier.md`, when written) places GEODE in **Tier 1 + Tier 2**
(pylatexenc Unicode + SymPy ASCII pretty), with no LLM CLI in **Tier 3**
(image inline via Kitty / SIXEL graphics protocols). Adding Tier 3
puts GEODE alone in the 4-tier intersection.

This module is the **scaffold**:

  * :func:`detect_graphics_capability` — runtime detection of the host
    terminal's graphics support. Returns one of ``"kitty"``, ``"sixel"``,
    or ``None``. Pure environment / TERM probe — never spawns a
    subprocess, never opens a TTY.
  * :func:`render_latex_image` — the *intended* entry point that will
    convert a LaTeX expression into a base64-encoded PNG and emit the
    appropriate terminal escape sequence. Currently raises
    ``NotImplementedError`` so the next PR can wire in matplotlib
    (or a lighter dvipng / mathjax_node alternative) without breaking
    the public API contract.

The Tier 1 / Tier 2 path in :mod:`core.ui.latex` is the runtime default;
Tier 3 only activates when *both* the capability probe returns a known
protocol *and* a future opt-in flag (``GEODE_LATEX_GRAPHICS=1``) is set.
This keeps the next PR's matplotlib import strictly opt-in.

Frontier reference
------------------
- Kitty graphics protocol: https://sw.kovidgoyal.net/kitty/graphics-protocol/
- WezTerm / Ghostty / Konsole adopt the same protocol family.
- SIXEL: xterm, mlterm, foot.
- Tools: `GuyAzene/latex-terminal`, `MaxwellsEquation/LaTerM`,
  `nilqed/latex2sixel`, `Pan-Maciek/LaTeRm`.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final, Literal

log = logging.getLogger(__name__)


GraphicsProtocol = Literal["kitty", "sixel"]


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------
#
# Detection is deliberately conservative — we prefer to *miss* a capability
# (and fall back to Tier 1/2 ASCII art) rather than emit a graphics escape
# sequence into a terminal that prints it as garbled bytes.
#
# Kitty: identified by exact / prefixed ``TERM`` values *or* env vars
# used by terminals that implement the Kitty graphics protocol.
#
# SIXEL: there is no clean env-var probe, so we restrict to a small
# allow-list of terminals known to support it (xterm with ``-ti vt340``,
# mlterm, foot). The ``COLORTERM`` value is *not* a reliable signal.

_KITTY_TERM_VALUES: Final[tuple[str, ...]] = (
    "xterm-kitty",
    "wezterm",
    "ghostty",
    "xterm-ghostty",
)
_KITTY_TERM_PREFIXES: Final[tuple[str, ...]] = (
    "wezterm-",
    "ghostty-",
    "xterm-ghostty-",
)
_KITTY_ENV_VARS: Final[tuple[str, ...]] = (
    "KITTY_WINDOW_ID",
    "WEZTERM_PANE",
    "WEZTERM_EXECUTABLE",
    "GHOSTTY_RESOURCES_DIR",
    "KONSOLE_VERSION",
)
_SIXEL_TERM_VALUES: Final[tuple[str, ...]] = (
    "mlterm",
    "foot",
)
_FORCE_DISABLE_ENV: Final = "GEODE_LATEX_GRAPHICS_DISABLE"
_FORCE_PROTOCOL_ENV: Final = "GEODE_LATEX_GRAPHICS_FORCE"


def detect_graphics_capability() -> GraphicsProtocol | None:
    """Return the host terminal's graphics protocol, or ``None`` if
    no supported protocol is detectable.

    Resolution order:
      1. ``GEODE_LATEX_GRAPHICS_DISABLE`` env — return ``None`` regardless.
      2. ``GEODE_LATEX_GRAPHICS_FORCE`` env (``"kitty"`` / ``"sixel"``)
         — operator override, useful for tests and users on terminals
         the allow-lists below miss.
      3. ``stdout.isatty()`` must be true — never emit graphics into
         a redirected pipe.
      4. Kitty allow-list (TERM value or env var).
      5. SIXEL allow-list.
      6. ``None``.
    """
    if os.environ.get(_FORCE_DISABLE_ENV):
        return None

    forced = os.environ.get(_FORCE_PROTOCOL_ENV, "").strip().lower()
    if forced == "kitty":
        return "kitty"
    if forced == "sixel":
        return "sixel"

    try:
        if not sys.stdout.isatty():
            return None
    except (AttributeError, ValueError):
        return None

    term = os.environ.get("TERM", "").lower()
    if (
        term in _KITTY_TERM_VALUES
        or term.startswith(_KITTY_TERM_PREFIXES)
        or any(os.environ.get(v) for v in _KITTY_ENV_VARS)
    ):
        return "kitty"
    if term in _SIXEL_TERM_VALUES:
        return "sixel"
    return None


# ---------------------------------------------------------------------------
# Image-inline entry point (scaffold)
# ---------------------------------------------------------------------------


def render_latex_image(src: str, *, protocol: GraphicsProtocol) -> str:
    """Convert a LaTeX expression to an inline-graphics escape sequence.

    Currently raises :class:`NotImplementedError`. The follow-up PR will
    wire one of:

      * `matplotlib.mathtext` → PNG → base64 → Kitty ``\\x1b_G…\\x1b\\\\``
        (lightest path; the user already has matplotlib in many envs).
      * `sympy.preview` (uses `dvipng`) → PNG → SIXEL ``\\x1bP…\\x1b\\\\``.

    Until then, the public API contract (signature + return type) is
    pinned so the rest of :mod:`core.ui.latex` can call into Tier 3 by
    name without any future refactor.
    """
    log.debug(
        "Tier 3 image render requested for protocol=%s, src=%r — scaffold only",
        protocol,
        src[:120],
    )
    raise NotImplementedError(
        "Tier 3 image rendering is staged behind a follow-up PR; "
        "callers must check `detect_graphics_capability()` *and* the runtime "
        "opt-in before calling `render_latex_image()`."
    )


# ---------------------------------------------------------------------------
# Opt-in helper
# ---------------------------------------------------------------------------

_GRAPHICS_OPT_IN_ENV: Final = "GEODE_LATEX_GRAPHICS"


def graphics_opt_in_active() -> bool:
    """True when the user has opted in to Tier 3 image rendering.

    The opt-in is intentionally separate from the capability probe so the
    next PR can ship the matplotlib import behind it — users who don't
    set the env var pay zero install / import cost even on a Kitty
    terminal.
    """
    return os.environ.get(_GRAPHICS_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes"}

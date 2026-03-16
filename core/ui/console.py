"""Rich Console singleton — GEODE brand theme.

Brand colors (from axolotl mascot, toned-down for readability):
  Rose (#d4a0a0)     — axolotl body → brand identity (muted coral)
  Amber (#e0b040)    — headlamp → energy, highlights (warm gold)
  Cadet (#5f9ea0)    — crystals, tech → interactive elements (calm cyan)
  Iris (#9775c4)     — gills → accent, tool names (soft purple)
  Lavender (#a88fd4) — geode crystal purple (muted crystal)
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# -- Brand palette (terminal-safe, toned-down) --
_CORAL = "#d4a0a0"  # axolotl body (muted rose)
_GOLD = "#e0b040"  # headlamp (warm amber)
_CYAN = "#5f9ea0"  # crystals / tech (calm cadet)
_MAGENTA = "#9775c4"  # gills / accent (soft iris)
_CRYSTAL = "#a88fd4"  # geode crystal (muted lavender)

GEODE_THEME = Theme(
    {
        # -- Brand --
        "brand": f"bold {_CORAL}",
        "brand.accent": f"bold {_MAGENTA}",
        "brand.gold": f"bold {_GOLD}",
        "brand.crystal": _CRYSTAL,
        # -- Semantic --
        "header": f"bold {_CYAN}",
        "step": "bold green",
        "score": f"bold {_GOLD}",
        "tier_s": "bold white on red",
        "tier_a": "bold white on blue",
        "tier_b": "bold white on green",
        "tier_c": "dim white on grey37",
        "label": "bold",
        "value": _CYAN,
        "warning": f"bold {_GOLD}",
        "error": "bold red",
        "success": "bold green",
        "muted": "dim",
        "status.spinner": _CYAN,
        # -- Agentic UI (Claude Code-style) --
        "tool_name": f"bold {_MAGENTA}",
        "tool_args": f"dim {_CYAN}",
        "token_info": "dim",
        "plan_step": _CYAN,
        "subagent": "bold blue",
        # -- Mascot --
        "mascot.gills": _MAGENTA,
        "mascot.lamp": f"bold {_GOLD}",
        "mascot.body": "white",
        "mascot.outline": "dim",
    }
)

console = Console(theme=GEODE_THEME, width=120)

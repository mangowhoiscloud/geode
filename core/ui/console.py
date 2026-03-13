"""Rich Console singleton — GEODE brand theme.

Brand colors (from axolotl mascot):
  Coral/pink (#f5a0a0)  — axolotl body → brand identity
  Gold (#ffd700)         — headlamp → energy, highlights
  Cyan (#00ced1)         — crystals, tech → interactive elements
  Magenta (#d946ef)      — gills → accent, tool names
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# -- Brand palette (terminal-safe) --
_CORAL = "#f5a0a0"  # axolotl body
_GOLD = "#ffd700"  # headlamp
_CYAN = "#00ced1"  # crystals / tech
_MAGENTA = "#d946ef"  # gills / accent
_CRYSTAL = "#c8a2ff"  # geode crystal purple

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

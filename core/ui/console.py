"""Rich Console singleton."""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

GEODE_THEME = Theme(
    {
        "header": "bold cyan",
        "step": "bold green",
        "score": "bold yellow",
        "tier_s": "bold white on red",
        "tier_a": "bold white on blue",
        "tier_b": "bold white on green",
        "tier_c": "dim white on grey37",
        "label": "bold",
        "value": "cyan",
        "warning": "bold yellow",
        "error": "bold red",
        "success": "bold green",
        "muted": "dim",
        "status.spinner": "cyan",
    }
)

console = Console(theme=GEODE_THEME, width=80)

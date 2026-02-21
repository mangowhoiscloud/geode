"""LLM streaming output with Rich Live display."""

from __future__ import annotations

from rich.live import Live
from rich.text import Text

from geode.llm.client import call_llm_streaming
from geode.ui.console import console


def stream_to_console(
    system: str,
    user: str,
    *,
    prefix: str = "",
    model: str | None = None,
) -> str:
    """Stream LLM output to console, return full text."""
    full_text = ""
    display = Text()
    if prefix:
        display.append(prefix, style="muted")

    with Live(display, console=console, refresh_per_second=15, transient=True):
        for delta in call_llm_streaming(system, user, model=model):
            full_text += delta
            display = Text()
            if prefix:
                display.append(prefix, style="muted")
            display.append(full_text)

    return full_text

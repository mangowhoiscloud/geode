"""LLM streaming output with Rich Live display.

Enhanced streaming panel with token counting, model display,
adapter-agnostic streaming support, and graph-level streaming.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from rich.console import Console as RichConsole
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from geode.infrastructure.ports.llm_port import LLMClientPort
from geode.llm.client import call_llm_streaming, get_usage_accumulator
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


def stream_panel(
    stream: Iterator[str],
    *,
    title: str = "LLM Output",
    model: str = "",
    border_style: str = "cyan",
) -> str:
    """Stream text deltas into a Rich Panel with live progress.

    Args:
        stream: Iterator yielding text deltas.
        title: Panel title.
        model: Model name for display.
        border_style: Rich border style.

    Returns:
        Full accumulated text.
    """
    full_text = ""
    token_estimate = 0
    start_time = time.time()

    def _build_panel() -> Panel:
        elapsed = time.time() - start_time
        tps = token_estimate / elapsed if elapsed > 0 else 0
        footer_parts = []
        if model:
            footer_parts.append(f"model: {model}")
        footer_parts.append(f"~{token_estimate} tokens")
        if tps > 0:
            footer_parts.append(f"{tps:.0f} tok/s")
        footer = " | ".join(footer_parts)

        content = Text(full_text)
        return Panel(
            content,
            title=f"[bold]{title}[/bold]",
            subtitle=f"[muted]{footer}[/muted]",
            border_style=border_style,
        )

    with Live(_build_panel(), console=console, refresh_per_second=12, transient=True):
        for delta in stream:
            full_text += delta
            # Rough token estimate: ~4 chars per token
            token_estimate = len(full_text) // 4

    # Use actual token count from usage accumulator if available
    acc = get_usage_accumulator()
    actual_tokens: int | None = None
    if acc.calls:
        last_call = acc.calls[-1]
        actual_tokens = last_call.output_tokens

    # Print final panel (non-transient)
    elapsed = time.time() - start_time
    final_tokens = actual_tokens if actual_tokens else token_estimate
    tps = final_tokens / elapsed if elapsed > 0 else 0
    footer_parts = []
    if model:
        footer_parts.append(f"model: {model}")
    if actual_tokens:
        footer_parts.append(f"{actual_tokens} tokens")
    else:
        footer_parts.append(f"~{token_estimate} tokens")
    footer_parts.append(f"{elapsed:.1f}s")
    footer_parts.append(f"{tps:.0f} tok/s")

    console.print(
        Panel(
            Text(full_text),
            title=f"[bold]{title}[/bold]",
            subtitle=f"[muted]{' | '.join(footer_parts)}[/muted]",
            border_style=border_style,
        )
    )

    return full_text


def stream_adapter_to_console(
    adapter: LLMClientPort,
    system: str,
    user: str,
    *,
    title: str = "Analysis",
    model: str | None = None,
) -> str:
    """Stream from any LLMClientPort adapter with panel display.

    Adapter-agnostic: works with ClaudeAdapter, OpenAIAdapter, or any port impl.
    """
    stream = adapter.generate_stream(system, user, model=model)
    display_model = model or "default"
    return stream_panel(stream, title=title, model=display_model)


def stream_graph_progress(
    graph: Any,
    state: dict[str, Any],
    config: dict[str, Any] | None = None,
    console: RichConsole | None = None,
) -> dict[str, Any]:
    """Stream graph execution with node-by-node progress display.

    Accumulates state updates using the correct merge strategy:
    - List reducer fields (analyses, errors, iteration_history) are extended.
    - Dict reducer fields (evaluations, subscores) are merged.
    - All other (scalar) fields are overwritten.

    Args:
        graph: Compiled LangGraph StateGraph.
        state: Initial state dict.
        config: Optional LangGraph config (e.g. thread config).
        console: Optional Rich console for output.

    Returns:
        Final accumulated state dict.
    """
    _console = console or RichConsole()
    final_state: dict[str, Any] = {}

    for event in graph.stream(state, config=config):
        for node_name, state_update in event.items():
            if node_name == "__end__":
                continue

            # Accumulate list reducer fields
            for key in ("analyses", "errors", "iteration_history"):
                if key in state_update and isinstance(state_update[key], list):
                    final_state.setdefault(key, []).extend(state_update[key])

            # Merge dict fields
            for key in ("evaluations", "subscores"):
                if key in state_update and isinstance(state_update[key], dict):
                    final_state.setdefault(key, {}).update(state_update[key])

            # Overwrite scalar fields
            for key, value in state_update.items():
                if key not in (
                    "analyses",
                    "errors",
                    "iteration_history",
                    "evaluations",
                    "subscores",
                ):
                    final_state[key] = value

            _console.print(f"  [dim]completed: {node_name}[/dim]")

    return final_state

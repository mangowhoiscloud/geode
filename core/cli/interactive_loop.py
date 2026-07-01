"""IPC response rendering and scheduler-queue drain delegator.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split).

Note: ``_thin_interactive_loop`` lives in ``core/cli/__init__.py`` rather
than here because ``tests/core/llm/test_signal_reload.py`` enforces a source-level
contract on the package ``__init__`` (the THIN ``/login refresh`` relay).
Keeping the loop body in ``__init__`` is the cheapest way to honor that
contract without weakening the test.
"""

from __future__ import annotations

from typing import Any

from core.ui.console import console


async def _drain_scheduler_queue(
    *,
    action_queue: Any,
    services: Any,
    session_lane: Any,
    global_lane: Any,
    force_isolated: bool = False,
    main_loop: Any | None = None,
    on_complete: Any | None = None,
    on_dispatch: Any | None = None,
    on_skip: Any | None = None,
    on_main_run: Any | None = None,
) -> int:
    """Drain pending scheduled jobs. Delegates to scheduler_drain module.

    PR-Async-Phase-C step 4a (2026-05-22) — async-native; the previous
    ``IsolatedRunner`` parameter is gone now that fire-and-forget runs on
    the caller's event loop via ``asyncio.create_task``.
    """
    from core.cli.scheduler_drain import drain_scheduler_queue

    return await drain_scheduler_queue(
        action_queue=action_queue,
        services=services,
        session_lane=session_lane,
        global_lane=global_lane,
        force_isolated=force_isolated,
        main_loop=main_loop,
        on_complete=on_complete,
        on_dispatch=on_dispatch,
        on_skip=on_skip,
        on_main_run=on_main_run,
    )


def _render_text_with_latex(text: str) -> None:
    """Render an LLM response with LaTeX segments lifted out of Markdown.

    The body is scanned for math delimiters (``$``/``$$``/``\\[\\]``/``\\(\\)``/
    ``\\begin{equation}…``) and split into text + math segments. Text
    segments still flow through :class:`rich.markdown.Markdown`; math
    segments render through :func:`core.ui.latex.render_latex` so the
    user sees Unicode (Tier 1) or a 2D Sympy block (Tier 2) instead of
    raw backslash form. Inline math is folded back into the surrounding
    Markdown paragraph; block math splits the Markdown stream. Falls back
    to plain Markdown when the body contains no math.
    """
    from rich.markdown import Markdown

    from core.ui.cjk_markdown import cjk_safe_emphasis
    from core.ui.console import refresh_console_width
    from core.ui.latex import extract_and_render_inline

    refresh_console_width()

    # CommonMark rejects `**…**` when the closer touches a Korean particle
    # (`**[추정]**이지만`) — pad spans so emphasis renders instead of
    # literal asterisks. Code regions pass through untouched.
    text = cjk_safe_emphasis(text)

    segments = list(extract_and_render_inline(text))
    has_math = any(kind != "text" for kind, _ in segments)

    console.print()
    if not has_math:
        console.print(Markdown(text))
        console.print()
        return

    text_buffer: list[str] = []

    def flush_text_buffer() -> None:
        if text_buffer:
            console.print(Markdown("".join(text_buffer)))
            text_buffer.clear()

    for kind, payload in segments:
        if not payload:
            continue
        if kind in {"text", "inline_math"}:
            text_buffer.append(payload)
        else:  # block_math
            flush_text_buffer()
            console.print()
            console.print(payload, style="value")
            console.print()
    flush_text_buffer()
    console.print()


def _render_ipc_response(response: dict[str, Any], *, streamed: bool = False) -> None:
    """Render an IPC response from serve.

    When *streamed* is True, the agentic UI (tool calls, token usage) was
    already rendered in real-time via streaming events — only the final
    text response needs rendering.
    """
    rtype = response.get("type", "")

    if rtype == "error":
        console.print(f"\n  [error]{response.get('message', 'Unknown error')}[/error]\n")
        return

    if rtype == "result":
        if not streamed:
            # Fallback: no streaming happened — show tool call summary
            tool_calls = response.get("tool_calls", [])
            for tc in tool_calls:
                console.print(f"  [dim]▸ {tc.get('name', '?')}[/dim]")

        # Main text (always render — this is the LLM's final response)
        text = response.get("text", "")
        if text:
            _render_text_with_latex(text)

        if not streamed:
            # Fallback status line when streaming wasn't available
            model = response.get("model", "")
            rounds = response.get("rounds", 0)
            tool_calls = response.get("tool_calls", [])
            parts = []
            if model:
                parts.append(f"✢ {model}")
            if rounds:
                parts.append(f"{rounds} rounds")
            if tool_calls:
                parts.append(f"{len(tool_calls)} tools")
            if parts:
                console.print(f"  [dim]{' · '.join(parts)}[/dim]")
        return

    # Silently drop internal protocol acks and lifecycle events
    if rtype in (
        "ack",
        "exit_ack",
        "llm_retry",
        "llm_error",
        "retry_wait",
        "budget_warning",
        "model_switched",
        "model_escalation",
    ):
        return

    # Fallback: unexpected response type — log instead of printing raw dict
    import logging

    logging.getLogger(__name__).debug("Unhandled IPC response type: %s", rtype)

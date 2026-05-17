"""GEODE CLI — Typer entrypoint with natural language interactive mode.

Architecture (OpenClaw-inspired):
  /command  → commands.py (Binding Router: deterministic dispatch)
  free-text → agentic_loop.py (AgenticLoop: multi-turn tool_use loop)

This module is the slim Typer entry point. Internal helpers and the
heavyweight ``init``/``serve`` commands live in sibling modules
(``welcome``, ``dispatcher``, ``prompt_session``, ``interactive_loop``,
``typer_commands``, ``typer_init``, ``typer_serve``). Tier 3 God Object
split — see ``CHANGELOG`` for v0.77.0.
"""

from __future__ import annotations

import logging
from typing import Any

import typer
from plugins.petri_audit.cli_audit import audit, petri_archive

from core import __version__

# ---------------------------------------------------------------------------
# Sub-module re-exports (backward compatibility)
# ---------------------------------------------------------------------------
# Internal helpers extracted into sibling modules during the v0.77.0
# Tier 3 God Object split. Re-exported here so ``from core.cli import X``
# keeps working for the 90+ external import sites (tests, plugins,
# server). Each ``as X`` alias suppresses ruff F401 unused-import errors.
from core.cli.dispatcher import _handle_command as _handle_command
from core.cli.interactive_loop import _drain_scheduler_queue as _drain_scheduler_queue
from core.cli.interactive_loop import _render_ipc_response as _render_ipc_response
from core.cli.prompt_session import _build_prompt_session as _build_prompt_session
from core.cli.prompt_session import _drain_stdin as _drain_stdin
from core.cli.prompt_session import _force_select_event_loop as _force_select_event_loop
from core.cli.prompt_session import _get_prompt_session as _get_prompt_session
from core.cli.prompt_session import _read_multiline_input as _read_multiline_input
from core.cli.prompt_session import _restore_terminal as _restore_terminal
from core.cli.prompt_session import _sigint_handler as _sigint_handler
from core.cli.report_renderer import (
    _build_skill_narrative as _build_skill_narrative,
)
from core.cli.report_renderer import (
    _generate_report as _generate_report,
)
from core.cli.report_renderer import (
    _parse_report_args as _parse_report_args,
)
from core.cli.report_renderer import (
    _state_to_report_dict as _state_to_report_dict,
)
from core.cli.session_state import _get_last_result as _get_last_result
from core.cli.session_state import _get_readiness as _get_readiness
from core.cli.session_state import _result_cache as _result_cache
from core.cli.session_state import _ResultCache as _ResultCache
from core.cli.session_state import _scheduler_service_ctx as _scheduler_service_ctx
from core.cli.session_state import _set_last_result as _set_last_result
from core.cli.session_state import _set_readiness as _set_readiness
from core.cli.tool_handlers import (
    _build_tool_handlers as _build_tool_handlers,
)
from core.cli.typer_commands import (
    about,
    doctor,
    history,
    setup,
    version,
)
from core.cli.typer_init import _ensure_gitignore_entry as _ensure_gitignore_entry
from core.cli.typer_init import init
from core.cli.typer_serve import _build_runtime_for_serve as _build_runtime_for_serve
from core.cli.typer_serve import serve
from core.cli.welcome import _render_readiness_compact as _render_readiness_compact
from core.cli.welcome import _render_welcome_brand as _render_welcome_brand
from core.cli.welcome import _suppress_noisy_warnings as _suppress_noisy_warnings
from core.cli.welcome import _welcome_screen as _welcome_screen
from core.hooks import HookEvent, HookSystem
from core.hooks.utils import fire_hook
from core.llm.commentary import generate_commentary
from core.ui.console import console
from core.ui.status import GeodeStatus

log = logging.getLogger(__name__)

# Hook system module-level variable for memory event firing (P1.5)
_hooks_ctx: HookSystem | None = None


def _fire_hook(event: HookEvent, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is wired (or no-op)."""
    fire_hook(_hooks_ctx, event, data)


def _show_commentary(
    user_text: str, action: str, context: dict[str, Any], *, is_offline: bool
) -> None:
    """Generate and display LLM commentary after tool call results."""
    if is_offline:
        return
    from core.config import settings

    with GeodeStatus("Generating response...", model=settings.model) as status:
        text = generate_commentary(user_query=user_text, action=action, context=context)
        status.stop("response" if text else "response (skipped)")
    if text:
        console.print()
        console.print(f"  {text}")
        console.print()


def _handle_memory_action(intent: Any, user_text: str, is_offline: bool) -> None:
    """Handle memory-related actions (P0-A + P1-B). Delegates to memory_handler module."""
    from core.cli.memory_handler import handle_memory_action

    handle_memory_action(intent, user_text, is_offline, fire_hook=_fire_hook)


# ---------------------------------------------------------------------------
# Thin REPL — delegates to geode serve via IPC
# ---------------------------------------------------------------------------


_LOCAL_COMMANDS = frozenset({"/help"})

# Commands that need TTY interaction locally, then relay the result to serve
_TTY_LOCAL_COMMANDS = frozenset({"/model"})


def _thin_interactive_loop(
    *,
    resume_session: str = "",
    continue_latest: bool = False,
) -> None:
    """Thin CLI client — all execution delegated to geode serve via IPC.

    Local commands: /help
    Everything else (including /quit, /exit, /clear, /compact): relayed to serve
    """
    from core.cli.ipc_client import IPCClient

    client = IPCClient()
    if not client.connect():
        console.print("  [error]Failed to connect to serve[/error]")
        return

    console.print(f"  [success]Session: {client.session_id}[/success]")

    # Resume a previous session if requested
    if resume_session or continue_latest:
        result = client.request_resume(
            session_id=resume_session,
            continue_latest=continue_latest,
        )
        if result.get("type") == "resumed":
            sid = result.get("session_id", "")
            rnd = result.get("round_idx", 0)
            msgs = result.get("message_count", 0)
            model = result.get("model", "")
            console.print(
                f"  [success]Resumed:[/success] {sid}"
                f"  [muted](round {rnd}, {msgs} messages, {model})[/muted]"
            )
        else:
            console.print(f"  [warning]{result.get('message', 'Resume failed')}[/warning]")
    console.print()

    try:
        while True:
            console.show_cursor(True)
            try:
                user_input = _read_multiline_input("[header]>[/header] ")
            except (KeyboardInterrupt, EOFError):
                console.print("\n  [muted]Goodbye.[/muted]\n")
                break

            if not user_input:
                continue

            if user_input.strip().lower() in ("exit", "quit", "q"):
                # Relay /quit to serve for session cost summary
                response = client.send_command("/quit", "")
                output = response.get("output", "")
                if output:
                    import sys as _sys

                    _sys.stdout.write(output)
                    _sys.stdout.flush()
                break

            # Slash commands
            if "\n" not in user_input and user_input.startswith("/"):
                cmd = user_input.split()[0].lower()
                args = user_input[len(cmd) :].strip()

                # Local-only commands
                if cmd in _LOCAL_COMMANDS:
                    try:
                        _handle_command(cmd, args, False)
                    except (SystemExit, EOFError):
                        break
                    continue

                # /model (no args): interactive picker locally, then relay
                if cmd in _TTY_LOCAL_COMMANDS and not args:
                    if cmd == "/model":
                        import sys as _sys

                        from core.cli.commands import _interactive_model_picker

                        if _sys.stdin.isatty():
                            _interactive_model_picker()
                            # Relay to serve (suppress — picker already printed)
                            from core.config import settings

                            client.send_command("/model", settings.model)
                        else:
                            response = client.send_command(cmd, args)
                            output = response.get("output", "")
                            if output:
                                _sys.stdout.write(output)
                                _sys.stdout.flush()
                    else:
                        response = client.send_command(cmd, args)
                        output = response.get("output", "")
                        if output:
                            import sys as _sys

                            _sys.stdout.write(output)
                            _sys.stdout.flush()
                    continue

                # /clear: auto-force in IPC mode (no stdin for confirmation on serve)
                if cmd == "/clear" and "--force" not in args:
                    args = (args + " --force").strip()

                # v0.52 phase 3 — central command registry decides execution
                # location. THIN commands run locally so terminal stdin/stdout/
                # browser stay attached (fixes OAuth device-code invisibility,
                # bug class B1/B3).
                from core.cli.routing import RunLocation
                from core.cli.routing import lookup as _lookup_spec

                _spec = _lookup_spec(cmd)
                if _spec is not None and _spec.location is RunLocation.THIN:
                    try:
                        _handle_command(cmd, args, False)
                    except (SystemExit, EOFError):
                        break
                    # Notify daemon to reload auth state if this command
                    # may have written to ~/.geode/auth.toml.
                    if cmd in ("/login", "/key"):
                        import contextlib

                        with contextlib.suppress(Exception):
                            client.send_command("/login", "refresh")
                    continue

                # All other commands → relay to serve
                response = client.send_command(cmd, args)
                # Render captured output from serve (ANSI-styled text)
                output = response.get("output", "")
                if output:
                    import sys as _sys

                    _sys.stdout.write(str(output))
                    _sys.stdout.flush()
                if response.get("status") == "error":
                    console.print(f"  [error]{response.get('message', 'Command failed')}[/error]")
                elif response.get("should_break"):
                    break
                continue

            # Free text → relay as prompt (client-side direct rendering)
            from core.ui.event_renderer import EventRenderer

            _renderer = EventRenderer()
            _stream_started = False
            _r = _renderer  # bind for closures (B023)

            def _on_stream(data: str, *, _rr: Any = _r) -> None:
                nonlocal _stream_started
                _stream_started = True
                _rr.on_stream(data)

            def _on_event(event: dict[str, object], *, _rr: Any = _r) -> None:
                nonlocal _stream_started
                _stream_started = True
                _rr.on_event(event)

            def _on_approval_start(*, _rr: Any = _r) -> None:
                _rr.suspend_for_approval()

            def _on_approval_end(*, _rr: Any = _r) -> None:
                _rr.resume_from_approval()

            _renderer.start_activity()  # persistent spinner until result
            response = client.send_prompt(
                user_input,
                on_stream=_on_stream,
                on_event=_on_event,
                on_approval_start=_on_approval_start,
                on_approval_end=_on_approval_end,
            )
            _renderer.stop()
            if response.get("type") == "error" and "Connection lost" in response.get("message", ""):
                console.print("\n  [error]Connection to serve lost[/error]\n")
                break
            _render_ipc_response(response, streamed=_stream_started)
    finally:
        client.close()


app = typer.Typer(
    name="geode",
    help=f"GEODE v{__version__} — 범용 자율 실행 에이전트",
    no_args_is_help=False,
    invoke_without_command=True,
)

# Subcommand groups
from core.cli.cmd_skill import app as skill_app  # noqa: E402

app.add_typer(skill_app, name="skill")


# ---------------------------------------------------------------------------
# Typer command registration
# ---------------------------------------------------------------------------
# Functions live in sibling modules; we apply Typer decorators here so
# the package ``__init__`` remains the canonical Typer entry point.

app.command()(version)
app.command()(about)
app.command()(setup)
app.command()(doctor)
app.command()(init)
app.command()(history)
app.command()(serve)
app.command()(audit)
app.command(name="petri-archive")(petri_archive)


@app.callback()
def main(
    ctx: typer.Context,
    continue_session: bool = typer.Option(
        False, "--continue", help="Resume the most recent session"
    ),
    resume: str = typer.Option("", "--resume", help="Resume a specific session by ID"),
) -> None:
    """GEODE — Autonomous Research Harness."""
    if ctx.invoked_subcommand is None:
        _welcome_screen()

        # Ensure serve is running (auto-start if needed)
        from core.cli.ipc_client import is_serve_running, start_serve_if_needed

        if not is_serve_running():
            from core.ui.status import TextSpinner

            spinner = TextSpinner("Starting serve...")
            spinner.start()
            ready = start_serve_if_needed(timeout_s=30)
            spinner.stop()
            if not ready:
                console.print("  [error]Failed to start geode serve[/error]")
                console.print("  [dim]Try manually: geode serve &[/dim]")
                raise typer.Exit(1)

        console.print("  [muted]Connected to serve via IPC[/muted]")
        _thin_interactive_loop(
            resume_session=resume,
            continue_latest=continue_session,
        )


if __name__ == "__main__":
    app()

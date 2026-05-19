"""Interactive prompt session helpers for the GEODE thin CLI.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split). Hosts
prompt_toolkit setup, signal/select-loop guards, and multi-line input
helpers. The ``terminal`` module already owns the lower-level terminal
primitives (``restore_terminal``, ``drain_stdin``, ``suppress_noisy_warnings``);
the helpers here are CLI-loop facing wrappers.
"""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from typing import Any

from core.ui.console import console

log = logging.getLogger(__name__)


def _restore_terminal() -> None:
    """Restore terminal to sane cooked mode. Delegates to terminal module."""
    from core.cli.terminal import restore_terminal

    restore_terminal()


_original_sigint = signal.getsignal(signal.SIGINT)


def _sigint_handler(signum: int, frame: Any) -> None:
    """SIGINT handler that restores terminal before raising KeyboardInterrupt."""
    _restore_terminal()
    raise KeyboardInterrupt


# ---------------------------------------------------------------------------
# prompt_toolkit REPL input (arrow keys, history)
# ---------------------------------------------------------------------------
def _event_data_is_printable_character(event: Any, data: str | None) -> bool:
    """Return True only for printable character key events."""
    if not data or not data.isprintable():
        return False

    key_sequence = getattr(event, "key_sequence", ())
    if not key_sequence:
        return True

    key = getattr(key_sequence[-1], "key", None)
    return key == data


def _build_prompt_session() -> Any:
    """Create a prompt_toolkit PromptSession with history + GEODE styling.

    multiline=True so that pasted multi-line text stays in the buffer
    instead of each newline triggering a separate submit. Enter submits,
    Escape+Enter inserts a real newline.

    Includes custom printable-insert plus Backspace/Delete key bindings
    that force a full renderer redraw after the buffer changes — fixes
    wide-char (Korean jamo) ghost artifacts where the display doesn't
    update even though the buffer is correctly modified.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.filters import is_done
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("enter", filter=~is_done)
    def _enter(event: Any) -> None:
        """Enter always submits (like single-line mode)."""
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter", filter=~is_done)
    def _newline(event: Any) -> None:
        """Escape+Enter inserts a real newline for intentional multi-line."""
        event.current_buffer.insert_text("\n")

    @kb.add("<any>")
    def _insert_printable(event: Any) -> None:
        data = event.data
        if not _event_data_is_printable_character(event, data):
            return

        event.current_buffer.insert_text(data)
        event.app.invalidate()

    @kb.add("backspace")
    def _backspace(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position > 0:
            buf.delete_before_cursor(count=1)
            event.app.invalidate()

    @kb.add("delete")
    def _delete(event: Any) -> None:
        buf = event.app.current_buffer
        if buf.cursor_position < len(buf.text):
            buf.delete(count=1)
            event.app.invalidate()

    history_path = Path.home() / ".geode_history"

    # PR-γ1 — install + bind the subscription quota banner. Lazy-load
    # the self-improving-loop config so prompt_session stays importable when
    # ``core.config.self_improving_loop`` is unavailable (test contexts).
    bottom_toolbar = _make_bottom_toolbar()

    return PromptSession(
        history=FileHistory(str(history_path)),
        message=HTML("<b>&gt;</b> "),
        enable_history_search=True,
        multiline=True,
        key_bindings=kb,
        bottom_toolbar=bottom_toolbar,
    )


def _make_bottom_toolbar() -> Any:
    """Build the bottom_toolbar callable for the REPL.

    Installs a process-wide :class:`SubscriptionQuotaBanner` keyed on
    the self-improving-loop config's warn / abort thresholds, then returns its
    ``render`` method as the prompt_toolkit ``bottom_toolbar`` value.
    Returns ``None`` when the self-improving-loop config is unavailable so the
    REPL falls back to no-banner gracefully.
    """
    from prompt_toolkit.formatted_text import HTML as _HTML

    from core.cli.quota_banner import SubscriptionQuotaBanner, install_banner

    try:
        from core.config.self_improving_loop import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
        warn = cfg.warn_threshold
        abort = cfg.abort_threshold
    except Exception:
        log.warning("self-improving-loop config unavailable; banner uses defaults", exc_info=True)
        warn, abort = 0.5, 0.9

    banner = SubscriptionQuotaBanner(
        warn_threshold=warn,
        abort_threshold=abort,
    )
    install_banner(banner)

    # P0c — wire the per-response Anthropic quota writer (callback
    # registration instead of cross-layer import: the agent path
    # ``core.llm.providers.anthropic`` is forbidden by import-linter from
    # depending on ``core.cli.*``, so the CLI owns the import direction
    # and pushes its setter in).
    try:
        from core.llm.providers.anthropic import register_quota_setter

        register_quota_setter(banner.set_state)
    except Exception:  # pragma: no cover - defensive
        log.warning("anthropic quota setter registration failed", exc_info=True)

    def _render() -> Any:
        text = banner.render()
        if not text:
            return ""
        return _HTML(text)

    return _render


_select_policy_applied = False


def _force_select_event_loop() -> None:
    """Force asyncio to use select() instead of kqueue on Python 3.14+.

    Python 3.14's kqueue selector raises OSError on add_reader(fd) when
    prompt_toolkit attaches stdin. select() doesn't have this issue.
    Deprecated in 3.16 but functional through 3.15.
    """
    global _select_policy_applied
    if _select_policy_applied:
        return
    _select_policy_applied = True

    import asyncio
    import selectors
    import warnings

    class _SelectLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            selector = selectors.SelectSelector()
            return asyncio.SelectorEventLoop(selector)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(_SelectLoopPolicy())
    log.debug("Forced SelectSelector event loop policy (Python 3.14+ kqueue workaround)")


# Module-level lazy singleton
_prompt_session: Any = None


def _get_prompt_session() -> Any:
    global _prompt_session
    if _prompt_session is False:
        return None  # permanently disabled after runtime failure
    if _prompt_session is None:
        # Python 3.14+ kqueue is incompatible with prompt_toolkit's
        # asyncio add_reader (OSError: Invalid argument). Force select()
        # based event loop so prompt_toolkit works (CJK input, history).
        if sys.version_info >= (3, 14):
            _force_select_event_loop()
        try:
            _prompt_session = _build_prompt_session()
        except Exception:
            log.warning("prompt_toolkit init failed, falling back to console.input", exc_info=True)
            _prompt_session = False  # sentinel: disabled
    return _prompt_session


def _drain_stdin() -> None:
    """Drain leftover bytes from stdin. Delegates to terminal module."""
    from core.cli.terminal import drain_stdin

    drain_stdin()


def _read_multiline_input(prompt: str) -> str:
    """Read user input via prompt_toolkit (arrow keys, history).

    Falls back to Rich console.input if prompt_toolkit is unavailable.
    Paste handling is delegated to prompt_toolkit's built-in bracketed
    paste support (no manual stdin polling).
    """
    session = _get_prompt_session()
    if session is not None:
        try:
            # Restore default SIGINT so prompt_toolkit can handle Ctrl-C internally.
            # Our custom handler interferes with prompt_toolkit's input loop.
            signal.signal(signal.SIGINT, _original_sigint)
            raw: str = str(session.prompt()).strip()
            # Join pasted multi-line text into a single line.
            # Intentional newlines (Esc+Enter) are preserved by the caller
            # via "\n" detection in the slash command guard.
            text = " ".join(raw.splitlines()) if "\n" in raw else raw
            # Drain stdin to prevent leftover paste from auto-submitting
            # on the next prompt. Only needed when bracketed paste is broken
            # or the terminal doesn't support it.
            _drain_stdin()
        except (KeyboardInterrupt, EOFError):
            raise
        except Exception:
            log.warning("prompt_toolkit failed, falling back to console.input", exc_info=True)
            # Invalidate session to avoid retrying prompt_toolkit on every input
            global _prompt_session
            _prompt_session = False  # sentinel: permanently disabled
            _restore_terminal()
            text = str(console.input("> ")).strip()
        finally:
            # Re-install our handler for the non-input phase (spinner, tool execution)
            signal.signal(signal.SIGINT, _sigint_handler)
    else:
        text = str(console.input("> ")).strip()

    return text

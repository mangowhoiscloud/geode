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
def _build_prompt_session() -> Any:
    """Create a prompt_toolkit PromptSession with history + GEODE styling.

    multiline=True so that pasted multi-line text stays in the buffer
    instead of each newline triggering a separate submit. Enter submits,
    Escape+Enter inserts a real newline.

    Includes a custom Backspace/Delete key binding that forces a full
    renderer redraw after deletion — fixes wide-char (Korean jamo) ghost
    artifacts where the display doesn't update even though the buffer is
    correctly modified.
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
    return PromptSession(
        history=FileHistory(str(history_path)),
        message=HTML("<b>&gt;</b> "),
        enable_history_search=True,
        multiline=True,
        key_bindings=kb,
    )


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

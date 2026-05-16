"""OAuth device-code helper — open the verification URL on first stdin line.

Used by both render paths of the OAuth device-code prompt:

  * IPC path — ``core.ui.event_renderer.EventRenderer._handle_oauth_login_started``
    (when the OAuth flow runs in serve and surfaces via IPC events).
  * Direct path — ``core.ui.agentic_ui.events.emit_oauth_login_started`` fallback
    (when the flow runs in the thin CLI process itself — e.g.
    ``/login openai`` slash command with no IPC writer set).

Both paths render the same Press [Enter] prompt and spawn the same daemon
watcher so the user gets identical UX regardless of which process owns
the OAuth polling loop. Keeping the helper in a tiny standalone module
avoids cyclic imports between ``event_renderer`` and ``agentic_ui.events``.
"""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger(__name__)


def start_oauth_browser_watcher(uri: str) -> None:
    """Daemon thread: open ``uri`` in the default browser on first stdin line.

    Non-blocking — returns immediately so the polling heartbeats can keep
    rendering. If the user finishes OAuth without pressing Enter, the thread
    stays blocked on ``sys.stdin.readline()`` until the process exits; it's
    a daemon so it dies with the process.

    Skipped when stdin is not a TTY (piped / non-interactive sessions like
    CI runs or scripted invocations).
    """
    if not sys.stdin.isatty():
        return

    def _watcher() -> None:
        try:
            sys.stdin.readline()
        except Exception:
            return
        try:
            import webbrowser

            webbrowser.open(uri)
        except Exception:  # pragma: no cover — webbrowser is best-effort
            log.debug("webbrowser.open failed for %s", uri, exc_info=True)

    threading.Thread(target=_watcher, daemon=True, name="oauth-browser-watcher").start()

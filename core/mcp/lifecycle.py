"""Signal and process-exit lifecycle state for MCP connections."""

from __future__ import annotations

import atexit
import logging
import signal
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class MCPLifecycle:
    """Own MCP signal/atexit registration and shutdown state."""

    def __init__(self, is_main_thread: Callable[[], bool]) -> None:
        self.signal_installed = False
        self.prev_sigterm: Any = None
        self.prev_sigint: signal.Handlers | None = None
        self.atexit_registered = False
        self.shutdown_called = False
        self._is_main_thread = is_main_thread

    def install(self, shutdown: Callable[[], None], atexit_cleanup: Callable[[], None]) -> None:
        if self.signal_installed:
            return
        try:
            if not self._is_main_thread():
                log.debug("MCP signal handlers skipped (not main thread)")
                return
        except Exception:
            log.debug("MCP signal handler thread check failed", exc_info=True)
            return

        def signal_shutdown(signum: int, frame: Any) -> None:
            log.info("MCP received signal %d, shutting down servers", signum)
            shutdown()
            previous = self.prev_sigterm if signum == signal.SIGTERM else self.prev_sigint
            if previous and callable(previous):
                previous(signum, frame)
            elif previous == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        try:
            self.prev_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, signal_shutdown)
            self.signal_installed = True
            log.debug("MCP SIGTERM handler installed")
        except (OSError, ValueError):
            log.debug("MCP signal handler installation failed", exc_info=True)
        if not self.atexit_registered:
            atexit.register(atexit_cleanup)
            self.atexit_registered = True

    def uninstall(self) -> None:
        if not self.signal_installed:
            return
        try:
            if not self._is_main_thread():
                return
        except Exception:
            return
        try:
            if self.prev_sigterm is not None:
                signal.signal(signal.SIGTERM, self.prev_sigterm)
            self.signal_installed = False
            log.debug("MCP signal handlers restored")
        except (OSError, ValueError):
            log.debug("MCP signal handler restoration failed", exc_info=True)

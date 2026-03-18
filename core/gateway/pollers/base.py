"""Base Poller — abstract base for channel pollers."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.gateway.channel_manager import ChannelManager

log = logging.getLogger(__name__)


class BasePoller(ABC):
    """Abstract daemon-thread poller for external messaging channels.

    Subclasses implement _poll_once() to fetch new messages from
    their channel and route them through the ChannelManager.
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        poll_interval_s: float = 2.0,
    ) -> None:
        self._manager = channel_manager
        self._poll_interval = poll_interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier (e.g., 'slack')."""
        ...

    @abstractmethod
    def _poll_once(self) -> None:
        """Fetch new messages and route them via self._manager."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the poller has necessary credentials/config."""
        ...

    def start(self) -> None:
        """Start the polling daemon thread."""
        if not self.is_configured():
            log.debug("Poller %s not configured — skipping", self.channel_name)
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"geode-{self.channel_name}-poller",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Gateway poller started: %s (interval=%.1fs)",
            self.channel_name,
            self._poll_interval,
        )

    def stop(self) -> None:
        """Signal the poller to stop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("Gateway poller stopped: %s", self.channel_name)

    def _run_loop(self) -> None:
        """Main polling loop (runs in daemon thread)."""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                log.warning("Poller %s error: %s", self.channel_name, exc)
            self._stop_event.wait(self._poll_interval)

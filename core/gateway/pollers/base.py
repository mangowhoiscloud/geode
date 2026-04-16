"""Base Poller — abstract base for channel pollers."""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.gateway.channel_manager import ChannelManager
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort

log = logging.getLogger(__name__)


class BasePoller(ABC):
    """Abstract daemon-thread poller for external messaging channels.

    Subclasses implement _poll_once() to fetch new messages from
    their channel and route them through the ChannelManager.

    Subclasses MAY define:
        _env_config_var: str  — env var name for is_configured() check
    """

    _env_config_var: str = ""  # Override in subclass for auto is_configured()

    def __init__(
        self,
        channel_manager: ChannelManager,
        *,
        mcp_manager: MCPServerManager | None = None,
        notification: NotificationPort | None = None,
        poll_interval_s: float = 2.0,
    ) -> None:
        self._manager = channel_manager
        self._mcp = mcp_manager
        self._notification = notification
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

    def is_configured(self) -> bool:
        """Check if the poller has necessary credentials/config."""
        if self._env_config_var:
            return bool(os.environ.get(self._env_config_var))
        return False

    # --- Shared helpers ---

    def _check_mcp_health(self) -> bool:
        """Return True if MCP manager is available and this channel is healthy."""
        if self._mcp is None:
            return False
        health = self._mcp.check_health()
        return health.get(self.channel_name, False)

    def _get_channel_bindings(self) -> list[dict[str, Any]]:
        """Return bindings for this channel with valid channel IDs."""
        bindings = self._manager.list_bindings()
        return [
            b
            for b in bindings
            if b["channel"] == self.channel_name and b.get("channel_id", "") not in ("", "*")
        ]

    # --- Lifecycle ---

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

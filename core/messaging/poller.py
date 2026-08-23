"""Process-neutral base for external messaging pollers."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager
    from core.mcp.notification_port import NotificationPort
    from core.messaging.binding import ChannelManager

log = logging.getLogger(__name__)


class BasePoller(ABC):
    """Abstract daemon-thread poller for external messaging channels."""

    _env_config_var: str = ""
    STOP_JOIN_TIMEOUT_S: float = 5.0

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
        """Return the channel identifier (e.g., ``slack``)."""
        ...

    @abstractmethod
    async def _apoll_once(self) -> None:
        """Fetch new messages and route them through the channel manager."""
        ...

    def is_configured(self) -> bool:
        """Return whether this poller has its required environment config."""
        return bool(self._env_config_var and os.environ.get(self._env_config_var))

    def _check_mcp_health(self) -> bool:
        """Return whether the MCP manager reports this channel healthy."""
        if self._mcp is None:
            return False
        return self._mcp.check_health().get(self.channel_name, False)

    def _get_channel_bindings(self) -> list[dict[str, Any]]:
        """Return valid bindings for this poller's channel."""
        return [
            binding
            for binding in self._manager.list_bindings()
            if binding["channel"] == self.channel_name
            and binding.get("channel_id", "") not in ("", "*")
        ]

    def start(self) -> None:
        """Start the polling daemon thread when configured."""
        if not self.is_configured():
            log.debug("Poller %s not configured — skipping", self.channel_name)
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop_thread,
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
        """Signal the poller to stop and join its thread."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.STOP_JOIN_TIMEOUT_S)
            if thread.is_alive():
                log.warning(
                    "Gateway poller %s still stopping after %.0fs join timeout",
                    self.channel_name,
                    self.STOP_JOIN_TIMEOUT_S,
                )
                return
            self._thread = None
        log.info("Gateway poller stopped: %s", self.channel_name)

    def _run_loop_thread(self) -> None:
        """Run the async polling loop in the poller's daemon thread."""
        with asyncio.Runner() as runner:
            runner.run(self._run_loop_async())

    async def _run_loop_async(self) -> None:
        """Poll until stopped, isolating one failed iteration."""
        while not self._stop_event.is_set():
            try:
                await self._apoll_once()
            except Exception as exc:
                log.warning("Poller %s error: %s", self.channel_name, exc)
            await asyncio.sleep(self._poll_interval)

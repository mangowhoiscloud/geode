"""Slack Socket Mode client for push-based gateway inbound events.

The app-level ``xapp-`` token is used only to call
``apps.connections.open`` and obtain a short-lived WebSocket URL. Bot-token
Web API calls stay in :mod:`core.messaging.slack_transport`.

Protocol references:
- https://docs.slack.dev/apis/events-api/using-socket-mode/
- https://docs.slack.dev/reference/methods/apps.connections.open/

Events API envelopes are admitted into a bounded queue BEFORE they are
acknowledged; a full queue leaves the envelope unACKed so Slack redelivers
it. A fixed worker pool consumes the queue, keeping the acknowledgement
path independent from a potentially long GEODE agent turn without
accumulating unbounded local tasks. WebSocket URLs contain a temporary
ticket and are never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from core.messaging.slack_transport import (
    SlackTransportError,
    open_socket_mode_url,
    resolve_app_token,
)

log = logging.getLogger(__name__)

_MAX_RECONNECT_DELAY_S = 30.0
_RECV_STOP_POLL_S = 1.0
# Bounded ingress (PR-SLACK-SOCKET-LANDING): events are admitted to this
# queue BEFORE their envelope is acknowledged. A full queue leaves the
# envelope unACKed so Slack redelivers it — overload sheds to Slack's
# retry path instead of accumulating unbounded local tasks. (An event that
# WAS acked lives in process memory; a crash before its handler finishes
# still loses it — Slack's retry only covers the unacked window.)
_ADMISSION_QUEUE_MAX = 64
_EVENT_WORKERS = 8
_DRAIN_TIMEOUT_S = 20.0

SocketEventHandler = Callable[[dict[str, Any]], Awaitable[None]]
StopPredicate = Callable[[], bool]


class _SocketConnection(Protocol):
    async def recv(self) -> str | bytes: ...

    async def send(self, message: str) -> None: ...


class SlackSocketModeError(Exception):
    """Socket Mode URL generation or protocol validation failed."""


class SlackSocketModeClient:
    """Minimal Socket Mode protocol client using GEODE's existing dependencies."""

    def __init__(self, app_token: str | None = None) -> None:
        self._app_token = resolve_app_token(app_token)

    @property
    def configured(self) -> bool:
        """An app-level token is available (no network)."""
        return bool(self._app_token)

    async def open_connection_url(self) -> str:
        """Issue and validate a temporary Slack WebSocket URL.

        The URL includes a bearer-like ticket. Callers may connect with it but
        must never persist or log it.
        """
        if not self._app_token:
            raise SlackSocketModeError("SLACK_APP_TOKEN not configured")
        try:
            return await open_socket_mode_url(self._app_token)
        except SlackTransportError as exc:
            raise SlackSocketModeError(str(exc)) from exc

    async def run(self, on_event: SocketEventHandler, should_stop: StopPredicate) -> None:
        """Receive, admit, acknowledge, and dispatch events until ``should_stop``.

        Connection failures use bounded exponential backoff. Slack-requested
        refreshes immediately leave the current socket and obtain a fresh URL.
        On stop, already-ACKed events are drained for a bounded window.
        """
        if not self.configured:
            raise SlackSocketModeError("SLACK_APP_TOKEN not configured")

        import websockets

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_ADMISSION_QUEUE_MAX)

        in_flight = 0

        async def worker() -> None:
            nonlocal in_flight
            while True:
                payload = await queue.get()
                in_flight += 1
                try:
                    await on_event(payload)
                except Exception as exc:
                    log.warning("Slack Socket Mode event handler failed: %s", exc)
                finally:
                    in_flight -= 1
                    queue.task_done()

        workers = [
            asyncio.create_task(worker(), name=f"geode-slack-event-worker-{i}")
            for i in range(_EVENT_WORKERS)
        ]
        reconnect_delay = 1.0
        try:
            while not should_stop():
                try:
                    url = await self.open_connection_url()
                    async with websockets.connect(
                        url,
                        open_timeout=15.0,
                        ping_interval=20.0,
                        ping_timeout=20.0,
                        close_timeout=5.0,
                        max_size=2 * 1024 * 1024,
                    ) as socket:
                        log.info("Slack Socket Mode connected")
                        received_frame = False
                        while not should_stop():
                            try:
                                raw = await asyncio.wait_for(
                                    socket.recv(), timeout=_RECV_STOP_POLL_S
                                )
                            except TimeoutError:
                                continue
                            if not received_frame:
                                # A connection that reaches Slack protocol
                                # traffic is healthy enough to reset backoff.
                                reconnect_delay = 1.0
                                received_frame = True
                            reconnect = await self._handle_frame(
                                socket,
                                raw,
                                queue,
                            )
                            if reconnect:
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if should_stop():
                        break
                    log.warning(
                        "Slack Socket Mode disconnected (%s); reconnecting in %.0fs",
                        self._safe_error(exc),
                        reconnect_delay,
                    )
                    await self._wait_or_stop(reconnect_delay, should_stop)
                    reconnect_delay = min(
                        reconnect_delay * 2.0,
                        _MAX_RECONNECT_DELAY_S,
                    )
        finally:
            # Ingress has stopped (loop exited). Drain admitted events for a
            # bounded window — they were ACKed, so abandoning them silently
            # would lose delivered work; after the window, cancel loudly.
            try:
                await asyncio.wait_for(queue.join(), timeout=_DRAIN_TIMEOUT_S)
            except TimeoutError:
                log.warning(
                    "Slack Socket Mode drain timed out: %d queued + %d in-flight event(s)",
                    queue.qsize(),
                    in_flight,
                )
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            log.info("Slack Socket Mode stopped")

    @classmethod
    async def _handle_frame(
        cls,
        socket: _SocketConnection,
        raw: str | bytes,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> bool:
        """Handle one frame. Return ``True`` when Slack requests reconnect.

        Events API envelopes are ACKed only AFTER queue admission — a full
        queue skips the ACK so Slack redelivers the envelope later.
        """
        try:
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            envelope = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("Slack Socket Mode ignored a malformed frame")
            return False
        if not isinstance(envelope, dict):
            log.warning("Slack Socket Mode ignored a non-object frame")
            return False

        envelope_type = str(envelope.get("type", ""))
        if envelope_type == "hello":
            log.info("Slack Socket Mode hello received")
            return False
        if envelope_type == "disconnect":
            reason = str(envelope.get("reason", "unknown"))
            log.info("Slack Socket Mode refresh requested (reason=%s)", reason)
            return True

        envelope_id = str(envelope.get("envelope_id", ""))

        if envelope_type != "events_api":
            if envelope_id:
                await cls._ack(socket, envelope_id)
            log.debug("Slack Socket Mode acknowledged unsupported envelope type=%s", envelope_type)
            return False

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            if envelope_id:
                await cls._ack(socket, envelope_id)
            log.warning("Slack Socket Mode event envelope had no object payload")
            return False

        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # No ACK: Slack will redeliver; channel:ts dedup absorbs any
            # duplicate that arrives after pressure clears.
            log.warning(
                "Slack Socket Mode admission queue full (%d) — leaving envelope unACKed",
                queue.maxsize,
            )
            return False
        if envelope_id:
            await cls._ack(socket, envelope_id)
        return False

    @staticmethod
    async def _ack(socket: _SocketConnection, envelope_id: str) -> None:
        await socket.send(json.dumps({"envelope_id": envelope_id}, separators=(",", ":")))

    @staticmethod
    async def _wait_or_stop(delay_s: float, should_stop: StopPredicate) -> None:
        deadline = time.monotonic() + delay_s
        while not should_stop():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, 0.25))

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        """Return an error without ever echoing a temporary WebSocket ticket."""
        if isinstance(exc, SlackSocketModeError):
            return str(exc)
        return type(exc).__name__

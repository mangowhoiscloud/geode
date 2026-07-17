"""Slack Socket Mode protocol tests. No live Slack connection is used."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from core.messaging.slack_socket_mode import (
    SlackSocketModeClient,
    SlackSocketModeError,
)


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def recv(self) -> str:
        raise AssertionError("recv is not used by frame-level tests")

    async def send(self, message: str) -> None:
        self.sent.append(message)


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    real_client = httpx.AsyncClient

    def _client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)


def test_open_connection_url_uses_app_token_and_redacts_nothing_to_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "url": "wss://wss-primary.slack.com/link/?ticket=secret"},
        )

    _patch_httpx(monkeypatch, handler)
    client = SlackSocketModeClient(app_token="xapp-test")
    url = asyncio.run(client.open_connection_url())

    assert url.startswith("wss://wss-primary.slack.com/")
    assert requests[0].headers["authorization"] == "Bearer xapp-test"
    assert requests[0].url.path == "/api/apps.connections.open"


def test_open_connection_url_rejects_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(
        monkeypatch,
        lambda request: httpx.Response(200, json={"ok": False, "error": "invalid_auth"}),
    )
    client = SlackSocketModeClient(app_token="xapp-bad")

    with pytest.raises(SlackSocketModeError, match="invalid_auth"):
        asyncio.run(client.open_connection_url())


def test_open_connection_url_rejects_non_slack_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"ok": True, "url": "wss://example.com/link/?ticket=secret"},
        ),
    )
    client = SlackSocketModeClient(app_token="xapp-test")

    with pytest.raises(SlackSocketModeError, match="invalid WebSocket URL"):
        asyncio.run(client.open_connection_url())


def test_open_connection_url_honors_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "61"})
        return httpx.Response(
            200,
            json={"ok": True, "url": "wss://wss-primary.slack.com/link/?ticket=secret"},
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    _patch_httpx(monkeypatch, handler)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = SlackSocketModeClient(app_token="xapp-test")
    asyncio.run(client.open_connection_url())
    assert attempts == 2
    assert sleeps == [61.0]


def test_events_api_frame_is_admitted_then_acked() -> None:
    socket = _FakeSocket()

    async def scenario() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        reconnect = await SlackSocketModeClient._handle_frame(
            socket,
            json.dumps(
                {
                    "type": "events_api",
                    "envelope_id": "env-1",
                    "payload": {"event": {"type": "app_mention"}},
                }
            ),
            queue,
        )
        assert reconnect is False
        assert socket.sent == ['{"envelope_id":"env-1"}']
        assert queue.get_nowait() == {"event": {"type": "app_mention"}}

    asyncio.run(scenario())


def test_full_admission_queue_leaves_envelope_unacked() -> None:
    """No ACK on overload — Slack redelivers instead of local unbounded tasks."""
    socket = _FakeSocket()

    async def scenario() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        queue.put_nowait({"event": {"type": "app_mention"}})
        reconnect = await SlackSocketModeClient._handle_frame(
            socket,
            json.dumps(
                {
                    "type": "events_api",
                    "envelope_id": "env-overflow",
                    "payload": {"event": {"type": "message"}},
                }
            ),
            queue,
        )
        assert reconnect is False
        assert socket.sent == []
        assert queue.qsize() == 1

    asyncio.run(scenario())


def test_unsupported_envelope_is_acknowledged_without_dispatch() -> None:
    socket = _FakeSocket()

    async def scenario() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        reconnect = await SlackSocketModeClient._handle_frame(
            socket,
            '{"type":"slash_commands","envelope_id":"env-2","payload":{}}',
            queue,
        )
        assert reconnect is False
        assert queue.empty()

    asyncio.run(scenario())
    assert socket.sent == ['{"envelope_id":"env-2"}']


def test_disconnect_requests_fresh_connection() -> None:
    socket = _FakeSocket()

    async def scenario() -> bool:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        return await SlackSocketModeClient._handle_frame(
            socket,
            '{"type":"disconnect","reason":"refresh_requested"}',
            queue,
        )

    assert asyncio.run(scenario()) is True
    assert not socket.sent


@pytest.mark.parametrize("raw", ["not-json", "[]", b"\xff"])
def test_malformed_frames_are_ignored(raw: str | bytes) -> None:
    socket = _FakeSocket()

    async def scenario() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        reconnect = await SlackSocketModeClient._handle_frame(socket, raw, queue)
        assert reconnect is False
        assert queue.empty()

    asyncio.run(scenario())
    assert not socket.sent


def test_missing_app_token_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
    client = SlackSocketModeClient()
    assert client.configured is False
    with pytest.raises(SlackSocketModeError, match="not configured"):
        asyncio.run(client.open_connection_url())


def test_safe_error_never_echoes_unknown_exception_text() -> None:
    error = RuntimeError("wss://wss-primary.slack.com/link/?ticket=secret")
    assert SlackSocketModeClient._safe_error(error) == "RuntimeError"


def test_run_drains_admitted_events_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ACKed events still in the queue at stop are finished, not abandoned."""
    import websockets

    stopped = False
    handled: list[dict[str, Any]] = []

    class OneEventSocket(_FakeSocket):
        def __init__(self) -> None:
            super().__init__()
            self.frames = [
                json.dumps(
                    {
                        "type": "events_api",
                        "envelope_id": "env-1",
                        "payload": {"event": {"type": "app_mention"}},
                    }
                )
            ]

        async def recv(self) -> str:
            nonlocal stopped
            if self.frames:
                return self.frames.pop(0)
            stopped = True
            raise ConnectionError("closed")

    class FakeContext:
        async def __aenter__(self) -> OneEventSocket:
            return OneEventSocket()

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def fake_open(self) -> str:
        return "wss://wss-primary.slack.com/link/?ticket=secret"

    monkeypatch.setattr(websockets, "connect", lambda url, **kwargs: FakeContext())
    monkeypatch.setattr(SlackSocketModeClient, "open_connection_url", fake_open)

    async def on_event(payload: dict[str, Any]) -> None:
        await asyncio.sleep(0.05)
        handled.append(payload)

    client = SlackSocketModeClient(app_token="xapp-test")
    asyncio.run(client.run(on_event, lambda: stopped))
    assert handled == [{"event": {"type": "app_mention"}}]


def test_run_backs_off_across_connections_that_never_receive_a_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import websockets

    stopped = False
    waits: list[float] = []
    attempts = 0

    class FakeSocket(_FakeSocket):
        def __init__(self, *, succeeds: bool) -> None:
            super().__init__()
            self.succeeds = succeeds

        async def recv(self) -> str:
            nonlocal stopped
            if not self.succeeds:
                raise ConnectionError("handshake died before Slack hello")
            stopped = True
            return '{"type":"hello"}'

    class FakeContext:
        def __init__(self, socket: FakeSocket) -> None:
            self.socket = socket

        async def __aenter__(self) -> FakeSocket:
            return self.socket

        async def __aexit__(self, *args: Any) -> None:
            return None

    def fake_connect(url: str, **kwargs: Any) -> FakeContext:
        nonlocal attempts
        attempts += 1
        return FakeContext(FakeSocket(succeeds=attempts == 3))

    async def fake_open(self) -> str:
        return "wss://wss-primary.slack.com/link/?ticket=secret"

    async def fake_wait(delay: float, should_stop: Any) -> None:
        waits.append(delay)

    monkeypatch.setattr(websockets, "connect", fake_connect)
    monkeypatch.setattr(SlackSocketModeClient, "open_connection_url", fake_open)
    monkeypatch.setattr(SlackSocketModeClient, "_wait_or_stop", staticmethod(fake_wait))

    async def on_event(payload: dict[str, Any]) -> None:
        raise AssertionError("hello must not dispatch")

    client = SlackSocketModeClient(app_token="xapp-test")
    asyncio.run(client.run(on_event, lambda: stopped))
    assert attempts == 3
    assert waits == [1.0, 2.0]

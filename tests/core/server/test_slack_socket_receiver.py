"""Slack Socket Mode receiver and polling-fallback tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.messaging.binding import ChannelManager
from core.messaging.models import ChannelBinding
from core.messaging.slack_transport import SlackTransportError, reset_slack_transport
from core.server.supervised.slack_poller import SlackPoller


class _FakeTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str]] = []
        self.reactions: list[tuple[str, str, str]] = []
        self.history_calls = 0
        self.history_error: Exception | None = None

    @property
    def configured(self) -> bool:
        return True

    async def ais_available(self) -> bool:
        return True

    async def channel_history(
        self,
        channel_id: str,
        *,
        oldest: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        self.history_calls += 1
        if self.history_error:
            raise self.history_error
        return []

    async def add_reaction(self, channel_id: str, timestamp: str, emoji: str) -> None:
        self.reactions.append((channel_id, timestamp, emoji))

    async def post_message(
        self,
        channel_id: str,
        text: str,
        *,
        thread_ts: str = "",
    ) -> dict[str, Any]:
        self.posts.append((channel_id, text, thread_ts))
        return {"ok": True, "ts": "reply.1"}


@pytest.fixture()
def poller_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
    reset_slack_transport()
    created: list[SlackPoller] = []

    def factory(
        *,
        require_mention: bool = True,
        bot_user_id: str = "UGEODE",
    ) -> tuple[SlackPoller, ChannelManager, _FakeTransport]:
        manager = ChannelManager(bot_user_id=bot_user_id)
        manager.add_binding(
            ChannelBinding(
                channel="slack",
                channel_id="CBOUND",
                require_mention=require_mention,
            )
        )
        transport = _FakeTransport()
        poller = SlackPoller(manager)
        poller._transport = transport
        created.append(poller)
        return poller, manager, transport

    yield factory
    for poller in created:
        poller.stop()
    reset_slack_transport()


def test_socket_event_routes_and_replies_in_thread(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory()
    processed: list[tuple[str, dict[str, Any]]] = []

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        processed.append((content, metadata))
        return "done"

    manager.set_async_processor(processor)
    asyncio.run(
        poller._handle_socket_event(
            {
                "event_id": "Ev1",
                "event": {
                    "type": "app_mention",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "<@UGEODE> check this",
                    "ts": "171.25",
                },
            }
        )
    )

    assert processed[0][0] == "check this"
    assert processed[0][1]["channel_id"] == "CBOUND"
    assert processed[0][1]["thread_id"] == "171.25"
    assert transport.reactions == [
        ("CBOUND", "171.25", "eyes"),
        ("CBOUND", "171.25", "white_check_mark"),
    ]
    assert transport.posts == [("CBOUND", "done", "171.25")]


def test_thread_reply_continues_without_remention(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory()
    processed: list[tuple[str, str, str]] = []

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        processed.append((content, metadata["thread_id"], metadata["session_key"]))
        return f"reply-{len(processed)}"

    manager.set_async_processor(processor)

    async def scenario() -> None:
        await poller._handle_socket_event(
            {
                "event_id": "Ev-thread-root",
                "event": {
                    "type": "app_mention",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "<@UGEODE> start here",
                    "ts": "171.30",
                },
            }
        )
        await poller._handle_socket_event(
            {
                "event_id": "Ev-thread-followup",
                "event": {
                    "type": "message",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "continue without another mention",
                    "thread_ts": "171.30",
                    "ts": "171.31",
                },
            }
        )

    asyncio.run(scenario())

    assert processed == [
        ("start here", "171.30", "gateway:slack:cbound:u1:171_30"),
        (
            "continue without another mention",
            "171.30",
            "gateway:slack:cbound:u1:171_30",
        ),
    ]
    assert transport.posts == [
        ("CBOUND", "reply-1", "171.30"),
        ("CBOUND", "reply-2", "171.30"),
    ]
    assert transport.reactions == [
        ("CBOUND", "171.30", "eyes"),
        ("CBOUND", "171.30", "white_check_mark"),
        ("CBOUND", "171.31", "eyes"),
        ("CBOUND", "171.31", "white_check_mark"),
    ]


def test_unmentioned_reply_in_untracked_thread_is_ignored(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory()
    calls = 0

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "unexpected"

    manager.set_async_processor(processor)
    asyncio.run(
        poller._handle_socket_event(
            {
                "event_id": "Ev-untracked-thread",
                "event": {
                    "type": "message",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "continue this unrelated thread",
                    "thread_ts": "170.00",
                    "ts": "171.32",
                },
            }
        )
    )

    assert calls == 0
    assert not transport.posts
    assert not transport.reactions


def test_engaged_thread_is_scoped_to_its_channel(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory()
    manager.add_binding(ChannelBinding(channel="slack", channel_id="COTHER", require_mention=True))
    calls = 0

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "done"

    manager.set_async_processor(processor)

    async def scenario() -> None:
        await poller._handle_socket_event(
            {
                "event_id": "Ev-channel-root",
                "event": {
                    "type": "app_mention",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "<@UGEODE> engage",
                    "ts": "171.40",
                },
            }
        )
        await poller._handle_socket_event(
            {
                "event_id": "Ev-other-channel",
                "event": {
                    "type": "message",
                    "channel": "COTHER",
                    "user": "U1",
                    "text": "same timestamp, different channel",
                    "thread_ts": "171.40",
                    "ts": "171.41",
                },
            }
        )

    asyncio.run(scenario())

    assert calls == 1
    assert transport.posts == [("CBOUND", "done", "171.40")]


def test_engaged_thread_expires_after_ttl(
    poller_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poller, _, _ = poller_factory()
    poller._engaged_threads[("CBOUND", "171.50")] = 1.0
    monkeypatch.setattr(
        "core.server.supervised.slack_poller.time.monotonic",
        lambda: 1.0 + poller.THREAD_CONTINUATION_TTL_S + 0.1,
    )

    assert poller._is_engaged_thread("CBOUND", "171.50") is False
    assert not poller._engaged_threads


def test_persisted_session_restores_thread_engagement_after_restart(
    poller_factory: Any,
) -> None:
    poller, manager, transport = poller_factory()
    checked_keys: list[str] = []
    processed: list[str] = []

    def session_exists(session_key: str) -> bool:
        checked_keys.append(session_key)
        return session_key == "gateway:slack:cbound:u1:171_60"

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        processed.append(content)
        return "resumed"

    manager.set_session_exists_checker(session_exists)
    manager.set_async_processor(processor)
    assert not poller._engaged_threads

    asyncio.run(
        poller._handle_socket_event(
            {
                "event_id": "Ev-after-restart",
                "event": {
                    "type": "message",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "pick up where we left off",
                    "thread_ts": "171.60",
                    "ts": "171.61",
                },
            }
        )
    )

    assert checked_keys == ["gateway:slack:cbound:u1:171_60"]
    assert processed == ["pick up where we left off"]
    assert transport.posts == [("CBOUND", "resumed", "171.60")]
    assert ("CBOUND", "171.60") in poller._engaged_threads


def test_message_and_app_mention_for_same_timestamp_are_deduplicated(
    poller_factory: Any,
) -> None:
    poller, manager, transport = poller_factory()
    calls = 0

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "once"

    manager.set_async_processor(processor)

    async def scenario() -> None:
        for event_type, event_id in (("message", "Ev-message"), ("app_mention", "Ev-mention")):
            await poller._handle_socket_event(
                {
                    "event_id": event_id,
                    "event": {
                        "type": event_type,
                        "channel": "CBOUND",
                        "user": "U1",
                        "text": "<@UGEODE> hello",
                        "ts": "172.5",
                    },
                }
            )

    asyncio.run(scenario())
    assert calls == 1
    assert transport.posts == [("CBOUND", "once", "172.5")]


def test_app_mention_routes_when_bootstrap_bot_id_lookup_failed(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory(bot_user_id="")
    processed: list[str] = []

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        processed.append(content)
        return "done"

    manager.set_async_processor(processor)
    asyncio.run(
        poller._handle_socket_event(
            {
                "event_id": "Ev-no-bot-id",
                "event": {
                    "type": "app_mention",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "<@UUNKNOWN> still route this",
                    "ts": "172.6",
                },
            }
        )
    )
    assert processed == ["still route this"]
    assert transport.posts == [("CBOUND", "done", "172.6")]


def test_unbound_and_bot_events_are_ignored(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory(require_mention=False)
    calls = 0

    async def processor(content: str, metadata: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "unexpected"

    manager.set_async_processor(processor)

    async def scenario() -> None:
        await poller._handle_socket_event(
            {
                "event_id": "Ev-unbound",
                "event": {
                    "type": "message",
                    "channel": "COTHER",
                    "user": "U1",
                    "text": "hello",
                    "ts": "173.1",
                },
            }
        )
        await poller._handle_socket_event(
            {
                "event_id": "Ev-bot",
                "event": {
                    "type": "message",
                    "channel": "CBOUND",
                    "bot_id": "B1",
                    "text": "hello",
                    "ts": "173.2",
                },
            }
        )

    asyncio.run(scenario())
    assert calls == 0
    assert not transport.posts


def test_invalid_timestamp_is_ignored(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory(require_mention=False)
    manager.set_async_processor(lambda content, metadata: "unexpected")
    asyncio.run(
        poller._handle_socket_event(
            {
                "event_id": "Ev-invalid",
                "event": {
                    "type": "message",
                    "channel": "CBOUND",
                    "user": "U1",
                    "text": "hello",
                    "ts": "not-a-timestamp",
                },
            }
        )
    )
    assert not transport.posts


def test_polling_fallback_cools_down_inaccessible_channel(poller_factory: Any) -> None:
    poller, manager, transport = poller_factory(require_mention=False)
    transport.history_error = SlackTransportError("conversations.history: not_in_channel")

    async def scenario() -> None:
        await poller._poll_channel("CBOUND")
        await poller._poll_channel("CBOUND")

    asyncio.run(scenario())
    assert transport.history_calls == 1
    assert poller._poll_retry_after["CBOUND"] > 0


def test_app_token_selects_socket_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
    reset_slack_transport()
    manager = ChannelManager()
    poller = SlackPoller(manager)
    called = False

    class FakeSocketMode:
        configured = True

        async def run(self, on_event: Any, should_stop: Any) -> None:
            nonlocal called
            called = True

    poller._socket_mode = FakeSocketMode()
    try:
        assert poller.inbound_mode == "socket_mode"
        asyncio.run(poller._run_loop_async())
        assert called is True
    finally:
        poller.stop()
        reset_slack_transport()

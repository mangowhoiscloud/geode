"""SlackTransport contract — chunking, retry, availability cache, token
resolution. No network: httpx is faked at the client boundary."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from core.messaging.slack_transport import (
    MAX_MESSAGE_CHARS,
    SlackTransport,
    SlackTransportError,
    get_slack_transport,
    reset_slack_transport,
    resolve_bot_token,
)


class _FakeAPI:
    """MockTransport-backed Slack API with scriptable responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, list[dict[str, Any]]] = {}
        self.rate_limit_once: set[str] = set()

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit("/", 1)[-1]
            payload = json.loads(request.content or b"{}")
            self.calls.append((method, payload))
            if method in self.rate_limit_once:
                self.rate_limit_once.discard(method)
                return httpx.Response(429, headers={"Retry-After": "0"})
            queued = self.responses.get(method)
            body = queued.pop(0) if queued else {"ok": True, "ts": "111.222"}
            return httpx.Response(200, json=body)

        return httpx.MockTransport(handler)


@pytest.fixture()
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeAPI:
    api = _FakeAPI()
    real_client = httpx.AsyncClient

    def _patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = api.transport()
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _patched_client)
    return api


def _transport() -> SlackTransport:
    return SlackTransport(token="xoxb-test-token")


def test_configured_requires_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
    assert SlackTransport(token="").configured is False
    assert _transport().configured is True


def test_resolve_token_prefers_env_then_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-env")
    assert resolve_bot_token() == "xoxb-env"
    monkeypatch.delenv("SLACK_BOT_TOKEN")
    env_file = tmp_path / ".env"
    env_file.write_text("SLACK_BOT_TOKEN=xoxb-dotenv\n")
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", env_file)
    assert resolve_bot_token() == "xoxb-dotenv"


def test_post_message_short_text(fake_api: _FakeAPI) -> None:
    data = asyncio.run(_transport().post_message("C123", "hello"))
    assert data["ts"] == "111.222"
    assert fake_api.calls == [
        ("chat.postMessage", {"channel": "C123", "text": "hello", "mrkdwn": True})
    ]


def test_post_message_threads_follow_up_chunks(fake_api: _FakeAPI) -> None:
    fake_api.responses["chat.postMessage"] = [
        {"ok": True, "ts": "first.ts"},
        {"ok": True, "ts": "second.ts"},
    ]
    long_text = "A" * (MAX_MESSAGE_CHARS + 10)
    data = asyncio.run(_transport().post_message("C123", long_text))
    assert data["ts"] == "first.ts"  # first chunk anchors
    assert len(fake_api.calls) == 2
    first, second = fake_api.calls
    assert first[1]["text"].startswith("(1/2)")
    assert second[1]["thread_ts"] == "first.ts"  # follow-up threads under it


def test_chunk_prefers_newline_boundary() -> None:
    text = ("x" * 100 + "\n") * 500  # well over one chunk
    chunks = SlackTransport._chunk(text[: MAX_MESSAGE_CHARS + 500])
    assert len(chunks) == 2
    assert not chunks[0].endswith("x" * 101)  # cut at a newline, not mid-line


def test_rate_limit_retries_then_succeeds(fake_api: _FakeAPI) -> None:
    fake_api.rate_limit_once.add("chat.postMessage")
    data = asyncio.run(_transport().post_message("C123", "hello"))
    assert data["ts"] == "111.222"
    assert len(fake_api.calls) == 2  # 429 then success


def test_api_error_raises(fake_api: _FakeAPI) -> None:
    fake_api.responses["chat.postMessage"] = [{"ok": False, "error": "channel_not_found"}]
    with pytest.raises(SlackTransportError, match="channel_not_found"):
        asyncio.run(_transport().post_message("C123", "hello"))


def test_channel_history_passes_oldest(fake_api: _FakeAPI) -> None:
    fake_api.responses["conversations.history"] = [
        {"ok": True, "messages": [{"ts": "2.0", "text": "hi"}]}
    ]
    messages = asyncio.run(_transport().channel_history("C123", oldest="1.0", limit=5))
    assert messages == [{"ts": "2.0", "text": "hi"}]
    assert fake_api.calls[0][1] == {"channel": "C123", "limit": 5, "oldest": "1.0"}


def test_add_reaction_already_reacted_is_success(fake_api: _FakeAPI) -> None:
    fake_api.responses["reactions.add"] = [{"ok": False, "error": "already_reacted"}]
    asyncio.run(_transport().add_reaction("C123", "1.0", "eyes"))  # must not raise


def test_availability_caches_auth_test(fake_api: _FakeAPI) -> None:
    transport = _transport()
    assert asyncio.run(transport.ais_available()) is True
    assert asyncio.run(transport.ais_available()) is True
    auth_calls = [c for c in fake_api.calls if c[0] == "auth.test"]
    assert len(auth_calls) == 1  # second probe served from cache


def test_unconfigured_calls_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
    transport = SlackTransport(token="")
    with pytest.raises(SlackTransportError, match="not configured"):
        asyncio.run(transport.post_message("C123", "hello"))
    assert asyncio.run(transport.ais_available()) is False


def test_default_transport_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    reset_slack_transport()
    try:
        assert get_slack_transport() is get_slack_transport()
    finally:
        reset_slack_transport()


def test_notification_fallback_crosses_threads() -> None:
    """PR-SLACK-TRANSPORT: poller daemon threads read the process
    fallback — set in the main thread, visible in a fresh thread."""
    import threading

    from core.mcp.notification_port import get_notification, set_notification

    marker = object()
    set_notification(marker)  # type: ignore[arg-type]
    seen: list[Any] = []
    t = threading.Thread(target=lambda: seen.append(get_notification()))
    t.start()
    t.join()
    set_notification(None)
    assert seen == [marker]

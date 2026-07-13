"""Pending-ask store contract — first-reply-wins, expiry, reply routing."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

from core.memory.pending_ask import (
    ALREADY_ANSWERED,
    EXPIRED,
    NOT_FOUND,
    RESOLVED,
    PendingAsk,
    PendingAskStore,
    ahandle_ask_reply,
    apublish_clarification_ask,
    format_ask_notification,
    parse_ask_reply,
)


def _make_store(tmp_path: Any) -> PendingAskStore:
    return PendingAskStore(tmp_path / "pending_asks")


# ---------------------------------------------------------------------------
# Store basics
# ---------------------------------------------------------------------------


def test_create_get_roundtrip(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Which repo?", session_id="s-abc123", source="scheduled:job1")
    loaded = store.get(ask.ask_id)
    assert loaded is not None
    assert loaded.question == "Which repo?"
    assert loaded.session_id == "s-abc123"
    assert loaded.source == "scheduled:job1"
    assert loaded.status == "pending"
    assert len(loaded.ask_id) == 8


def test_find_exact_prefix_and_ambiguous(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q1", session_id="s1", source="scheduled:a")
    assert store.find(ask.ask_id) is not None
    assert store.find(ask.ask_id[:4]) is not None
    assert store.find(ask.ask_id[:4].upper()) is not None
    assert store.find("zzzzzzzz") is None
    # Ambiguity: empty prefix matches everything → refuse once >1 asks exist
    store.create("Q2", session_id="s2", source="scheduled:b")
    assert store.find("") is None


def test_list_pending_excludes_answered_and_stale(tmp_path):
    store = _make_store(tmp_path)
    open_ask = store.create("open", session_id="s1", source="scheduled:a")
    answered = store.create("answered", session_id="s2", source="scheduled:b")
    store.resolve(answered.ask_id, "yes", answered_by="test")
    stale = store.create("stale", session_id="s3", source="scheduled:c")
    stale.created_at = time.time() - 80 * 3600
    from core.memory.atomic_write import atomic_write_json

    atomic_write_json(store.asks_dir / f"{stale.ask_id}.json", stale.to_dict(), indent=2)

    pending_ids = {a.ask_id for a in store.list_pending()}
    assert pending_ids == {open_ask.ask_id}
    assert len(store.list_asks()) == 3


# ---------------------------------------------------------------------------
# First-reply-wins resolution
# ---------------------------------------------------------------------------


def test_resolve_first_reply_wins(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s1", source="scheduled:a")

    outcome1, first = store.resolve(ask.ask_id, "answer one", answered_by="cli:alice")
    assert outcome1 == RESOLVED
    assert first is not None and first.answer == "answer one"

    outcome2, second = store.resolve(ask.ask_id, "answer two", answered_by="slack:bob")
    assert outcome2 == ALREADY_ANSWERED
    assert second is not None
    assert second.answer == "answer one"  # the losing reply never overwrites
    assert second.answered_by == "cli:alice"


def test_resolve_expired_and_not_found(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s1", source="scheduled:a")
    ask.created_at = time.time() - 80 * 3600
    from core.memory.atomic_write import atomic_write_json

    atomic_write_json(store.asks_dir / f"{ask.ask_id}.json", ask.to_dict(), indent=2)

    outcome, expired = store.resolve(ask.ask_id, "late", answered_by="cli:x")
    assert outcome == EXPIRED
    assert expired is not None and expired.status == "expired"
    # Expiry is persisted
    assert store.get(ask.ask_id).status == "expired"

    assert store.resolve("deadbeef", "x", answered_by="y")[0] == NOT_FOUND


def test_purge_stale_removes_old_files(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("old", session_id="s1", source="scheduled:a")
    import os

    old = time.time() - 15 * 24 * 3600
    os.utime(store.asks_dir / f"{ask.ask_id}.json", (old, old))
    assert store.purge_stale() == 1
    assert store.get(ask.ask_id) is None


# ---------------------------------------------------------------------------
# Reply grammar
# ---------------------------------------------------------------------------


def test_parse_ask_reply_shapes():
    assert parse_ask_reply("ask 3f2a9c1b use repo geode") == ("3f2a9c1b", "use repo geode")
    assert parse_ask_reply("/ask 3F2A9C1B: yes") == ("3f2a9c1b", "yes")
    assert parse_ask_reply("ASK abcd do\nthe second line") == ("abcd", "do\nthe second line")
    assert parse_ask_reply("  ask 12ab  answer  ") == ("12ab", "answer")


def test_parse_ask_reply_rejects_non_replies():
    assert parse_ask_reply("task abc123 do it") is None
    assert parse_ask_reply("ask") is None
    assert parse_ask_reply("ask 3f2a9c1b") is None  # no answer text
    assert parse_ask_reply("asking 3f2a9c1b about repos") is None
    assert parse_ask_reply("please ask 3f2a9c1b something") is None
    assert parse_ask_reply("") is None


# ---------------------------------------------------------------------------
# Publish (notification side)
# ---------------------------------------------------------------------------


class _FakeNotification:
    def __init__(self, *, success: bool = True, raise_on_send: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self._success = success
        self._raise = raise_on_send

    async def asend_message(self, channel, recipient, message, *, severity="info", **kwargs):
        from core.mcp.notification_port import NotificationResult

        if self._raise:
            raise RuntimeError("send blew up")
        self.sent.append((channel, recipient, message))
        return NotificationResult(success=self._success, channel=channel)

    async def ais_available(self, channel=None):
        return True

    def list_channels(self):
        return ["slack"]


def test_publish_persists_and_notifies(tmp_path):
    from core.mcp.notification_port import set_notification

    store = _make_store(tmp_path)
    fake = _FakeNotification()
    set_notification(fake)
    try:
        ask = asyncio.run(
            apublish_clarification_ask(
                "Which branch?", session_id="s-42", source="scheduled:nightly", store=store
            )
        )
    finally:
        set_notification(None)

    assert ask is not None
    assert len(fake.sent) == 1
    _channel, _recipient, message = fake.sent[0]
    assert ask.ask_id in message
    assert "Which branch?" in message
    assert "geode ask answer" in message
    stored = store.get(ask.ask_id)
    assert stored.notified_channel != ""


def test_publish_without_adapter_still_persists(tmp_path):
    from core.mcp.notification_port import set_notification

    store = _make_store(tmp_path)
    set_notification(None)
    ask = asyncio.run(
        apublish_clarification_ask("Q", session_id="s-1", source="scheduled:x", store=store)
    )
    assert ask is not None
    assert store.get(ask.ask_id) is not None
    assert store.get(ask.ask_id).notified_channel == ""


def test_publish_survives_adapter_exception(tmp_path):
    from core.mcp.notification_port import set_notification

    store = _make_store(tmp_path)
    set_notification(_FakeNotification(raise_on_send=True))
    try:
        ask = asyncio.run(
            apublish_clarification_ask("Q", session_id="s-1", source="scheduled:x", store=store)
        )
    finally:
        set_notification(None)
    assert ask is not None
    assert store.get(ask.ask_id) is not None


def test_record_notified_never_clobbers_a_won_answer(tmp_path):
    """Race shape: reply lands between create() and record_notified()."""
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s-1", source="scheduled:x")
    stale_copy = store.get(ask.ask_id)  # what the publisher still holds
    store.resolve(ask.ask_id, "the answer", answered_by="slack:fast")

    store.record_notified(stale_copy, channel="slack", recipient="#ops")

    current = store.get(ask.ask_id)
    assert current.status == "answered"
    assert current.answer == "the answer"
    assert current.answered_by == "slack:fast"
    assert current.notified_channel == "slack"
    assert current.notified_recipient == "#ops"


def test_format_notification_contains_reply_instructions():
    ask = PendingAsk(ask_id="ab12cd34", question="Q?", session_id="s-9", source="scheduled:j")
    text = format_ask_notification(ask)
    assert "ask ab12cd34" in text
    assert "geode ask answer ab12cd34" in text


# ---------------------------------------------------------------------------
# Reply routing (ahandle_ask_reply)
# ---------------------------------------------------------------------------


class _FakeCheckpoint:
    def __init__(self, states: dict[str, Any]) -> None:
        self._states = states

    def load(self, session_id: str):
        return self._states.get(session_id)


def _fake_state(session_id: str = "s-42") -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        messages=[{"role": "user", "content": "original request"}],
    )


def test_ahandle_non_reply_returns_none(tmp_path):
    async def _boom(_state, _answer):  # pragma: no cover — must not run
        raise AssertionError("continuation must not run")

    result = asyncio.run(
        ahandle_ask_reply(
            "just a normal message",
            answered_by="slack:u1",
            run_continuation=_boom,
            store=_make_store(tmp_path),
        )
    )
    assert result is None


def test_ahandle_unknown_id_explicit_slash_errors(tmp_path):
    async def _boom(_state, _answer):  # pragma: no cover
        raise AssertionError

    result = asyncio.run(
        ahandle_ask_reply(
            "/ask deadbeef go ahead",
            answered_by="slack:u1",
            run_continuation=_boom,
            store=_make_store(tmp_path),
        )
    )
    assert result is not None and "Unknown ask id" in result


def test_ahandle_bare_ask_with_unknown_id_falls_through(tmp_path):
    """Ordinary chat like 'ask cafe about deployment' is not swallowed."""

    async def _boom(_state, _answer):  # pragma: no cover
        raise AssertionError

    result = asyncio.run(
        ahandle_ask_reply(
            "ask cafe about the deployment",
            answered_by="slack:u1",
            run_continuation=_boom,
            store=_make_store(tmp_path),
        )
    )
    assert result is None


def test_ahandle_happy_path_runs_continuation(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Which repo?", session_id="s-42", source="scheduled:j")
    seen: dict[str, Any] = {}

    async def _cont(state, answer):
        seen["session_id"] = state.session_id
        seen["answer"] = answer
        return "continued fine"

    result = asyncio.run(
        ahandle_ask_reply(
            f"ask {ask.ask_id} use geode",
            answered_by="slack:u1",
            run_continuation=_cont,
            store=store,
            checkpoint=_FakeCheckpoint({"s-42": _fake_state()}),
        )
    )
    assert result == "continued fine"
    assert seen == {"session_id": "s-42", "answer": "use geode"}
    assert store.get(ask.ask_id).status == "answered"


def test_ahandle_second_reply_gets_first_reply_wins(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s-42", source="scheduled:j")
    checkpoint = _FakeCheckpoint({"s-42": _fake_state()})

    async def _cont(_state, _answer):
        return "ok"

    asyncio.run(
        ahandle_ask_reply(
            f"ask {ask.ask_id} first",
            answered_by="slack:u1",
            run_continuation=_cont,
            store=store,
            checkpoint=checkpoint,
        )
    )
    second = asyncio.run(
        ahandle_ask_reply(
            f"ask {ask.ask_id} second",
            answered_by="slack:u2",
            run_continuation=_cont,
            store=store,
            checkpoint=checkpoint,
        )
    )
    assert second is not None
    assert "already answered" in second
    assert "first reply wins" in second


def test_ahandle_missing_checkpoint_records_answer(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s-gone", source="scheduled:j")

    async def _boom(_state, _answer):  # pragma: no cover
        raise AssertionError

    result = asyncio.run(
        ahandle_ask_reply(
            f"ask {ask.ask_id} yes",
            answered_by="cli:me",
            run_continuation=_boom,
            store=store,
            checkpoint=_FakeCheckpoint({}),
        )
    )
    assert result is not None and "checkpoint" in result
    assert store.get(ask.ask_id).status == "answered"


def test_ahandle_continuation_failure_is_honest(tmp_path):
    store = _make_store(tmp_path)
    ask = store.create("Q", session_id="s-42", source="scheduled:j")

    async def _cont(_state, _answer):
        raise RuntimeError("loop exploded")

    result = asyncio.run(
        ahandle_ask_reply(
            f"ask {ask.ask_id} yes",
            answered_by="cli:me",
            run_continuation=_cont,
            store=store,
            checkpoint=_FakeCheckpoint({"s-42": _fake_state()}),
        )
    )
    assert result is not None
    assert "continuation failed" in result
    assert store.get(ask.ask_id).status == "answered"

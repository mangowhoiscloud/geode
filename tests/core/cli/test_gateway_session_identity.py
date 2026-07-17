"""Gateway machine-instance identity — one messaging thread, one session.

v0.99.329: the gateway derives a stable checkpoint session id from the
binding session_key so a thread's turns share ONE checkpoint chain
(docs/architecture/session-state-machine.md § Machine instance).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.cli.typer_serve import (
    _gateway_checkpoint_is_resumable,
    _gateway_checkpoint_session_id,
    _gateway_resume_messages,
    _gateway_session_can_resume,
    _gateway_session_is_terminal,
    _restore_gateway_loop,
)


def test_derivation_is_stable():
    key = "slack:C123:U9:thread-1"
    assert _gateway_checkpoint_session_id(key) == _gateway_checkpoint_session_id(key)


def test_distinct_threads_get_distinct_instances():
    base = _gateway_checkpoint_session_id("slack:C123:U9:thread-1")
    assert base != _gateway_checkpoint_session_id("slack:C123:U9:thread-2")
    assert base != _gateway_checkpoint_session_id("telegram:C123:U9:thread-1")


def test_id_shape_pins_sha256():
    import hashlib

    key = "slack:C1:U1:t1"
    sid = _gateway_checkpoint_session_id(key)
    assert sid.startswith("s-gw-")
    assert sid == "s-gw-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def test_only_active_or_paused_gateway_checkpoint_is_resumable():
    assert _gateway_checkpoint_is_resumable(SimpleNamespace(status="active"))
    assert _gateway_checkpoint_is_resumable(SimpleNamespace(status="paused"))
    assert not _gateway_checkpoint_is_resumable(SimpleNamespace(status="completed"))
    assert not _gateway_checkpoint_is_resumable(SimpleNamespace(status="error"))


def test_gateway_history_falls_back_to_resumable_checkpoint():
    checkpoint = SimpleNamespace(
        status="active",
        messages=[{"role": "user", "content": "persisted"}],
    )

    assert _gateway_resume_messages(None, checkpoint) == checkpoint.messages
    assert _gateway_resume_messages(
        {"messages": [{"role": "user", "content": "fresh"}]},
        checkpoint,
    ) == [{"role": "user", "content": "fresh"}]
    assert (
        _gateway_resume_messages(
            None,
            SimpleNamespace(status="completed", messages=checkpoint.messages),
        )
        == []
    )


def test_gateway_resume_probe_prefers_durable_machine_status():
    session_key = "gateway:slack:c1:u1:171_1"
    expected_id = _gateway_checkpoint_session_id(session_key)

    class Store:
        def exists(self, key: str) -> bool:
            assert key == session_key
            return True

    class Checkpoint:
        state = SimpleNamespace(status="paused")

        def load(self, session_id: str):
            assert session_id == expected_id
            return self.state

    checkpoint = Checkpoint()
    assert _gateway_session_can_resume(session_key, Store(), checkpoint)
    checkpoint.state = SimpleNamespace(status="completed")
    assert not _gateway_session_can_resume(session_key, Store(), checkpoint)


def test_terminal_probe_requires_explicit_ended_checkpoint():
    session_key = "gateway:slack:c1:u1:171_2"
    expected_id = _gateway_checkpoint_session_id(session_key)

    class Checkpoint:
        def __init__(self, state):
            self.state = state

        def load(self, session_id):
            assert session_id == expected_id
            return self.state

    completed = SimpleNamespace(status="completed")
    errored = SimpleNamespace(status="error")
    paused = SimpleNamespace(status="paused")
    assert _gateway_session_is_terminal(session_key, Checkpoint(completed))
    assert _gateway_session_is_terminal(session_key, Checkpoint(errored))
    assert not _gateway_session_is_terminal(session_key, Checkpoint(paused))
    # No durable record at all is NOT terminal — the engagement cache may
    # legitimately bridge the pre-checkpoint window.
    assert not _gateway_session_is_terminal(session_key, Checkpoint(None))


def test_gateway_checkpoint_round_trip_restores_thread_history(tmp_path: Path):
    from core.memory.session import InMemorySessionStore
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

    session_key = "gateway:slack:cbound:u1:171_30"
    session_id = _gateway_checkpoint_session_id(session_key)
    messages = [
        {"role": "user", "content": "start here"},
        {"role": "assistant", "content": "ready"},
    ]
    SessionCheckpoint(session_dir=tmp_path).save(
        SessionState(session_id=session_id, status="active", messages=messages)
    )

    restarted_checkpoint = SessionCheckpoint(session_dir=tmp_path)
    empty_l2 = InMemorySessionStore()
    assert _gateway_session_can_resume(session_key, empty_l2, restarted_checkpoint)
    restored = restarted_checkpoint.load(session_id)
    restored_messages = _gateway_resume_messages(None, restored)
    assert [(item["role"], item["content"]) for item in restored_messages] == [
        ("user", "start here"),
        ("assistant", "ready"),
    ]


def test_gateway_loop_restore_matches_cli_machine_and_model_contract():
    class Loop:
        model = "new-default"
        restored = None
        updated_model = ""

        def restore_from_checkpoint(self, state):
            self.restored = state

        async def update_model_async(self, model: str):
            self.updated_model = model

    state = SimpleNamespace(model="persisted-model")
    loop = Loop()
    asyncio.run(_restore_gateway_loop(loop, state))

    assert loop.restored is state
    assert loop.updated_model == "persisted-model"

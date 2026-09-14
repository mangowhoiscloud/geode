"""Owned dream threads stop before their observation sinks are closed."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.hooks import HookEvent, HookSystem
from core.hooks.llm_observation import observe_llm_call
from core.llm.adapters.base import UsageSummary
from core.memory.dreaming import DreamingService, DreamResult, make_dreaming_handler
from core.memory.session_manager import SessionManager
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink


def test_dreaming_hook_keeps_each_turn_effort_across_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "agentic_effort", "low")
    dispatch = AsyncMock(return_value=SimpleNamespace(text="summary"))
    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)
    manager = SessionManager(tmp_path / "effort.db")
    owner = DreamingService(session_manager=manager)
    _name, handler = make_dreaming_handler(service=owner)
    try:
        for session_id, effort in (("default", None), ("explicit", "max")):
            manager.upsert_messages(session_id, [{"role": "user", "content": "context", "seq": 0}])
            handler(
                HookEvent.TURN_COMPLETED,
                {"session_id": session_id, "rounds": 1, "model": "gpt-5.6-sol", "effort": effort},
            )
        asyncio.run(owner.settle(deadline=time.monotonic() + 2))
        assert {
            call.kwargs["correlation"]["session_id"]: call.kwargs["effort"]
            for call in dispatch.await_args_list
        } == {"default": "low", "explicit": "max"}
        assert dispatch.await_count == 2
        assert settings.agentic_effort == "low"
    finally:
        owner.close()
        manager.close()


@pytest.mark.parametrize("mode", ["settle", "cancel", "deadline", "uncooperative"])
def test_background_lifecycle_keeps_terminal_evidence_before_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "events.db")
    hooks.register_sink(HookPersistenceSink(store, session_key="synthetic", run_id="dream-test"))
    manager = SessionManager(tmp_path / "sessions.db")
    manager.upsert_messages("s", [{"role": "user", "content": "synthetic", "seq": 0}])
    entered, released = threading.Event(), threading.Event()
    owner = DreamingService(session_manager=manager, hooks=hooks)

    async def provider() -> SimpleNamespace:
        entered.set()
        if mode == "uncooperative":
            assert released.wait(2), "test failed to release its synthetic blocking provider"
        else:
            while not released.is_set():
                await asyncio.sleep(0.001)
        return SimpleNamespace(text="synthetic summary", usage=UsageSummary(input_tokens=5))

    async def dispatch(_prompt: str, **kwargs: Any) -> SimpleNamespace:
        return await observe_llm_call(
            provider,
            hooks=kwargs["hooks"],
            correlation=kwargs["correlation"],
            model="synthetic",
            provider="openai",
            adapter="synthetic",
            purpose="text_completion",
        )

    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)

    async def run() -> None:
        if mode == "deadline":
            owner.set_deadline(time.monotonic() + 0.2)
        thread = owner.dream_session_background("s", provider="openai", model="synthetic")
        assert await asyncio.to_thread(entered.wait, 1)
        owner.stop_admission()
        with pytest.raises(RuntimeError, match="admission"):
            owner.dream_session_background("s", provider="openai", model="synthetic")
        if mode == "settle":
            released.set()
            await owner.settle(deadline=time.monotonic() + 1)
        elif mode == "deadline":
            await owner.settle(deadline=time.monotonic() + 1)
        elif mode == "uncooperative":
            with pytest.raises(TimeoutError, match="shutdown incomplete"):
                await owner.aclose(deadline=time.monotonic() + 0.02)
            assert thread.is_alive()
            released.set()
        await owner.aclose(deadline=time.monotonic() + 1)
        assert not thread.is_alive()
        assert hooks.closed is False

    try:
        asyncio.run(run())
        starts = store.read(event_filter=HookEvent.LLM_CALL_STARTED.value)
        ends = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)
        assert len(starts) == len(ends) == 1
        assert starts[0].llm_attempt_id == ends[0].llm_attempt_id
        if mode in {"cancel", "deadline"}:
            assert ends[0].payload["success"] is False
            assert ends[0].payload["error_type"] == "CancelledError"
            assert ends[0].payload["usage"] is None
            assert manager.list_context_artifacts(session_id="s", kinds=("dream",)) == []
        elif mode == "settle":
            assert ends[0].payload["success"] is True
            assert ends[0].payload["usage"]["input_tokens"] == 5
            assert len(manager.list_context_artifacts(session_id="s", kinds=("dream",))) == 1
    finally:
        released.set()
        owner.close(timeout_s=2)
        hooks.close()
        manager.close()


def test_expired_deadline_never_starts_a_dream_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = DreamingService()
    owner.set_deadline(time.monotonic() - 1)
    monkeypatch.setattr(
        threading.Thread, "start", lambda _self: pytest.fail("expired dream started a thread")
    )
    with pytest.raises(RuntimeError, match="admission"):
        owner.dream_session_background("synthetic")
    owner.close(timeout_s=0)


@pytest.mark.parametrize("stage", ["worker", "manager_close"])
def test_dead_worker_failure_remains_visible_after_a_later_job(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    owner = DreamingService()
    count = 0

    def fail_close() -> None:
        raise OSError("private cleanup exception")

    async def work(self: DreamingService, session_id: str, **_kwargs: Any) -> DreamResult:
        nonlocal count
        count += 1
        if count == 1:
            if stage == "worker":
                raise ValueError("private worker exception")
            self._session_manager = SimpleNamespace(close=fail_close)
        return DreamResult(None, session_id, False)

    monkeypatch.setattr(DreamingService, "dream_session", work)
    for _ in range(2):
        thread = owner.dream_session_background("synthetic")
        thread.join(1)
        assert not thread.is_alive()
    expected = "ValueError" if stage == "worker" else "OSError"
    assert count == 2
    with pytest.raises(RuntimeError, match=expected) as caught:
        asyncio.run(owner.aclose(deadline=time.monotonic() + 1))
    assert "private" not in str(caught.value)
    with pytest.raises(RuntimeError, match=expected):
        owner.close(timeout_s=0)


def test_failed_thread_start_does_not_leave_an_unjoinable_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = DreamingService()
    error = RuntimeError("synthetic thread start failure")

    def fail_start(_thread: threading.Thread) -> None:
        raise error

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError) as caught:
        owner.dream_session_background("synthetic")
    assert caught.value is error
    owner.close(timeout_s=0)


@pytest.mark.parametrize("stage", ["read", "artifact_preparation"])
def test_cancellation_during_sync_prelude_prevents_dispatch_and_artifact_write(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    entered, released = threading.Event(), threading.Event()
    effects: list[str] = []

    def block() -> None:
        entered.set()
        assert released.wait(2)

    class Session:
        def get_messages(self, _session_id: str) -> list[dict[str, Any]]:
            if stage == "read":
                block()
            return [{"role": "user", "content": "synthetic", "seq": 1}]

        def list_context_artifacts(self, **_kwargs: Any) -> list[Any]:
            return []

        def upsert_context_artifact(self, **_kwargs: Any) -> str:
            effects.append("upsert")
            return "synthetic-artifact"

    async def dispatch(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        effects.append("dispatch")
        return SimpleNamespace(text="synthetic summary")

    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source", lambda _p: "subscription"
    )
    if stage == "artifact_preparation":

        def estimate(_messages: Any) -> int:
            block()
            return 5

        monkeypatch.setattr("core.memory.dreaming.estimate_message_tokens", estimate)
    owner = DreamingService(session_manager=Session(), deadline=time.monotonic() + 60)
    try:
        thread = owner.dream_session_background("synthetic", model="synthetic")
        assert entered.wait(1)
        owner.cancel()
        released.set()
        thread.join(1)
        assert not thread.is_alive()
        assert effects == ([] if stage == "read" else ["dispatch"])
    finally:
        released.set()
        owner.close(timeout_s=1)


@pytest.mark.parametrize("stage", ["read", "write", "no_messages", "up_to_date"])
def test_actual_dream_result_retains_bounded_storage_error_for_drain(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    class Session:
        def get_messages(self, _session_id: str) -> list[dict[str, Any]]:
            if stage == "read":
                raise OSError("private read failure")
            return (
                []
                if stage == "no_messages"
                else [{"role": "user", "content": "synthetic", "seq": 1}]
            )

        def list_context_artifacts(self, **_kwargs: Any) -> list[Any]:
            return (
                [SimpleNamespace(source_end_seq=1, artifact_id="synthetic", content="synthetic")]
                if stage == "up_to_date"
                else []
            )

        def upsert_context_artifact(self, **_kwargs: Any) -> str:
            raise OSError("private write failure")

    async def dispatch(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(text="synthetic summary")

    monkeypatch.setattr("core.llm.adapters.dispatch.complete_text_via_adapters", dispatch)
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source", lambda _p: "subscription"
    )
    owner = DreamingService(session_manager=Session())
    thread = owner.dream_session_background("synthetic", model="synthetic")
    thread.join(1)
    assert not thread.is_alive()
    if stage in {"read", "write"}:
        with pytest.raises(RuntimeError, match="OSError") as caught:
            asyncio.run(owner.aclose(deadline=time.monotonic() + 1))
        assert "private" not in str(caught.value)
    else:
        asyncio.run(owner.aclose(deadline=time.monotonic() + 1))

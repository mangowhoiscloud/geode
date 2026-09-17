"""Shared offload wiring does not cross-delete another session's data."""

import asyncio

from core.hooks.system import HookEvent, HookSystem
from core.wiring.bootstrap import build_tool_offload


def test_session_end_does_not_delete_shared_store_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("core.config.settings.tool_offload_threshold", 1_000)
    monkeypatch.setattr("core.paths.PROJECT_TOOL_OFFLOAD", tmp_path / "offload")
    bus = HookSystem()

    first_store = build_tool_offload(session_id="runtime-session", hooks=bus)
    second_store = build_tool_offload(session_id="serve-session", hooks=bus)

    assert first_store is not None
    assert second_store is not None
    assert second_store.session_id == "serve-session"
    first_store.offload("first", {"value": 1})
    second_store.offload("second", {"value": 2})

    asyncio.run(bus.trigger_async(HookEvent.SESSION_ENDED, {"session_id": "other-session"}))

    assert first_store.recall("first") == {"value": 1}
    assert second_store.recall("second") == {"value": 2}

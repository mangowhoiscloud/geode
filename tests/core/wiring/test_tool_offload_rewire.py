"""The serve daemon wires tool offload twice on one hook bus.

Runtime bootstrap registers the cleanup hook first; supervised services then
rebuild the store with their own session id. After the hook-lifecycle
unification (#2593) both calls land on the same bus, and the second
registration crashed the daemon at startup with
``DuplicateHookRegistrationError`` (launchd EX_CONFIG, masked for days by a
manually started daemon holding the socket). The cleanup registration keeps
the last explicitly built store.
"""

import asyncio

from core.hooks.system import HookEvent, HookSystem
from core.wiring.bootstrap import build_tool_offload


def test_double_wire_on_one_bus_keeps_the_last_store(monkeypatch, tmp_path) -> None:
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

    asyncio.run(bus.trigger_async(HookEvent.SESSION_ENDED, {}))

    assert first_store.recall("first") == {"value": 1}
    assert "error" in second_store.recall("second")

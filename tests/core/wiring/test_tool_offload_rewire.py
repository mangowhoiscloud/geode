"""The serve daemon wires tool offload twice on one hook bus.

Runtime bootstrap registers the cleanup hook first; supervised services then
rebuild the store with their own session id. After the hook-lifecycle
unification (#2593) both calls land on the same bus, and the second
registration crashed the daemon at startup with
``DuplicateHookRegistrationError`` (launchd EX_CONFIG, masked for days by a
manually started daemon holding the socket). The rewire must follow the same
last-wins semantic as ``set_offload_store``.
"""

from core.hooks.system import HookSystem
from core.wiring.bootstrap import build_tool_offload


def test_double_wire_on_one_bus_keeps_the_last_store(monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings.tool_offload_threshold", 1_000)
    bus = HookSystem()

    first_store = build_tool_offload(session_id="runtime-session", hooks=bus)
    second_store = build_tool_offload(session_id="serve-session", hooks=bus)

    assert first_store is not None
    assert second_store is not None
    assert second_store.session_id == "serve-session"

    from core.orchestration.tool_offload import get_offload_store

    assert get_offload_store() is second_store

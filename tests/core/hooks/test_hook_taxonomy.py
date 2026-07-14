"""PR-HOOK-TAXONOMY (2026-07-14) guard tests.

Pins the taxonomy-redesign invariants:

- D5: every HookEvent satisfies ``NAME == VALUE.upper()``; the read-side
  ``LEGACY_EVENT_VALUES`` alias map covers exactly the renamed values;
  ``HookEventStore.read(event_filter=...)`` expands aliases both ways.
- D6: the replaced ``_fire_hook`` reimplementations delegate to
  ``core.hooks.dispatch`` (source-scan) and the dead
  ``ToolExecutor._fire_hook`` stays deleted.
- D7: ``dispatch.fire_hook`` warns (never raises) on a payload missing its
  ``REQUIRED_PAYLOAD_KEYS`` entry, and the repaired emit sites
  (isolated_execution ``SUBAGENT_COMPLETED``, seed-generation orchestrator
  ``SUBAGENT_*``) no longer trip the warning.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

import pytest
from core.hooks import dispatch as hooks_dispatch
from core.hooks.system import LEGACY_EVENT_VALUES, HookEvent, HookSystem, resolve_event_value

# ---------------------------------------------------------------------------
# D5 — naming convention + alias map
# ---------------------------------------------------------------------------


def test_every_member_name_matches_value() -> None:
    """One naming convention in the enum: NAME == VALUE.upper().

    (Past-participle enforcement is a naming-review concern, not testable.)
    """
    mismatches = [(m.name, m.value) for m in HookEvent if m.name != m.value.upper()]
    assert mismatches == []


def test_alias_map_covers_exactly_the_renamed_values() -> None:
    """The alias map holds exactly the pre-rename values.

    The audit named 7 tense-split members; ``llm_call_retry`` was an 8th
    NAME/VALUE mismatch the list missed — it had to be aligned too or the
    NAME == VALUE.upper() guard above could never hold.
    """
    assert LEGACY_EVENT_VALUES == {
        "session_start": "session_started",
        "session_end": "session_ended",
        "turn_complete": "turn_completed",
        "llm_call_start": "llm_call_started",
        "llm_call_end": "llm_call_ended",
        "llm_call_retry": "llm_call_retried",
        "tool_exec_start": "tool_exec_started",
        "tool_exec_end": "tool_exec_ended",
    }


def test_alias_targets_are_current_enum_values() -> None:
    current_values = {m.value for m in HookEvent}
    for old, new in LEGACY_EVENT_VALUES.items():
        assert new in current_values
        assert old not in current_values, f"legacy value {old!r} still on the enum"
        assert resolve_event_value(old) is HookEvent(new)


def test_resolve_event_value_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        resolve_event_value("no_such_event")


def test_event_store_filter_matches_legacy_and_canonical_rows(tmp_path: Path) -> None:
    """Rows stored under the pre-rename value must stay queryable when
    filtering by the canonical value, and vice versa."""
    from core.hooks.catalog import EventRetentionClass
    from core.observability.event_store import HookEventStore, HookEventWrite

    def _write(event: str, occurred_at: float) -> HookEventWrite:
        return HookEventWrite(
            occurred_at=occurred_at,
            session_key="s",
            run_id="r",
            event=event,
            dispatch_mode="observe",
            status="ok",
            retention_class=EventRetentionClass.STANDARD,
            handler_count=0,
            handler_error_count=0,
            blocked=False,
            block_reason="",
            actor_type="system",
            actor_id="t",
            action="session.ended",
            entity_type="session",
            entity_id="s",
            task_id=None,
            level="info",
            payload={},
        )

    store = HookEventStore(tmp_path / "events.db")
    try:
        store.append(_write("session_end", 100.0))  # legacy row
        store.append(_write("session_ended", 200.0))  # canonical row
        store.append(_write("tool_exec_ended", 300.0))  # unrelated event

        canonical = store.read(event_filter="session_ended")
        assert sorted(row.occurred_at for row in canonical) == [100.0, 200.0]
        legacy = store.read(event_filter="session_end")
        assert sorted(row.occurred_at for row in legacy) == [100.0, 200.0]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# D6 — single dispatch path
# ---------------------------------------------------------------------------


def test_replaced_fire_hook_sites_delegate_to_dispatch() -> None:
    """The formerly self-reimplemented emit helpers now call the shared
    ``core.hooks.dispatch`` path instead of open-coding try/except."""
    from core.agent.approval import ApprovalWorkflow
    from core.agent.tool_executor.processor import ToolCallProcessor
    from core.mcp import manager as mcp_manager
    from core.orchestration.isolated_execution import IsolatedRunner
    from plugins.seed_generation import orchestrator as seed_orchestrator

    delegating_sources = [
        inspect.getsource(ApprovalWorkflow._fire_hook),
        inspect.getsource(ApprovalWorkflow._fire_hook_async),
        inspect.getsource(ToolCallProcessor._fire_hook),
        inspect.getsource(ToolCallProcessor._fire_interceptor),
        inspect.getsource(ToolCallProcessor._fire_with_result),
        inspect.getsource(mcp_manager._fire_mcp_hook),
        inspect.getsource(IsolatedRunner._post_to_main),
        inspect.getsource(seed_orchestrator.Pipeline._emit_hook),
    ]
    for source in delegating_sources:
        assert "core.hooks.dispatch" in source, source
        # No open-coded exception swallowing around the trigger call.
        assert "except Exception" not in source, source


def test_dead_executor_fire_hook_stays_deleted() -> None:
    from core.agent.tool_executor.executor import ToolExecutor

    assert not hasattr(ToolExecutor, "_fire_hook")


def test_thin_wrappers_delegate_to_dispatch() -> None:
    """The already-thin module wrappers keep routing through dispatch."""
    import core.cli as cli_module
    from core.hooks import tool_hooks
    from core.llm.router import _hooks as router_hooks
    from core.self_improving.loop import _hooks as sil_hooks
    from core.tools import memory_tools

    for module, func_name in [
        (memory_tools, "_fire_hook"),
        (router_hooks, "_fire_hook"),
        (sil_hooks, "_fire_hook"),
        (tool_hooks, "fire_tool_hook"),
        (cli_module, "_fire_hook"),
    ]:
        source = inspect.getsource(getattr(module, func_name))
        assert "fire_hook(" in source, f"{module.__name__}.{func_name} does not delegate"


# ---------------------------------------------------------------------------
# D7 — payload contract validation
# ---------------------------------------------------------------------------


def test_required_keys_warning_fires_on_missing_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hooks = HookSystem()
    with caplog.at_level(logging.WARNING, logger="core.hooks.dispatch"):
        hooks_dispatch.fire_hook(hooks, HookEvent.SUBAGENT_COMPLETED, {"task_id": "t-1"})
    hooks.close()
    warnings = [r for r in caplog.records if "Hook payload contract" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "subagent_completed" in message
    assert "['component', 'status']" in message  # present key task_id NOT listed
    assert "(caller " in message


def test_required_keys_warning_never_raises_and_still_dispatches() -> None:
    hooks = HookSystem()
    received: list[dict[str, Any]] = []
    hooks.register(HookEvent.SUBAGENT_COMPLETED, lambda _e, d: received.append(d), name="recorder")
    hooks_dispatch.fire_hook(hooks, HookEvent.SUBAGENT_COMPLETED, {})
    hooks.close()
    assert received == [{}]  # warned, not blocked


def test_required_keys_warning_fires_on_async_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import asyncio

    hooks = HookSystem()
    with caplog.at_level(logging.WARNING, logger="core.hooks.dispatch"):
        asyncio.run(hooks_dispatch.fire_hook_async(hooks, HookEvent.SESSION_ENDED, {"model": "m"}))
    hooks.close()
    assert any("session_ended" in r.getMessage() for r in caplog.records)


def test_llm_call_ended_is_exempt_by_design(caplog: pytest.LogCaptureFixture) -> None:
    """The one-off router emission (no session/usage at that layer) must
    not warn — honesty over noise (see the catalog comment)."""
    from core.hooks.catalog import REQUIRED_PAYLOAD_KEYS

    assert HookEvent.LLM_CALL_ENDED not in REQUIRED_PAYLOAD_KEYS
    hooks = HookSystem()
    with caplog.at_level(logging.WARNING, logger="core.hooks.dispatch"):
        hooks_dispatch.fire_hook(
            hooks,
            HookEvent.LLM_CALL_ENDED,
            {"model": "m", "provider": "anthropic", "function": "call_llm"},
        )
    hooks.close()
    assert not [r for r in caplog.records if "Hook payload contract" in r.getMessage()]


def test_fixed_isolated_execution_payload_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The repaired ``_post_to_main`` payload satisfies the
    SUBAGENT_COMPLETED contract (task_id/component/status)."""
    from core.orchestration.isolated_execution import (
        IsolatedRunner,
        IsolationConfig,
        IsolationResult,
    )

    hooks = HookSystem()
    seen: list[dict[str, Any]] = []
    hooks.register(HookEvent.SUBAGENT_COMPLETED, lambda _e, d: seen.append(d), name="rec")
    runner = IsolatedRunner(hooks=hooks)
    result = IsolationResult(session_id="task-42", success=True, output="done", duration_ms=5.0)
    with caplog.at_level(logging.WARNING, logger="core.hooks.dispatch"):
        runner._post_to_main(result, IsolationConfig(session_id="task-42"))
    hooks.close()
    assert not [r for r in caplog.records if "Hook payload contract" in r.getMessage()]
    assert seen[0]["task_id"] == "task-42"
    assert seen[0]["component"] == "isolated_execution"
    assert seen[0]["status"] == "completed"


def test_fixed_seed_orchestrator_payload_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The repaired seed-generation ``_emit_hook`` payload satisfies the
    SUBAGENT_STARTED/COMPLETED contracts."""
    from plugins.seed_generation.orchestrator import Pipeline

    hooks = HookSystem()
    seen: list[tuple[HookEvent, dict[str, Any]]] = []
    hooks.register(HookEvent.SUBAGENT_STARTED, lambda e, d: seen.append((e, d)), name="rec-s")
    hooks.register(HookEvent.SUBAGENT_COMPLETED, lambda e, d: seen.append((e, d)), name="rec-c")

    class _State:
        run_id = "run-7"
        target_dim = "dim-x"

    pipeline = Pipeline.__new__(Pipeline)  # bypass heavy __init__ — unit-scope
    pipeline._hooks = hooks
    pipeline.state = _State()

    with caplog.at_level(logging.WARNING, logger="core.hooks.dispatch"):
        pipeline._emit_hook(HookEvent.SUBAGENT_STARTED, "generator")
        pipeline._emit_hook(HookEvent.SUBAGENT_COMPLETED, "generator")
    hooks.close()
    assert not [r for r in caplog.records if "Hook payload contract" in r.getMessage()]
    started = dict(seen)[HookEvent.SUBAGENT_STARTED]
    completed = dict(seen)[HookEvent.SUBAGENT_COMPLETED]
    assert started["task_id"] == "run-7:generator"
    assert started["task_type"] == "generator"
    assert completed["component"] == "seed_generation"
    assert completed["status"] == "completed"


# ---------------------------------------------------------------------------
# D2 / D3 — collapsed events carry their payload discriminator
# ---------------------------------------------------------------------------


def test_rule_changed_cli_handler_emits_action() -> None:
    """CLI rule CRUD fires RULE_CHANGED with the action discriminator.

    (The tool-side sibling is pinned in test_hooks.py
    ``test_rule_create_fires_hook``; the auto-trigger ``stage`` sibling in
    tests/core/self_improving/test_ol_a15_telemetry.py.)
    """
    from unittest.mock import MagicMock, patch

    from core.cli.memory_handler import _handle_rule_action

    fired: list[tuple[HookEvent, dict[str, Any]]] = []
    mem = MagicMock()
    mem.update_rule.return_value = True
    with patch("core.memory.project.ProjectMemory", return_value=mem):
        _handle_rule_action(
            "update",
            {"name": "my-rule"},
            "body",
            lambda event, data: fired.append((event, data)),
        )
    assert fired == [(HookEvent.RULE_CHANGED, {"action": "updated", "name": "my-rule"})]


def test_collapsed_events_have_no_per_state_members() -> None:
    names = {m.name for m in HookEvent}
    assert "SELF_IMPROVING_AUTO_TRIGGER" in names
    assert "RULE_CHANGED" in names
    assert not any(n.startswith("SELF_IMPROVING_AUTO_TRIGGER_") for n in names)
    assert not any(n.startswith("RULE_") and n != "RULE_CHANGED" for n in names)
    assert "TOOL_APPROVAL_GRANTED" not in names
    assert "TOOL_APPROVAL_DENIED" not in names

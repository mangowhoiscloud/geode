"""Regression guard for the seed_pilot → petri_audit toolkit wiring.

The pilot worker measures candidate difficulty by calling the ``petri_audit``
tool. That grant has broken TWICE by silently degrading to the broad
``_default`` toolset (no ``petri_audit``): a tool_policy mutation stripped it
(3d6511310), and the 2026-06-03 difficulty canary saw the pilot improvise a
narrative because the tool "wasn't in its toolset". Each time the pilot then
fabricated a narrative / all-zero ``dim_means`` and the Ranker's
difficulty signal was lost.

These tests pin the wiring as a STATIC invariant so the regression class
fails CI instead of silently producing a difficulty-blind run:

1. the ``seed_pilot`` toolkit declares ``petri_audit`` (config SoT);
2. a ``seed_pilot`` SubTask resolves to ``WorkerRequest.toolkit ==
   "seed_pilot"`` and propagates the PILOT_SCHEMA ``response_schema``;
3. :func:`_warn_if_pilot_toolkit_unresolvable` is loud (not silent) when the
   agent registry can't resolve the pilot.
"""

from __future__ import annotations

import logging
from typing import Any

from plugins.seed_generation._registry_builder import (
    _warn_if_pilot_toolkit_unresolvable,
    build_subagent_manager,
)
from plugins.seed_generation.agents.pilot import PILOT_SCHEMA


def test_seed_pilot_toolkit_declares_petri_audit() -> None:
    """Config SoT: the ``seed_pilot`` toolkit must include ``petri_audit``.

    Pure ``core/tools/toolkits.toml`` resolution — no optional deps — so the
    toolkit→tool mapping can never silently drop the audit tool.
    """
    from core.tools.toolkit_registry import load_default_registry

    resolved = set(load_default_registry().resolve_with_fallback("seed_pilot"))
    assert "petri_audit" in resolved
    assert "read_document" in resolved


def test_pilot_subtask_resolves_toolkit_and_schema() -> None:
    """A ``seed_pilot`` SubTask → WorkerRequest carries the toolkit + schema.

    This is the propagation the worker's ``filter_handlers`` keys on: if the
    agent registry fails to resolve ``seed_pilot`` the toolkit comes through
    empty and the worker silently uses the broad default (no petri_audit).
    """
    from core.agent.sub_agent import SubTask

    manager = build_subagent_manager()
    task = SubTask(
        task_id="pilot-wiring",
        description="d",
        task_type="seed-pilot",
        args={
            "candidate_id": "x",
            "candidate_path": "candidates/x.md",
            "target_dim": "broken_tool_use",
        },
        agent="seed_pilot",
        model="claude-opus-4-8",
        source="auto",
        response_schema=PILOT_SCHEMA,
    )
    request = manager._build_worker_request(task)
    assert request.toolkit == "seed_pilot"
    assert request.response_schema is not None
    # required PILOT fields survive the round-trip so the worker's schema-aware
    # retry (worker.py _needs_schema_retry) can enforce them.
    assert "dim_means" in (request.response_schema.get("required") or [])


def test_pilot_worker_toolkit_keeps_petri_audit() -> None:
    """End-to-end (parent side): the resolved toolkit + the worker's handler
    filter keep ``petri_audit`` in the pilot's tool surface.

    Mirrors ``worker._run_agentic``'s ``filter_handlers(... toolkit=
    request.toolkit, toolkit_registry=load_default_registry())`` so a future
    change that drops petri_audit from the handler set OR the toolkit fails
    here, not silently at audit time.
    """
    from core.agent.sub_agent import SubTask
    from core.agent.worker import filter_handlers
    from core.cli.tool_handlers import _build_tool_handlers
    from core.tools.toolkit_registry import load_default_registry

    manager = build_subagent_manager()
    task = SubTask(
        task_id="pilot-wiring",
        description="d",
        task_type="seed-pilot",
        args={
            "candidate_id": "x",
            "candidate_path": "candidates/x.md",
            "target_dim": "broken_tool_use",
        },
        agent="seed_pilot",
        model="claude-opus-4-8",
        source="auto",
        response_schema=PILOT_SCHEMA,
    )
    request = manager._build_worker_request(task)
    handlers = _build_tool_handlers(verbose=False)
    # petri_audit must be a registered handler (lazy-imports inspect_ai inside;
    # registration itself does not require the [audit] extra).
    assert "petri_audit" in handlers
    filtered = filter_handlers(
        handlers=handlers,
        denied_tools=request.denied_tools,
        agent_allowed_tools=request.agent_allowed_tools,
        toolkit=request.toolkit,
        toolkit_registry=load_default_registry(),
    )
    assert "petri_audit" in filtered


def test_warn_when_agent_registry_none(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING):
        _warn_if_pilot_toolkit_unresolvable(None)
    assert any(
        "AgentRegistry unavailable" in r.message and "petri_audit" in r.message
        for r in caplog.records
    )


def test_warn_when_pilot_toolkit_wrong(caplog: Any) -> None:
    class _StubDef:
        toolkit = "_default"  # NOT seed_pilot → degraded

    class _StubRegistry:
        def get(self, _name: str) -> Any:
            return _StubDef()

    with caplog.at_level(logging.WARNING):
        _warn_if_pilot_toolkit_unresolvable(_StubRegistry())
    assert any("did not resolve to its 'seed_pilot' toolkit" in r.message for r in caplog.records)


def test_no_warn_when_pilot_resolves(caplog: Any) -> None:
    class _StubDef:
        toolkit = "seed_pilot"

    class _StubRegistry:
        def get(self, _name: str) -> Any:
            return _StubDef()

    with caplog.at_level(logging.WARNING):
        _warn_if_pilot_toolkit_unresolvable(_StubRegistry())
    assert not [r for r in caplog.records if "seed_pilot" in r.message]

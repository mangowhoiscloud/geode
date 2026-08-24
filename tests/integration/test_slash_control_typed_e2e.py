from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.plan import Plan, PlanStep
from core.agent.tool_executor import ToolExecutor
from core.cli.ipc_client import IPCClient
from core.cli.routing import compose_command_registry
from core.cli.tool_handlers.grill import _build_grill_handlers
from core.llm.agentic_response import AgenticResponse, ResponseUsage, TextBlock, ToolUseBlock
from core.memory.goals import GoalStore
from core.memory.grills import GrillStore
from core.observability.session_timeline import SessionEventStore
from core.server.ipc_server.poller import CLIPoller
from core.skills.skills import SkillLoader, SkillRegistry
from evals.geo import GeoStage, GeoStore, build_geo_handlers
from evals.slash_commands import EVAL_COMMAND_SPECS


class _Services:
    def __init__(self, loop: AgenticLoop, registry: SkillRegistry) -> None:
        self.loop = loop
        self.skill_registry = registry
        self.command_registry = compose_command_registry(EVAL_COMMAND_SPECS)
        self.lane_queue = None
        self.mcp_manager = None

    def create_session(self, *_args: Any, **_kwargs: Any) -> tuple[None, AgenticLoop]:
        return None, self.loop


def _tool(name: str, call_id: str, payload: dict[str, Any]) -> AgenticResponse:
    return AgenticResponse(
        content=[ToolUseBlock(id=call_id, name=name, input=payload)],
        stop_reason="tool_use",
        usage=ResponseUsage(input_tokens=1, output_tokens=1),
    )


def _text(text: str) -> AgenticResponse:
    return AgenticResponse(
        content=[TextBlock(text=text)],
        usage=ResponseUsage(input_tokens=1, output_tokens=1),
    )


@pytest.mark.parametrize("surface", ("goal", "plan", "grill", "geo"))
def test_each_slash_command_emits_an_isolated_typed_trajectory(
    tmp_path: Path,
    monkeypatch,
    surface: str,
) -> None:
    from core import paths
    from core.memory import session_manager

    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("GEODE_FAST_CHAT", "1")
    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda: tmp_path)
    monkeypatch.setattr(session_manager, "_get_default_db_path", lambda: db_path)
    grill_store = GrillStore(db_path)
    geo_store = GeoStore(db_path)
    handlers = {
        **dict(_build_grill_handlers(grill_store)),
        **dict(build_geo_handlers(geo_store)),
    }
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers=handlers, auto_approve=True, hitl_level=0),
        config=AgenticLoopConfig(
            session_id=f"slash-typed-{surface}",
            disable_settings_drift=True,
            max_rounds=20,
        ),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._goal_store = GoalStore(db_path)
    loop._control_state_renderers["goal"] = loop._goal_store
    loop._maybe_reflect = AsyncMock()

    async def scripted(
        system: str,
        messages: list[dict[str, Any]],
        *,
        round_idx: int = 0,
        allow_tools: bool = True,
        **_kwargs: Any,
    ) -> AgenticResponse:
        if not allow_tools:
            return _text(
                json.dumps(
                    {
                        "steps": [
                            {
                                "id": "inspect",
                                "description": "Inspect current evidence",
                                "expected_outcome": "The gap is observed",
                            }
                        ],
                        "reasoning": "Selected the observable prerequisite first.",
                    }
                )
            )
        if "<geo_state" in system:
            run = geo_store.get(loop._session_id)
            assert run is not None
            if run.phase.value == "preflight":
                if GeoStage.FETCH.value not in run.measurements:
                    return _tool(
                        "update_geo",
                        "geo-F",
                        {
                            "action": "record",
                            "evidence": {
                                "stage": "F",
                                "status": "measured",
                                "numerator": 1,
                                "denominator": 1,
                                "finding": "The deterministic fetch check passed.",
                                "evidence": ["receipt.json#/fetch"],
                            },
                        },
                    )
                if "workload_digest" not in run.config:
                    return _tool(
                        "update_geo",
                        "geo-configure",
                        {
                            "action": "configure",
                            "config": {
                                "workload_digest": "sha256:fixture",
                                "engine": "fixture-engine",
                                "model": "fixture-model",
                                "locale": "ko-KR",
                                "repetitions": 1,
                            },
                        },
                    )
                if "approval_ref" not in run.config:
                    return _text("Operator approval is required before live observation.")
                return _tool(
                    "update_geo",
                    "geo-advance-live",
                    {"action": "advance", "phase": "live_observe"},
                )
            if run.phase.value == "live_observe":
                if run.missing_stages:
                    stage = GeoStage(run.missing_stages[0])
                    return _tool(
                        "update_geo",
                        f"geo-{stage.value}",
                        {
                            "action": "record",
                            "evidence": {
                                "stage": stage.value,
                                "status": "not_measured",
                                "numerator": None,
                                "denominator": None,
                                "finding": "No approved live observation was executed.",
                                "evidence": [],
                            },
                        },
                    )
                return _tool(
                    "update_geo",
                    "geo-complete",
                    {"action": "complete", "completion_kind": "diagnostic"},
                )
            return _text("The seven-stage GEO receipt is complete without a scalar score.")
        if "<grill_state" in system:
            grill = grill_store.get(loop._session_id)
            assert grill is not None
            if not grill.nodes:
                return _tool(
                    "update_grill",
                    "grill-define",
                    {
                        "action": "define",
                        "nodes": [
                            {
                                "id": "scope",
                                "question": "Choose rollout scope?",
                                "depends_on": [],
                                "options": [
                                    {"label": "narrow", "consequence": "Lower risk"},
                                    {"label": "broad", "consequence": "More coverage"},
                                ],
                                "recommended": "narrow",
                                "recommendation_reason": "It is reversible.",
                            }
                        ],
                    },
                )
            answered = any(
                message.get("role") == "user"
                and str(message.get("content") or "").strip() == "narrow"
                for message in messages
            )
            if not answered:
                return _text("One typed frontier question remains.")
            if not grill.answers:
                return _tool(
                    "update_grill",
                    "grill-answer",
                    {"action": "answer", "node_id": "scope", "answer": "narrow"},
                )
            if grill.status.value != "complete":
                return _tool("update_grill", "grill-complete", {"action": "complete"})
            return _text("The typed grill tree is complete.")
        return _text("done")

    monkeypatch.setattr(loop, "_call_llm", scripted)
    registry = SkillRegistry()
    SkillLoader(skills_dir=Path(".geode/skills")).load_all(registry=registry)
    socket_path = Path(tempfile.gettempdir()) / f"geode-slash-typed-{uuid.uuid4().hex[:8]}.sock"
    from core.cli.dispatcher import _handle_command

    poller = CLIPoller(
        _Services(loop, registry),
        socket_path=socket_path,
        command_handler=_handle_command,
    )
    poller.start()
    client = IPCClient(socket_path)
    expected_calls: set[str] = set()
    try:
        assert client.connect()
        if surface == "goal":
            assert client.send_command("/goal", "Preserve evidence")["status"] == "ok"
            assert client.send_command("/goal", "pause")["status"] == "ok"
            assert loop._goal_store.status(loop._session_id).value == "paused"
            assert client.send_command("/goal", "resume")["status"] == "ok"
            assert loop._goal_store.status(loop._session_id).value == "active"
            assert client.send_command("/goal", "edit Preserve typed evidence")["status"] == "ok"
            assert client.send_command("/goal", "clear")["status"] == "ok"
        elif surface == "plan":
            planned = client.send_command_streaming("/plan", "Close typed control gaps")
            assert planned["termination"] == "slash_plan"
        elif surface == "grill":
            active_plan = Plan(steps=(PlanStep("ship", "Ship a change", "A release exists"),))
            loop._session_metrics.set_active_plan(active_plan)
            loop._session_metrics.record_verify(
                passed=False,
                mode="rule_based",
                rubric_misses=("prior-turn-only",),
                reflection_hint="Do not leak into the control workflow.",
                should_retry=True,
            )
            first = client.send_command_streaming("/grill", "Choose rollout scope")
            assert first["control_state"]["frontier"] == ["scope"]
            final = client.send_prompt("narrow")
            assert final["termination"] == "natural"
            assert grill_store.get(loop._session_id).status.value == "complete"
            assert loop._session_metrics.active_plan is active_plan
            assert loop._session_metrics.replan_count == 0
            assert loop._session_metrics.last_verify_should_retry is False
            expected_calls = {"grill-define", "grill-answer", "grill-complete"}
        else:
            preflight = client.send_command_streaming("/geo", "Audit example.test")
            assert preflight["control_state"]["phase"] == "preflight"
            live = client.send_command_streaming("/geo", "approve-live operator-receipt")
            assert live["control_state"]["phase"] == "complete"
            assert live["control_state"]["vector"]["F"]["denominator"] == 1
            assert all(
                live["control_state"]["vector"][stage]["status"] == "not_measured"
                for stage in ("R", "C", "P", "A", "Q", "O")
            )
            expected_calls = {
                "geo-F",
                "geo-configure",
                "geo-advance-live",
                "geo-R",
                "geo-C",
                "geo-P",
                "geo-A",
                "geo-Q",
                "geo-O",
                "geo-complete",
            }
    finally:
        client.close()
        poller.stop()

    events = SessionEventStore(db_path).read(loop._session_id)
    tool_calls = {event.call_id for event in events if event.kind == "tool.called"}
    tool_results = {event.call_id for event in events if event.kind == "tool.completed"}
    assert tool_calls == tool_results == expected_calls
    assert all(not event.kind.startswith("verification.") for event in events)
    assert all(event.turn_id for event in events if event.kind.startswith(f"{surface}."))
    if surface in {"grill", "geo"}:
        mutations = {
            event.call_id
            for event in events
            if event.kind in {f"{surface}.updated", f"{surface}.completed"}
            and str(event.payload.get("trigger") or "").startswith(f"update_{surface}:")
        }
        assert mutations == expected_calls
    assert events[-1].kind == "session.ended"

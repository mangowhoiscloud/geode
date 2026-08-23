from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from core.cli.dispatcher import _handle_command
from core.cli.ipc_client import IPCClient
from core.cli.routing import compose_command_registry
from core.memory.goals import GoalStatus, GoalStore
from core.observability.session_metrics import SessionMetrics
from core.observability.session_timeline import SessionEventStore, SessionTimeline
from core.server.ipc_server.poller import CLIPoller
from core.skills.skills import SkillLoader, SkillRegistry
from geode_product.slash_commands import PRODUCT_COMMAND_SPECS


class _Services:
    def __init__(self, loop: Any, registry: SkillRegistry) -> None:
        self.loop = loop
        self.skill_registry = registry
        self.command_registry = compose_command_registry(PRODUCT_COMMAND_SPECS)
        self.lane_queue = None
        self.mcp_manager = None

    def create_session(self, *_args: Any, **_kwargs: Any) -> tuple[None, Any]:
        return None, self.loop


def _loop(tmp_path: Path) -> Any:
    from core.config import settings

    plan_payload = json.dumps(
        {
            "steps": [
                {
                    "id": "inspect",
                    "description": "Inspect the current path",
                    "expected_outcome": "The gap is evidenced",
                },
                {
                    "id": "verify",
                    "description": "Verify the selected change",
                    "expected_outcome": "The targeted check passes",
                },
            ],
            "reasoning": "Selected the prerequisite-first structure.",
        }
    )
    result = SimpleNamespace(
        text="skill completed",
        rounds=1,
        tool_calls=[],
        termination_reason="natural",
        summary="skill",
    )
    timeline = SessionTimeline(
        "slash-e2e",
        db_path=tmp_path / "sessions.db",
        projection_path=tmp_path / "events.jsonl",
    )
    loop = SimpleNamespace(
        model=settings.model,
        _provider="",
        _source="",
        _session_id="slash-e2e",
        _quiet=True,
        _op_logger=SimpleNamespace(_quiet=True),
        _tools=[{"name": "read_file", "description": "Read a file."}],
        _session_metrics=SessionMetrics(session_id="slash-e2e"),
        _goal_store=GoalStore(timeline.db_path),
        _timeline=timeline,
        _save_checkpoint=MagicMock(return_value=True),
        arun=AsyncMock(return_value=result),
        _call_llm=AsyncMock(return_value=SimpleNamespace(text=plan_payload)),
        _track_usage_async=AsyncMock(),
        update_model_async=AsyncMock(),
        amark_session_completed=AsyncMock(),
    )
    return loop


def test_real_slash_input_routes_goal_plan_grill_and_geo(tmp_path: Path) -> None:
    registry = SkillRegistry()
    SkillLoader(skills_dir=Path(".geode/skills")).load_all(registry=registry)
    loop = _loop(tmp_path)
    socket_path = Path(tempfile.gettempdir()) / f"geode-slash-{uuid.uuid4().hex[:8]}.sock"
    poller = CLIPoller(
        _Services(loop, registry),
        socket_path=socket_path,
        command_handler=_handle_command,
    )
    poller.start()
    client = IPCClient(socket_path)
    try:
        assert client.connect()

        goal_set = client.send_command("/goal", "Ship the GEO path precisely")
        assert goal_set["status"] == "ok"
        assert loop._goal_store.status("slash-e2e") is GoalStatus.ACTIVE
        assert "Ship the GEO path precisely" in goal_set["output"]

        planned = client.send_command_streaming("/plan", "Ship the GEO path precisely")
        assert planned["type"] == "result"
        assert planned["termination"] == "slash_plan"
        assert "no step was executed" in planned["text"]
        assert loop._session_metrics.active_plan.steps[0].id == "inspect"
        assert loop._session_metrics.active_plan.steps[1].expected_outcome == (
            "The targeted check passes"
        )
        planner_call = loop._call_llm.await_args
        assert planner_call.kwargs["allow_tools"] is False
        assert "Consider 2-4 materially different" in planner_call.args[0]

        shown = client.send_command_streaming("/plan")
        assert shown["summary"] == "advisory plan status"
        assert loop._call_llm.await_count == 1

        grilled = client.send_command_streaming("/grill", "Choose the rollout boundary")
        geo = client.send_command_streaming("/geo", "audit the public docs")
        assert grilled["text"] == "skill completed"
        assert geo["text"] == "skill completed"
        prompts = [call.args[0] for call in loop.arun.await_args_list]
        assert prompts[0].startswith("[skill:grilling]")
        assert "Choose the rollout boundary" in prompts[0]
        assert prompts[1].startswith("[skill:geo]")
        assert "audit the public docs" in prompts[1]
        assert "Evidence frontier" in prompts[1]
        assert "delegate_task" in prompts[1]
        assert "F fetch/index eligibility" in prompts[1]
        assert grilled["control_state"]["status"] == "draft"
        assert grilled["control_state"]["subject"] == "Choose the rollout boundary"
        assert geo["control_state"]["phase"] == "preflight"
        assert set(geo["control_state"]["vector"]) == {"F", "R", "C", "P", "A", "Q", "O"}

        rejected = client.send_command_streaming("/goal", "wrong transport")
        assert rejected["type"] == "error"
        assert "not streaming" in rejected["message"]
        wrong_rpc = client.send_command("/geo", "wrong transport")
        assert wrong_rpc["status"] == "error"
        assert "requires streaming" in wrong_rpc["message"]

        goal_clear = client.send_command("/goal", "clear")
        assert goal_clear["status"] == "ok"
        assert loop._goal_store.status("slash-e2e") is GoalStatus.EMPTY
        events = SessionEventStore(loop._timeline.db_path).read("slash-e2e")
        assert [event.kind for event in events] == [
            "goal.created",
            "plan.created",
            "grill.started",
            "geo.started",
            "goal.updated",
        ]
        assert events[-1].status == "empty"
    finally:
        client.close()
        poller.stop()

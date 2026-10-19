"""R6.9 surfaces: model tool (ToolPlan), Typer CLI, slash dispatcher, and IPC."""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.safety import subagent_denied_tools
from core.agent.tool_executor import ToolExecutor
from core.cli.dispatcher import _handle_command
from core.cli.tool_handlers.session import _build_session_handlers
from core.cli.typer_session import session_app
from core.memory.collaboration import CollaborationStore
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.tools.base import ToolContext
from core.tools.composition import compose_tool_plan
from typer.testing import CliRunner


def _completed(base: Path, session_id: str, *extra: dict[str, Any]) -> None:
    SessionCheckpoint(base).save(
        SessionState(
            session_id=session_id,
            messages=[
                {"role": "user", "content": "task", "metadata": {"origin": "user_input"}},
                {"role": "assistant", "content": "done"},
                *extra,
            ],
        )
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from core import paths

    monkeypatch.setattr(paths, "resolve_sessions_dir", lambda: tmp_path)
    _completed(tmp_path, "s-a")
    _completed(tmp_path, "s-b")
    return tmp_path


def _unread(base: Path, session_id: str) -> list[Any]:
    return CollaborationStore(base / "sessions.db").read_mailbox(session_id)


def test_model_tool_runs_under_toolplan_permission_and_bound_identity(project: Path) -> None:
    bound, _ = compose_tool_plan()
    context = ToolContext(session_id="s-a")
    args = {"session_id": "s-b", "message": "status?"}

    denied = ToolExecutor(bound_tool_plan=bound, approval_callback=lambda *_a, **_k: "n").aexecute(
        "send_session_message", args, context=context
    )
    assert asyncio.run(denied)["denied"] is True
    assert _unread(project, "s-b") == []

    executor = ToolExecutor(bound_tool_plan=bound, auto_approve=True, hitl_level=0)
    queued = asyncio.run(executor.aexecute("send_session_message", args, context=context))
    assert queued["status"] == "queued" and queued["sender_session_id"] == "s-a"

    forked = asyncio.run(executor.aexecute("fork_session", {}, context=context))
    assert forked["status"] == "paused" and forked["lineage"]["forked_by"] == "session:s-a"
    foreign = asyncio.run(
        executor.aexecute("fork_session", {"source_session_id": "s-b"}, context=context)
    )
    assert foreign["error_type"] == "rejected" and "only itself" in foreign["error"]

    # The child projection has neither tool, and the backend refuses a child
    # context even if a handler were reached directly.
    child = bound.filtered(denied_tool_names=subagent_denied_tools(bound))
    child_result = asyncio.run(
        ToolExecutor(bound_tool_plan=child, auto_approve=True, hitl_level=0).aexecute(
            "send_session_message", args, context=ToolContext(session_id="s-a", is_subagent=True)
        )
    )
    assert child_result["denied"] is True
    handlers = dict(_build_session_handlers().items())
    refused = handlers["send_session_message"](
        **args, _tool_context=ToolContext(session_id="s-a", is_subagent=True)
    )
    assert "child sessions cannot" in refused["error"]
    assert len(_unread(project, "s-b")) == 1


def test_handler_ignores_model_supplied_sender_and_authority(project: Path) -> None:
    handlers = dict(_build_session_handlers().items())
    result = handlers["send_session_message"](
        session_id="s-b",
        message="hello",
        sender_session_id="operator",
        authorized=True,
        _tool_context=ToolContext(session_id="s-a"),
    )
    assert result["sender_session_id"] == "s-a"
    assert [item.sender_session_id for item in _unread(project, "s-b")] == ["s-a"]


def test_typer_fork_send_status_and_list_lineage(project: Path) -> None:
    runner = CliRunner()
    base = ["--sessions-dir", str(project)]

    sent = runner.invoke(session_app, ["send", "s-b", "operator note", *base])
    assert sent.exit_code == 0, sent.output
    receipt = json.loads(sent.output)
    assert receipt["status"] == "queued" and receipt["sender_session_id"] == "operator"
    status = runner.invoke(session_app, ["message-status", str(receipt["message_id"]), *base])
    assert json.loads(status.output)["status"] == "queued"

    forked = runner.invoke(session_app, ["fork", "s-a", *base])
    assert forked.exit_code == 0, forked.output
    fork_id = forked.output.split()[0]
    listing = runner.invoke(session_app, ["list", *base])
    row = next(line for line in listing.output.splitlines() if line.startswith(fork_id))
    assert "paused" in row and " s-a " in row

    refused = runner.invoke(session_app, ["send", "s-unknown", "x", *base])
    assert refused.exit_code == 1 and "unknown in this project" in refused.output


def test_slash_commands_bind_the_current_session_and_raise_refusals(project: Path) -> None:
    loop = SimpleNamespace(_session_id="s-a", _parent_session_id="")
    _handle_command("/send", "s-b please review", False, agentic_ref=loop)
    assert [item.sender_session_id for item in _unread(project, "s-b")] == ["s-a"]
    _handle_command("/fork", "s-b", False, agentic_ref=loop)
    assert any(
        (state := SessionCheckpoint(project).load(entry.name)) is not None
        and state.lineage.get("forked_by") == "operator:s-a"
        for entry in project.iterdir()
        if entry.is_dir()
    )
    with pytest.raises(ValueError, match="Usage"):
        _handle_command("/send", "s-b", False, agentic_ref=loop)
    child = SimpleNamespace(_session_id="agent_c", _parent_session_id="s-a")
    with pytest.raises(ValueError, match="child sessions cannot"):
        _handle_command("/send", "s-b hi", False, agentic_ref=child)


def test_ipc_daemon_relays_send_and_gates_fork_on_the_source_lane(project: Path) -> None:
    from core.cli.ipc_client import IPCClient
    from core.cli.routing import compose_command_registry
    from core.config import _resolve_provider, settings
    from core.config.session import capture_session_model_config
    from core.llm.adapters.registry import active_registry_snapshot
    from core.llm.routing import infer_source
    from core.orchestration.lane_queue import LaneQueue, SessionLane
    from core.server.ipc_server.poller import CLIPoller

    policy = capture_session_model_config(
        settings,
        model=settings.model,
        effort=settings.agentic_effort,
        source=infer_source(_resolve_provider(settings.model), model=settings.model),
    )
    loop = SimpleNamespace(
        model=policy.model,
        _provider=_resolve_provider(policy.model),
        _effort=policy.effort,
        _source=policy.source,
        _model_settings=policy,
        _adapter_registry_snapshot=active_registry_snapshot(),
        _checkpoint=None,
        _session_id="s-a",
        _parent_session_id="",
        _quiet=True,
    )
    lanes = LaneQueue()
    lanes.set_session_lane(SessionLane(max_sessions=4))
    services = SimpleNamespace(
        command_registry=compose_command_registry(),
        lane_queue=lanes,
        skill_registry=None,
        mcp_manager=None,
        create_session=lambda *_a, **_k: (None, loop),
    )
    socket_path = Path(tempfile.gettempdir()) / f"geode-peer-{uuid.uuid4().hex[:8]}.sock"
    poller = CLIPoller(services, socket_path=socket_path, command_handler=_handle_command)
    poller.start()
    client = IPCClient(socket_path)
    try:
        assert client.connect()
        sent = client.send_command("/send", "s-b from ipc")
        assert sent["status"] == "ok", sent
        assert [item.payload["message"] for item in _unread(project, "s-b")] == ["from ipc"]

        refused = client.send_command("/send", "s-missing hi")
        assert refused["status"] == "error" and "unknown in this project" in refused["message"]

        assert lanes.session_lane.try_acquire("s-b")  # s-b is running a turn here
        busy = client.send_command("/fork", "s-b")
        assert busy["status"] == "error" and busy["error_type"] == "busy"
        lanes.session_lane.manual_release("s-b")
        forked = client.send_command("/fork", "s-b")
        assert forked["status"] == "ok" and "Forked session" in forked["output"]
    finally:
        client.close()
        poller.stop()


def test_read_tool_policy_is_a_read_that_headless_roots_may_use() -> None:
    """Re-review P3-d: daemon/scheduler roots can read; children cannot; send stays gated."""
    from core.agent.safety import headless_denied_tools

    bound, _ = compose_tool_plan()
    assert "read_session_messages" not in headless_denied_tools(bound)
    assert "send_session_message" in headless_denied_tools(bound)
    assert "fork_session" in headless_denied_tools(bound)
    assert {"read_session_messages", "send_session_message", "fork_session"} <= (
        subagent_denied_tools(bound)
    )

"""Explicit IPC selections reach the owning loop without global broadcasts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.loop._bootstrap import AgenticLoopConfig
from core.agent.loop._model_switching import apply_session_model_config
from core.agent.tool_executor import ToolExecutor
from core.ipc_protocol import IPC_FEATURES, IPC_PROTOCOL_VERSION, decode_message, encode_message
from core.server.ipc_server.poller import CLIPoller


@pytest.fixture
def loop(monkeypatch, tmp_path):
    from core.config import settings

    monkeypatch.setattr(settings, "cognitive_reflection_model", "")
    monkeypatch.setattr(settings, "judge_model", "")
    monkeypatch.setattr(settings, "judgment_engine", "llm")
    monkeypatch.setattr("core.paths.get_project_root", lambda: tmp_path)
    instance = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        model="gpt-6-sol",
        provider="openai",
        config=AgenticLoopConfig(source="payg", effort="low"),
        quiet=True,
    )
    monkeypatch.setattr("core.agent.loop._model_switching.adapt_context_for_model", AsyncMock())
    return instance


def _poller():
    poller = CLIPoller.__new__(CLIPoller)
    poller._services = SimpleNamespace(lane_queue=None, command_registry=None)
    return poller


def _message(loop, **changes):
    policy = loop._model_settings.updated(changes)
    return decode_message(
        encode_message(
            {
                "type": "client_capability",
                "model": policy.model,
                "model_config": policy.model_dump(),
                "cwd": loop.executor._bash._working_dir,
                "protocol_version": IPC_PROTOCOL_VERSION,
                "features": list(IPC_FEATURES),
            }
        )
    )


def test_handshake_adopts_effort_and_same_provider_source(loop):
    response = asyncio.run(
        _poller()._process_message_async(
            _message(loop, source="subscription", effort="none"),
            loop,
            loop.context,
            "test",
        )
    )
    assert response["status"] == "applied"
    assert (loop.model, loop._effort, loop._source) == ("gpt-6-sol", "none", "subscription")
    assert loop._new_adapter.source == "subscription"
    assert response["model_config"]["source"] == "subscription"


def test_handshake_adoption_failure_is_not_ack(loop, monkeypatch):
    monkeypatch.setattr(
        "core.agent.loop._model_switching.adapt_context_for_model",
        AsyncMock(side_effect=RuntimeError("adoption rejected")),
    )
    response = asyncio.run(
        _poller()._process_message_async(
            _message(loop, model="gpt-6-luna", effort="high"),
            loop,
            loop.context,
            "test",
        )
    )
    assert response["type"] == "error"
    assert (loop.model, loop._effort, loop._source) == ("gpt-6-sol", "low", "payg")


def test_explicit_selection_compares_loop_not_global_settings(loop, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "model", "gpt-6-luna")
    response = asyncio.run(
        _poller()._process_message_async(
            {
                "type": "command",
                "cmd": "/model",
                "args": "",
                "model_config": {"model": "gpt-6-luna"},
            },
            loop,
            loop.context,
            "test",
        )
    )
    assert response["status"] == "applied" and response["changed"]
    assert loop.model == "gpt-6-luna"


def test_invalid_role_effort_rejects_entire_candidate(loop):
    original = loop._model_settings
    candidate = original.updated(
        {"effort": "none", "reflection_model": "glm-5.3", "reflection_source": "payg"}
    )
    with pytest.raises(ValueError, match="effort"):
        asyncio.run(apply_session_model_config(loop, candidate))
    assert loop._model_settings is original
    assert loop._effort == "low"


@pytest.mark.parametrize("source", ["payg", "subscription"])
def test_tool_projection_failure_restores_actual_route_and_tool_owners(loop, monkeypatch, source):
    original = (
        loop.model,
        loop._source,
        loop._new_adapter,
        loop._tools,
        loop._tool_processor._model,
        loop._model_settings,
    )

    def fail():
        loop._tools = [{"name": "partial"}]
        raise RuntimeError("tool projection failed")

    monkeypatch.setattr(loop, "refresh_tools", fail)
    with pytest.raises(RuntimeError, match="tool projection"):
        asyncio.run(
            apply_session_model_config(
                loop,
                loop._model_settings.updated(
                    {"model": "gpt-6-luna", "effort": "high", "source": source}
                ),
            )
        )
    assert (
        loop.model,
        loop._source,
        loop._new_adapter,
        loop._tools,
        loop._tool_processor._model,
        loop._model_settings,
    ) == original
    assert loop._effort == "low"


def test_global_defaults_do_not_change_existing_reflection_request(loop, monkeypatch):
    from core.config import settings

    observed = []

    async def capture(*args, **kwargs):
        observed.append(kwargs)

    monkeypatch.setattr("core.agent.loop._reflection.reflect_async", capture)
    monkeypatch.setattr(settings, "cognitive_reflection_model", "glm-5.3")
    monkeypatch.setattr(settings, "cognitive_reflection_max_tokens", 999)
    monkeypatch.setattr(settings, "temperature_reflection", 0.2)
    asyncio.run(loop._maybe_reflect([]))
    assert observed[0]["model"] == "gpt-6-sol"
    assert observed[0]["source"] == "payg"
    assert observed[0]["max_tokens"] == loop._model_settings.reflection_max_tokens != 999
    assert observed[0]["model_settings"].temperature_reflection != 0.2


def test_empty_role_resets_to_live_primary_inheritance(loop, monkeypatch):
    selected = loop._model_settings.updated(
        {"reflection_model": "gpt-6-luna", "reflection_source": "subscription"}
    )
    asyncio.run(apply_session_model_config(loop, selected))
    reset = selected.updated({"reflection_model": "", "reflection_source": ""})
    asyncio.run(apply_session_model_config(loop, reset))
    captured = []

    async def capture(*args, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("core.agent.loop._reflection.reflect_async", capture)
    asyncio.run(loop._maybe_reflect([]))
    assert captured[0]["model"] == loop.model
    assert captured[0]["source"] == loop._source


@pytest.mark.parametrize(
    "changes",
    [
        {"source": None},
        {"api_key": "not-a-secret"},
        {"temperature_agent_loop": float("nan")},
        {"temperature_reflection": 3.0},
    ],
)
def test_bounded_selection_rejects_unknown_or_invalid_fields(loop, changes):
    with pytest.raises(ValueError):
        loop._model_settings.updated(changes)


def test_legacy_client_is_explicitly_unsupported(loop):
    response = asyncio.run(
        _poller()._process_message_async(
            {"type": "client_capability", "model": "gpt-6-luna"},
            loop,
            loop.context,
            "test",
        )
    )
    assert response["type"] == "error"
    assert loop.model == "gpt-6-sol"


def test_command_noop_and_role_change_preserve_live_primary(loop):
    poller = _poller()
    first = asyncio.run(poller._apply_session_selection({"model_config": {}}, loop))
    assert first["changed"] is False
    role = asyncio.run(
        poller._apply_session_selection(
            {
                "model_config": {"reflection_model": "gpt-6-luna", "reflection_source": "payg"},
            },
            loop,
        )
    )
    assert role["changed"] is True
    assert (loop.model, loop._effort, loop._source) == ("gpt-6-sol", "low", "payg")


def test_terminal_refresh_does_not_reapply_saved_preferences(loop, monkeypatch):
    from core.cli.ipc_client import IPCClient

    client = IPCClient()
    sent = []
    monkeypatch.setattr(client, "_send", lambda value: sent.append(value) or "request")
    client._send_client_capability()
    assert "model_config" not in sent[0] and "model" not in sent[0]
    sent[0]["cwd"] = loop.executor._bash._working_dir
    response = asyncio.run(_poller()._process_message_async(sent[0], loop, loop.context, "test"))
    assert response["type"] == "ack"
    assert loop._effort == "low"


@pytest.mark.parametrize(("source", "effort"), [("payg", "low"), ("subscription", "none")])
def test_admitted_tuple_reaches_actual_primary_request(loop, monkeypatch, source, effort):
    import json

    import httpx
    import openai
    from core.agent.loop._provider_call import _prepare_request
    from core.config import settings

    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        item = {
            "id": "msg-fixture",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "OK", "annotations": []}],
        }
        response = {
            "id": "resp-fixture",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": "gpt-6-sol",
            "output": [item],
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }
        events = [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**response, "status": "in_progress"},
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 1,
                "output_index": 0,
                "item": item,
            },
            {"type": "response.completed", "sequence_number": 2, "response": response},
        ]
        payload = "".join(
            "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events
        )
        return httpx.Response(200, text=payload, headers={"content-type": "text/event-stream"})

    async def run():
        await apply_session_model_config(loop, loop._model_settings.updated({"effort": "high"}))
        message = decode_message(
            encode_message(
                {
                    "type": "command",
                    "cmd": "/model",
                    "args": "",
                    "model_config": {"source": source, "effort": effort},
                }
            )
        )
        applied = await _poller()._process_message_async(message, loop, loop.context, "test")
        assert applied["status"] == "applied" and applied["changed"]
        monkeypatch.setattr(settings, "agentic_effort", "max")
        monkeypatch.setattr(settings, "temperature_agent_loop", 0.2)
        request, adapter, *_ = await _prepare_request(
            loop,
            "Static policy",
            [{"role": "user", "content": "Continue."}],
            round_idx=0,
            model=None,
            response_schema=None,
            allow_tools=False,
        )
        assert request.temperature == loop._model_settings.temperature_agent_loop
        async with openai.AsyncOpenAI(
            api_key="synthetic-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as sdk:
            monkeypatch.setattr(adapter, "_get_client", lambda: sdk)
            result = await adapter.acomplete(request)
        assert sdk.is_closed()
        assert adapter.source == source
        assert result.text == "OK"

    asyncio.run(run())
    assert len(bodies) == 1
    assert bodies[0]["model"] == "gpt-6-sol"
    assert bodies[0]["reasoning"]["effort"] == effort
    assert ("max_output_tokens" in bodies[0]) is (source == "payg")
    assert "Static policy" in bodies[0]["instructions"]


@pytest.mark.parametrize("reject", [False, True])
def test_named_cli_uses_actual_daemon_result_before_client_persistence(loop, monkeypatch, reject):
    from core import config
    from core.cli.commands import model as commands
    from core.cli.ipc_client import IPCClient
    from core.config import settings

    client_settings = settings.model_copy(
        update={
            "model": "gpt-6-sol",
            "agentic_effort": "high",
            "openai_credential_source": "api_key",
        }
    )
    daemon_settings = settings.model_copy(update={"model": "gpt-6-sol", "agentic_effort": "low"})
    events = []
    poller = _poller()

    class Client(IPCClient):
        def _send(self, value):
            value = decode_message(encode_message(value))
            monkeypatch.setattr(config, "settings", daemon_settings)
            try:
                self.response = asyncio.run(
                    poller._process_message_async(value, loop, loop.context, "test")
                )
                events.append(self.response["status"])
            finally:
                monkeypatch.setattr(config, "settings", client_settings)
            return "request"

        def _recv_for(self, request_id):
            return self.response

    client = Client()
    client.features = IPC_FEATURES
    client._sock = object()
    monkeypatch.setattr(config, "settings", client_settings)
    monkeypatch.setattr(commands, "_model_available_for_role", lambda *_: True)
    monkeypatch.setattr("core.cli.commands._check_provider_key", lambda *_: None)
    monkeypatch.setattr("core.cli.commands.remove_env", lambda *_: False)
    monkeypatch.setattr(
        "core.config.env_io.upsert_config_toml", lambda *a, **k: events.append("persist")
    )
    if reject:
        monkeypatch.setattr(
            "core.agent.loop._model_switching.adapt_context_for_model",
            AsyncMock(side_effect=RuntimeError("not applied")),
        )
    commands.cmd_model("gpt-6-luna", client=client)
    if reject:
        assert events == ["error"]
        assert client_settings.model == daemon_settings.model == loop.model == "gpt-6-sol"
    else:
        assert events[0] == "applied" and "persist" in events
        assert client_settings.model == loop.model == "gpt-6-luna"
        assert daemon_settings.model == "gpt-6-sol"
        assert loop._effort == "high"


def test_best_of_judge_keeps_explicit_session_route_after_defaults_change(loop, monkeypatch):
    from core.agent.candidate_sampling import CandidateVerdict
    from core.agent.sub_agent import SubResult
    from core.config import settings

    loop._model_settings = loop._model_settings.updated(
        {
            "judge_model": "gpt-6-luna",
            "judge_source": "subscription",
        }
    )
    monkeypatch.setattr(settings, "judge_model", "glm-5.3")
    captured = []

    async def judge(*args, **kwargs):
        captured.append(kwargs)
        return CandidateVerdict(0, "checked")

    monkeypatch.setattr("core.agent.candidate_sampling.judge_candidates", judge)
    context = SimpleNamespace(
        agent_loop=loop,
        model=loop.model,
        provider=loop._provider,
        source=loop._source,
        effort=loop._effort,
    )
    results = [
        SubResult(
            success=True,
            output={"text": "candidate"},
            task_id="candidate-1",
            description="candidate",
        )
    ]
    asyncio.run(
        loop.executor._select_best_candidate(
            task_description="task", results=results, context=context
        )
    )
    assert captured[0]["model"] == "gpt-6-luna"
    assert captured[0]["source"] == "subscription"
    assert captured[0]["effort"] == "low"


def test_picker_uses_live_policy_and_preserves_source_on_effort_only_change(loop, monkeypatch):
    from core import config
    from core.cli import effort_picker
    from core.cli.commands import model as commands
    from core.cli.ipc_client import IPCClient
    from core.config import settings

    client = IPCClient()
    client.model_config = loop._model_settings.updated({"source": "subscription"}).model_dump()
    selected = []
    sent = []

    def picker(_profiles, current_model, current_effort, **kwargs):
        selected.append((current_model, current_effort, kwargs["role_initial_models"]))
        return effort_picker.PickerResult(model_id=current_model, effort="medium")

    monkeypatch.setattr(
        config,
        "settings",
        settings.model_copy(
            update={
                "model": "gpt-6-luna",
                "agentic_effort": "high",
                "openai_credential_source": "api_key",
            }
        ),
    )
    monkeypatch.setattr(commands, "_ensure_profiles_hydrated", lambda: None)
    monkeypatch.setattr(commands, "model_available", lambda _, **kwargs: True)
    monkeypatch.setattr(commands, "model_unavailable_reason", lambda *a, **k: None)
    monkeypatch.setattr(commands, "_apply_model", lambda *a, **k: None)
    monkeypatch.setattr(effort_picker, "pick_model_and_effort", picker)
    monkeypatch.setattr(
        client, "apply_model_config", lambda data: sent.append(data) or {"status": "applied"}
    )
    commands._interactive_model_picker(client=client)
    assert selected[0][:2] == ("gpt-6-sol", "low")
    assert sent == [{"model": "gpt-6-sol", "effort": "medium", "source": "subscription"}]


def test_effort_only_change_admits_current_payg_model_after_future_default_changes(monkeypatch):
    from core.cli.commands import _state
    from core.cli.commands import model as commands
    from core.cli.effort_picker import PickerResult
    from core.cli.ipc_client import IPCClient
    from core.config.session import SessionModelConfig

    client = IPCClient()
    client.model_config = SessionModelConfig(
        model="gpt-5.4", effort="low", source="payg"
    ).model_dump()
    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "subscription")
    profile = next(p for p in _state.get_model_profiles(openai_source="payg") if p.id == "gpt-5.4")
    assert (
        commands._model_selection_error(
            profile, "medium", _state.role_by_name("primary"), source=None
        )
        is not None
    )  # The old default-based admission rejects this valid PAYG route.
    accepted = []
    monkeypatch.setattr(
        client, "apply_model_config", lambda value: accepted.append(value) or {"status": "applied"}
    )
    monkeypatch.setattr(commands, "_apply_model", lambda *a, **k: None)
    commands._apply_picker_result(
        PickerResult(model_id="gpt-5.4", effort="medium"), [profile], client=client
    )
    assert accepted == [{"model": "gpt-5.4", "effort": "medium", "source": "payg"}]


@pytest.mark.parametrize(
    ("role", "inherited", "target", "expected_source"),
    [
        ("primary", False, "gpt-6-luna", "subscription"),
        ("reflection", False, "gpt-6-luna", "subscription"),
        ("reflection", True, "gpt-6-luna", "subscription"),
        ("primary", False, "glm-5.3", "payg"),
    ],
)
def test_named_model_change_preserves_live_provider_source(
    loop, monkeypatch, role, inherited, target, expected_source
):
    from core.cli.commands import model as commands
    from core.cli.ipc_client import IPCClient
    from core.config import settings

    changes = {"source": "subscription"}
    if role == "reflection" and not inherited:
        changes.update(reflection_model="gpt-6-sol", reflection_source="subscription")
    asyncio.run(apply_session_model_config(loop, loop._model_settings.updated(changes)))
    monkeypatch.setattr(settings, "openai_credential_source", "api_key")
    client = IPCClient()
    client.features = IPC_FEATURES
    client._sock = object()
    client.model_config = loop._model_settings.model_dump()
    responses = []
    availability = []
    persisted = []
    poller = _poller()

    def send(value):
        responses.append(
            asyncio.run(
                poller._process_message_async(
                    decode_message(encode_message(value)), loop, loop.context, "test"
                )
            )
        )
        return "request"

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(client, "_recv_for", lambda _: responses[-1])
    monkeypatch.setattr(
        commands,
        "model_available",
        lambda model, *, source=None: availability.append((model, source)) or True,
    )
    monkeypatch.setattr(commands, "_apply_model", lambda *a, **k: persisted.append(k))
    commands.cmd_model(f"{role} {target}", client=client)

    field = "model" if role == "primary" else "reflection_model"
    source_field = "source" if role == "primary" else "reflection_source"
    assert responses[-1]["status"] == "applied"
    assert getattr(loop._model_settings, field) == target
    assert getattr(loop._model_settings, source_field) == expected_source
    assert client.model_config[source_field] == expected_source
    assert persisted and availability == [
        (target, expected_source if target.startswith("gpt-") else None)
    ]

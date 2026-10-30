"""The connected CLI observes backend eligibility, and admission blocks dispatch."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from core.cli.ipc_client import IPCClient
from core.config.session import SessionModelConfig
from core.ipc_protocol import IPC_FEATURES
from core.llm.adapters.registry import active_registry_snapshot
from core.server.ipc_server.poller import CLIPoller


def poller(monkeypatch):
    instance = object.__new__(CLIPoller)
    instance._services = SimpleNamespace(lane_queue=None, command_registry=None)
    monkeypatch.setattr(instance, "_propagate_contextvars", lambda: None)
    return instance


def test_unconnected_prompt_never_enters_agent_loop(monkeypatch):
    from core.cli import session_state
    from core.wiring.startup import ReadinessReport

    monkeypatch.setattr(
        session_state, "_get_readiness", lambda: ReadinessReport(force_dry_run=True)
    )
    monkeypatch.setattr("core.llm.routing.model_available", lambda model, source=None: False)
    arun = AsyncMock(side_effect=AssertionError("adapter dispatch must not be reached"))
    loop = SimpleNamespace(
        model="gpt-6.1-sol",
        _source="subscription",
        arun=arun,
        _adapter_registry_snapshot=active_registry_snapshot(),
    )
    result = asyncio.run(poller(monkeypatch)._run_prompt_streaming_async("hello", loop, None))
    assert result["error_type"] == "credential_unavailable"
    assert "/login" in result["message"] and "/model" in result["message"]
    arun.assert_not_awaited()


@pytest.mark.parametrize("bad", [[{}], [{"model": "gpt-6.1-sol", "source": "auto"}], [{}] * 257])
def test_backend_route_queries_are_bounded_and_validated(monkeypatch, bad):
    result = asyncio.run(
        poller(monkeypatch)._handle_command_on_server(
            {"cmd": "/model", "model_queries": bad}, SimpleNamespace()
        )
    )
    assert result["status"] == "error"


def test_connected_picker_uses_backend_and_rejects_stale_local_eligibility(monkeypatch):
    from core.cli.commands import model as commands
    from core.cli.commands._state import role_by_name

    backend = poller(monkeypatch)
    monkeypatch.setattr("core.llm.routing.model_available", lambda *a, **kw: False)
    monkeypatch.setattr(commands, "model_available", lambda *a, **kw: True)
    client = IPCClient()
    client.features = IPC_FEATURES
    client._sock = Mock(gettimeout=Mock(return_value=None))
    client.model_config = SessionModelConfig(
        model="gpt-6.1-sol", source="subscription", effort="high"
    ).model_dump()
    pending = []
    monkeypatch.setattr(client, "_send", lambda payload: pending.append(payload) or "q")
    monkeypatch.setattr(
        client,
        "_recv_for",
        lambda request_id, **kwargs: asyncio.run(
            backend._handle_command_on_server(
                pending[-1], SimpleNamespace(_adapter_registry_snapshot=active_registry_snapshot())
            )
        ),
    )
    assert not commands._model_available_for_role("gpt-6.1-sol", role_by_name("primary"), client)
    assert pending[-1]["model_queries"] == [{"model": "gpt-6.1-sol", "source": "subscription"}]


def test_connected_route_query_never_falls_back_on_old_or_incomplete_daemon(monkeypatch):
    client = IPCClient()
    with pytest.raises(ValueError, match="Restart serve"):
        client.inspect_model_routes([("gpt-6.1-sol", "subscription")])
    client.features = IPC_FEATURES
    client._sock = Mock(gettimeout=Mock(return_value=None))
    monkeypatch.setattr(client, "_send", lambda payload: "q")
    monkeypatch.setattr(
        client, "_recv_for", lambda request_id, **kwargs: {"status": "ok", "model_routes": []}
    )
    with pytest.raises(ValueError, match="Incomplete"):
        client.inspect_model_routes([("gpt-6.1-sol", "subscription")])


def test_switch_admission_rejects_unavailable_route_without_mutating_session(monkeypatch):
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor

    config = SessionModelConfig(model="gpt-6.1-sol", effort="high", source="subscription")
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        model=config.model,
        provider="openai",
        config=AgenticLoopConfig(model_settings=config, source=config.source),
    )
    monkeypatch.setattr("core.llm.routing.model_available", lambda *a, **kw: False)
    with pytest.raises(ValueError, match="not connected"):
        asyncio.run(
            poller(monkeypatch)._apply_session_selection(
                {"model_config": {"model": "gpt-6-luna"}}, loop
            )
        )
    assert loop._model_settings == config
    assert loop.model == config.model and loop._source == config.source


@pytest.mark.parametrize("captured_available", [True, False])
def test_admission_and_queries_use_session_adapter_generation_with_fresh_credentials(
    monkeypatch, captured_available
):
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.loop.models import AgenticResult
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters import registry
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.adapters.base import CredentialDetection
    from core.llm.registry import get_provider_spec

    availability = {"current": captured_available}
    captured_adapter = AnthropicPaygAdapter()
    monkeypatch.setattr(
        captured_adapter,
        "detect_model_credential",
        lambda model: (
            CredentialDetection(model=model, provider="anthropic", source_path="synthetic")
            if availability["current"]
            else None
        ),
    )
    registry.register_adapter(
        captured_adapter,
        provider_spec=get_provider_spec("anthropic"),
        replace=True,
        trust_decision="synthetic-session-generation",
    )
    config = SessionModelConfig(model="claude-opus-5-5", source="payg", effort="high")
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        model=config.model,
        provider="anthropic",
        config=AgenticLoopConfig(model_settings=config, source=config.source),
    )
    captured = loop._adapter_registry_snapshot
    replacement = AnthropicPaygAdapter()
    monkeypatch.setattr(
        replacement,
        "detect_model_credential",
        lambda model: (
            None
            if captured_available
            else CredentialDetection(
                model=model, provider="anthropic", source_path="synthetic-replacement"
            )
        ),
    )
    registry.register_adapter(
        replacement,
        provider_spec=get_provider_spec("anthropic"),
        replace=True,
        trust_decision="synthetic-registry-replacement",
    )
    ambient = registry.active_registry_snapshot()
    assert ambient.generation != captured.generation
    arun = AsyncMock(return_value=AgenticResult(text="synthetic"))
    monkeypatch.setattr(loop, "arun", arun)
    monkeypatch.setattr("core.agent.loop._model_switching.adapt_context_for_model", AsyncMock())
    backend = poller(monkeypatch)
    query = {"cmd": "/model", "model_queries": [{"model": config.model, "source": "payg"}]}
    result = asyncio.run(backend._handle_command_on_server(query, loop))
    assert result["model_routes"][0]["available"] is captured_available
    response = asyncio.run(backend._run_prompt_streaming_async("synthetic", loop, None))
    assert arun.await_count == int(captured_available)
    assert (response.get("error_type") == "credential_unavailable") is not captured_available
    change = {"model_config": {"model": "claude-fable-5-1"}}
    if captured_available:
        assert asyncio.run(backend._apply_session_selection(change, loop))["status"] == "applied"
        assert loop._new_adapter is captured_adapter
    else:
        with pytest.raises(ValueError, match="not connected"):
            asyncio.run(backend._apply_session_selection(change, loop))
        assert loop._model_settings == config
    # The adapter generation stays pinned; credential state is not snapshotted.
    availability["current"] = not captured_available
    result = asyncio.run(backend._handle_command_on_server(query, loop))
    assert result["model_routes"][0]["available"] is not captured_available
    assert registry.active_registry_snapshot() is ambient

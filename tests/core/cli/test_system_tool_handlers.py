"""Status observes current credentials independently of CLI startup snapshots."""

from __future__ import annotations

import pytest
from core.cli import session_state
from core.cli.tool_handlers import cli_handler_groups
from core.wiring import startup


@pytest.mark.parametrize("credential", ["api", "subscription", "profile"])
def test_status_tracks_credentials_without_cli_bootstrap(
    credential: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    available = False
    monkeypatch.setattr(session_state, "_get_readiness", lambda: None)
    monkeypatch.setattr(startup, "_has_any_llm_key", lambda: available and credential == "api")
    monkeypatch.setattr(
        startup,
        "detect_subscription_oauth",
        lambda: "openai" if available and credential == "subscription" else None,
    )
    monkeypatch.setattr(
        startup, "_has_available_profile", lambda: available and credential == "profile"
    )
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    status = handlers["check_status"]

    assert status()["mode"] == "dry_run"
    available = True
    assert status()["mode"] == "full_llm"
    available = False
    assert status()["mode"] == "dry_run"


def test_status_reads_explicit_request_policy_after_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = startup.ReadinessReport(force_dry_run=True)
    monkeypatch.setattr(session_state, "_get_readiness", lambda: readiness)
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    status = handlers["check_status"]

    assert status()["mode"] == "dry_run"
    readiness = startup.ReadinessReport(force_dry_run=False)
    assert status()["mode"] == "full_llm"
    readiness = startup.ReadinessReport(force_dry_run=True)
    assert status()["mode"] == "dry_run"


@pytest.mark.parametrize("yield_after_batch", [False, True])
@pytest.mark.parametrize("role,hint", [("primary", "gpt-6-luna"), ("judgment", "llm")])
def test_registered_selection_commits_after_tool_batch_without_changing_defaults(
    monkeypatch, tmp_path, yield_after_batch, role, hint
):
    import asyncio
    import json
    from copy import deepcopy
    from unittest.mock import AsyncMock

    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.config import settings
    from core.config.session import SessionModelConfig
    from core.llm.adapters.base import AdapterCallResult, UsageSummary

    monkeypatch.setattr("core.paths.get_project_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "replan_enabled", False)
    monkeypatch.setattr(settings, "model", "gpt-6-astra")
    monkeypatch.setattr(settings, "judgment_engine", "jev")
    monkeypatch.setattr(session_state, "_get_readiness", lambda: startup.ReadinessReport())
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    requests = []

    class Adapter:
        name = "capture"
        provider = "openai"
        source = "payg"

        async def acomplete(self, request):
            requests.append(deepcopy(request))
            if len(requests) == 1:
                return AdapterCallResult(
                    text="",
                    usage=UsageSummary(),
                    stop_reason="tool_use",
                    tool_uses=(
                        {
                            "id": "switch",
                            "name": "switch_model",
                            "input": {"role": role, "model_hint": hint},
                        },
                        {"id": "status", "name": "check_status", "input": {}},
                    ),
                )
            return AdapterCallResult(text="done", usage=UsageSummary(), stop_reason="end_turn")

    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers=handlers, approval_callback=lambda *_args: "y"),
        model="gpt-6-sol",
        provider="openai",
        quiet=True,
        config=AgenticLoopConfig(
            source="payg",
            effort="high",
            max_rounds=4,
            yield_after_tool_round=yield_after_batch,
            allowed_tool_names={"switch_model", "check_status"},
            system_prompt_override="Offline selection test.",
            model_settings=SessionModelConfig(
                model="gpt-6-sol",
                source="payg",
                effort="high",
                judgment_engine="jev" if role == "judgment" else "llm",
            ),
        ),
    )
    loop._new_adapter = Adapter()
    # Focus on registered tool -> batch boundary -> next physical request.
    # Auxiliary judgment is covered separately by its request-level tests.
    loop._finish_cognitive_tool_round = AsyncMock()
    loop._afinalize_and_return = AsyncMock(side_effect=lambda result, *_args: result)
    before = loop._model_settings
    result = asyncio.run(loop._arun_once("Switch as requested, then check status."))
    assert result.termination_reason == ("tool_use_yield" if yield_after_batch else "natural")
    expected = hint if role == "primary" else "gpt-6-sol"
    assert (loop.model, loop._source, loop._effort) == (expected, "payg", "high")
    assert loop._model_settings.judgment_engine == "llm"
    assert loop._pending_model_settings is None
    assert (settings.model, settings.judgment_engine) == ("gpt-6-astra", "jev")
    results = {
        block["tool_use_id"]: json.loads(block["content"])
        for message in loop.context.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    assert results["switch"]["status"] == "pending"
    # Even a sibling tool in the same batch observes the original selection.
    assert results["status"]["model_config"] == before.model_dump()
    if not yield_after_batch:
        assert [request.model for request in requests] == ["gpt-6-sol", expected]
        assert requests[1].effort == "high"
        assert "switch" in str(requests[1].messages) and "status" in str(requests[1].messages)
    else:
        assert len(requests) == 1


def test_selection_requires_owner_and_rejects_invalid_candidate(monkeypatch, tmp_path):
    import asyncio

    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.config.session import SessionModelConfig
    from core.tools.base import ToolContext

    monkeypatch.setattr("core.paths.get_project_root", lambda: tmp_path)
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    handler = handlers["switch_model"]
    assert asyncio.run(handler(model_hint="gpt-6-sol"))["error_type"] == "dependency"
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        model="gpt-6-sol",
        provider="openai",
        quiet=True,
        config=AgenticLoopConfig(
            source="subscription",
            effort="none",
            model_settings=SessionModelConfig(
                model="gpt-6-sol", source="subscription", effort="none"
            ),
        ),
    )
    original = loop._model_settings
    result = asyncio.run(
        handler(model_hint="gpt-6-astra", _tool_context=ToolContext(agent_loop=loop))
    )
    assert result["error_type"] == "validation"
    assert loop._pending_model_settings is None and loop._model_settings is original

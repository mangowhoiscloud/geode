"""Cache boundaries survive volatile context without crossing route contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.openai_payg import OpenAIPaygAdapter
from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter
from openai import AsyncOpenAI


def _request(model: str, tail: str = "first") -> AdapterCallRequest:
    return AdapterCallRequest(
        model=model,
        system_prompt=f"Stable rules.\n\n{PROMPT_CACHE_BOUNDARY}{tail}</dynamic_context>",
        messages=(Message(role="user", content="task"),),
        metadata={"session_id": "private-session"},
    )


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol"])
def test_platform_static_breakpoint_survives_dynamic_context(model: str) -> None:
    first, second = (
        build_responses_kwargs(
            _request(model, tail), backend="platform", adapter_name="openai-payg"
        )
        for tail in ("first", "second")
    )
    first_block = first["input"][0]["content"][0]
    assert first["input"][0]["role"] == "developer"
    assert first_block == second["input"][0]["content"][0]
    assert first_block["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "instructions" not in first
    assert "prompt_cache_options" not in first  # Keep implicit history caching active.
    assert (
        "".join(block["text"] for block in first["input"][0]["content"])
        == _request(model).system_prompt
    )
    assert first["input"][1:] == second["input"][1:]


@pytest.mark.parametrize(("model", "backend"), [("gpt-5.5", "platform"), ("gpt-6-sol", "codex")])
def test_explicit_breakpoints_do_not_cross_unverified_routes(model: str, backend: str) -> None:
    request = _request(model)
    wire = build_responses_kwargs(request, backend=backend, adapter_name="fixture")
    assert wire["instructions"] == request.system_prompt
    assert "prompt_cache_breakpoint" not in json.dumps(wire)


@pytest.mark.parametrize("system", ["plain instructions", f"{PROMPT_CACHE_BOUNDARY}dynamic"])
def test_platform_does_not_invent_empty_or_unmarked_prefixes(system: str) -> None:
    request = replace(_request("gpt-6-sol"), system_prompt=system)
    wire = build_responses_kwargs(request, backend="platform", adapter_name="openai-payg")
    assert wire["instructions"] == system
    assert "prompt_cache_breakpoint" not in json.dumps(wire)


def test_platform_sdk_sends_static_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        event = {
            "type": "response.completed",
            "sequence_number": 1,
            "response": {
                "id": "resp-cache",
                "object": "response",
                "created_at": 0,
                "model": "gpt-6-sol",
                "status": "completed",
                "output": [],
                "usage": {
                    "input_tokens": 1100,
                    "output_tokens": 1,
                    "total_tokens": 1101,
                    "input_tokens_details": {"cached_tokens": 1024},
                },
            },
        }
        created = {
            "type": "response.created",
            "sequence_number": 0,
            "response": {**event["response"], "status": "in_progress"},
        }
        return httpx.Response(
            200,
            text="".join(
                f"event: {item['type']}\ndata: " + json.dumps(item) + "\n\n"
                for item in (created, event)
            ),
            headers={"content-type": "text/event-stream"},
        )

    async def run() -> None:
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenAIPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            events = [event async for event in adapter.astream(_request("gpt-6-sol"))]
            usage = next(event.payload for event in events if event.kind == "usage")
            assert usage["cached_input_tokens"] == 1024
            assert events[-1].kind == "stop"

    asyncio.run(run())
    wire = bodies[0]
    assert "instructions" not in wire
    assert wire["input"][0]["role"] == "developer"
    assert wire["input"][0]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "prompt_cache_breakpoint" not in wire["input"][0]["content"][1]


def _chat_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "gen-fixture",
            "object": "chat.completion",
            "created": 0,
            "model": json.loads(request.content)["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 1,
                "total_tokens": 101,
                "cost": 0.001,
                "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 10},
            },
        },
    )


@pytest.mark.parametrize(
    ("model", "marker"),
    [
        ("anthropic/claude-opus-5.5", "cache_control"),
        ("openai/gpt-6-sol", "prompt_cache_breakpoint"),
        ("openai/gpt-5.5", None),
        ("z-ai/glm-5.3", None),
        ("openrouter/auto", None),
    ],
)
def test_openrouter_wire_preserves_cache_and_session_ownership(
    monkeypatch: pytest.MonkeyPatch, model: str, marker: str | None
) -> None:
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _chat_response(request)

    async def run() -> None:
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            for tail in ("first", "second"):
                result = await adapter.acomplete(
                    replace(
                        _request(f"openrouter/{model}", tail),
                        messages=tuple(Message(role="user", content=f"turn {i}") for i in range(4)),
                    )
                )
                assert result.usage.cached_input_tokens == 80
                assert result.usage.cache_write_tokens == 10
                assert result.usage.reported_cost_usd == 0.001
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as new_client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": new_client)
            await adapter.acomplete(_request(f"openrouter/{model}"))
            monkeypatch.setattr(
                "core.agent.cognitive_state_ctx.get_session_id", lambda: "another-session"
            )
            await adapter.acomplete(replace(_request(f"openrouter/{model}"), metadata={}))

    asyncio.run(run())
    assert bodies[0]["session_id"] == bodies[1]["session_id"] == bodies[2]["session_id"]
    assert bodies[3]["session_id"] != bodies[0]["session_id"]
    assert "private-session" not in json.dumps(bodies)
    if marker == "cache_control":
        assert json.dumps(bodies[0]).count('"cache_control"') == 4
    content = bodies[0]["messages"][0]["content"]
    if marker:
        expected = (
            {"type": "ephemeral", "ttl": "1h"}
            if marker == "cache_control"
            else {"mode": "explicit"}
        )
        assert content[0][marker] == expected
        assert content[0] == bodies[1]["messages"][0]["content"][0]
        assert marker not in content[1]
    else:
        assert content == _request(f"openrouter/{model}").system_prompt
        assert "cache_control" not in json.dumps(bodies)


def test_openrouter_session_context_is_task_local_and_retains_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.cognitive_state_ctx import get_session_id, set_session_id

    bodies: dict[str, dict[str, Any]] = {}
    policy = {"order": ["openai"], "only": ["openai"], "allow_fallbacks": False}

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies[body["messages"][-1]["content"]] = body
        return _chat_response(request)

    async def run() -> None:
        set_session_id("parent-session")
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)

            async def call(label: str, context: str, metadata: dict[str, Any]) -> None:
                set_session_id(context)
                await asyncio.sleep(0)  # Interleave task bindings before request shaping.
                await adapter.acomplete(
                    replace(
                        _request("openrouter/openai/gpt-6-sol"),
                        messages=(Message(role="user", content=label),),
                        metadata=metadata,
                        provider_options={"openrouter": policy},
                    )
                )

            await asyncio.gather(
                call("missing", "", {}),
                call("explicit", "ignored-context", {"session_id": "explicit-session"}),
                call("task-a", "session-a", {}),
                call("task-b", "session-b", {}),
            )
            assert get_session_id() == "parent-session"

    asyncio.run(run())
    assert "session_id" not in bodies["missing"]
    for label, session in (
        ("explicit", "explicit-session"),
        ("task-a", "session-a"),
        ("task-b", "session-b"),
    ):
        expected = "geode-" + hashlib.sha256(session.encode()).hexdigest()
        assert bodies[label]["session_id"] == expected
        assert len(expected) <= 256
        assert session not in json.dumps(bodies[label])
    assert bodies["task-a"]["session_id"] != bodies["task-b"]["session_id"]
    assert all(body["provider"] == policy for body in bodies.values())


@pytest.mark.parametrize("turns", [0, 1, 3, 12])
@pytest.mark.parametrize("marked_system", [False, True])
def test_openrouter_claude_marker_budget_on_actual_sdk_wire(
    monkeypatch: pytest.MonkeyPatch, turns: int, marked_system: bool
) -> None:
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _chat_response(request)

    request = replace(
        _request("openrouter/anthropic/claude-sonnet-5"),
        system_prompt=_request("unused").system_prompt if marked_system else "plain rules",
        messages=tuple(Message(role="user", content=f"turn {i}") for i in range(turns)),
    )

    async def run() -> None:
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            await adapter.acomplete(request)

    asyncio.run(run())
    markers = [
        block["cache_control"]
        for message in bodies[0]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if "cache_control" in block
    ]
    assert len(markers) == min(turns, 3) + int(marked_system)
    assert len(markers) <= 4
    if marked_system:
        assert markers[0] == {"type": "ephemeral", "ttl": "1h"}
    assert all(marker == {"type": "ephemeral"} for marker in markers[int(marked_system) :])
    assert all(isinstance(message.content, str) for message in request.messages)

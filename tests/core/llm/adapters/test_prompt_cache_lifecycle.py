"""Cache boundaries survive volatile context without crossing route contracts."""

from __future__ import annotations

import asyncio
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
            monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
        return httpx.Response(
            200,
            json={
                "id": "gen-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": model,
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

    async def run() -> None:
        async with AsyncOpenAI(
            api_key="fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda: client)
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
            monkeypatch.setattr(adapter, "_get_client", lambda: new_client)
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

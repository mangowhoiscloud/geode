"""GEODE-owned inspect_ai providers serialize current model contracts.

The registered ``openai-platform``, ``openai-codex`` and ``anthropic-platform``
ModelAPIs run their real ``generate`` and SDK clients; only the HTTP transport
is fake. The stock ``openai``/``anthropic`` providers stay as raw escape hatches.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.tool import ToolFunction, ToolInfo, ToolParams


@pytest.fixture(autouse=True)
def _registered(monkeypatch: pytest.MonkeyPatch) -> None:
    from evals.petri.adapters import http_anthropic, http_openai
    from evals.petri.codex_provider import register as register_codex

    for name in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    http_openai.register()
    http_anthropic.register()
    register_codex()


_TOOL = ToolInfo(name="lookup", description="Lookup", parameters=ToolParams())
_INPUT = [ChatMessageUser(content="hi")]


def _openai_response(model: str) -> dict[str, Any]:
    item = {
        "type": "message",
        "id": "msg-1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "ok", "annotations": []}],
    }
    return {
        "id": "resp-1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": model,
        "output": [item],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


def _openai_sse(model: str) -> str:
    final = _openai_response(model)
    events = [
        {"type": "response.created", "response": {**final, "status": "in_progress", "output": []}},
        {"type": "response.output_item.done", "output_index": 0, "item": final["output"][0]},
        {"type": "response.completed", "response": final},
    ]
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps({**e, 'sequence_number': i})}\n\n"
        for i, e in enumerate(events)
    )


def _bind_openai(api: Any, wire: list[httpx.Request], model: str) -> None:
    from openai import AsyncOpenAI

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(request)
        if json.loads(request.content).get("stream"):
            return httpx.Response(
                200, text=_openai_sse(model), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=_openai_response(model))

    api.client = AsyncOpenAI(
        api_key="fixture",
        base_url=str(api.client.base_url),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )


@pytest.mark.parametrize("prefix", ["openai-platform", "openai-codex"])
@pytest.mark.parametrize(
    "model",
    [
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ],
)
@pytest.mark.parametrize("effort", ["medium", "max"])
def test_openai_providers_send_responses_with_native_effort(
    monkeypatch: pytest.MonkeyPatch, prefix: str, model: str, effort: str
) -> None:
    if prefix == "openai-codex":
        monkeypatch.setattr(
            "core.llm.providers.codex.resolve_codex_token", lambda *a, **k: "fixture"
        )
    api = get_model(f"{prefix}/{model}").api
    wire: list[httpx.Request] = []
    _bind_openai(api, wire, model)
    asyncio.run(api.generate(_INPUT, [_TOOL], "auto", GenerateConfig(reasoning_effort=effort)))

    expected = (
        "https://chatgpt.com/backend-api/codex/responses"
        if prefix == "openai-codex"
        else "https://api.openai.com/v1/responses"
    )
    assert {str(request.url) for request in wire} == {expected}  # never Chat Completions
    # inspect_ai's one-time reasoning-summary probe (stock behavior for reasoning
    # models) may precede the call; it must also use a supported effort.
    from core.llm.adapters._openai_common import get_openai_model_spec

    supported = get_openai_model_spec(model).reasoning_effort_values or ()
    bodies = [json.loads(request.content) for request in wire]
    assert len(bodies) <= 2 and all(b["reasoning"]["effort"] in supported for b in bodies)
    body = bodies[-1]
    assert body["model"] == model
    assert body["reasoning"]["effort"] == effort  # not dropped, max not lowered to xhigh
    assert body["tools"][0]["name"] == "lookup"


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-astra"])
@pytest.mark.parametrize("effort", ["none", "minimal"])
def test_openai_provider_rejects_unsupported_effort_before_request(model: str, effort: str) -> None:
    api = get_model(f"openai-platform/{model}").api
    wire: list[httpx.Request] = []
    _bind_openai(api, wire, model)
    with pytest.raises(ValueError, match="does not accept reasoning_effort"):
        asyncio.run(api.generate(_INPUT, [], "auto", GenerateConfig(reasoning_effort=effort)))
    assert wire == []


def test_openai_endpoint_is_bound_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    api = get_model("openai-platform/gpt-6.1-sol").api
    assert api.base_url == "https://api.openai.com/v1" and api.responses_api is True
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.test/v1")
    api.initialize()  # a client rebuild keeps the bound endpoint and classification
    assert str(api.client.base_url).startswith("https://api.openai.com/v1")
    assert api.is_gpt_5() is True

    gateway = get_model("openai-platform/gpt-6.1-sol", memoize=False).api
    assert gateway.base_url == "https://gateway.example.test/v1"
    # A familiar name on a custom gateway is not a verified current contract.
    assert gateway.is_gpt_5() is False and gateway.responses_api is False


def test_codex_override_endpoint_and_raw_stock_prefix_keep_stock_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.llm.providers.codex.resolve_codex_token", lambda *a, **k: "fixture")
    codex = get_model("openai-codex/gpt-6.1-sol").api
    assert codex.is_gpt_5() is True and codex.supports_max_reasoning_effort() is True
    custom = get_model(
        "openai-codex/gpt-6.1-sol", base_url="https://gateway.example.test", memoize=False
    ).api
    assert custom.is_gpt_5() is False
    # Raw ``openai/<model>`` is inspect_ai's stock provider: an explicit escape hatch.
    raw = get_model("openai/gpt-6.1-sol").api
    assert raw.is_gpt_5() is False and raw.responses_api is False


def _anthropic_message(model: str) -> dict[str, Any]:
    return {
        "id": "msg-1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _anthropic(model: str, **model_args: Any) -> tuple[Any, list[httpx.Request]]:
    from anthropic import AsyncAnthropic

    api = get_model(f"anthropic-platform/{model}", streaming=False, memoize=False, **model_args).api
    wire: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wire.append(request)
        return httpx.Response(200, json=_anthropic_message(model))

    api.client = AsyncAnthropic(
        api_key="fixture",
        base_url=str(api.client.base_url),
        timeout=60.0,  # skips the SDK's non-streaming duration guard; no network
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    return api, wire


def _send(api: Any, tool_choice: Any, **config: Any) -> None:
    config = {"max_tokens": 1024, **config}  # non-streaming SDK calls need a bound
    asyncio.run(api.generate(_INPUT, [_TOOL], tool_choice, GenerateConfig(**config)))


@pytest.mark.parametrize(
    ("model", "tool_choice", "expected"),
    [
        ("claude-sonnet-5-5", "none", {"type": "none"}),
        ("claude-opus-5-5", "none", {"type": "none"}),
        ("claude-haiku-5-5", "any", {"type": "any"}),
        ("claude-haiku-5-5", ToolFunction(name="lookup"), {"type": "tool", "name": "lookup"}),
    ],
)
def test_explicit_tool_choice_survives_thinking(
    model: str, tool_choice: Any, expected: Any
) -> None:
    api, wire = _anthropic(model)
    _send(api, tool_choice, reasoning_effort="medium")
    body = json.loads(wire[0].content)
    assert body["tool_choice"] == expected
    assert body["thinking"]["type"] == "adaptive"
    assert body["output_config"]["effort"] == "medium"


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"])
@pytest.mark.parametrize("tool_choice", ["any", ToolFunction(name="lookup")])
@pytest.mark.parametrize("config", [{}, {"reasoning_effort": "medium"}])
def test_forced_tool_choice_rejected_before_request(
    model: str, tool_choice: Any, config: dict[str, Any]
) -> None:
    api, wire = _anthropic(model)
    with pytest.raises(ValueError, match="forced tool_choice"):
        _send(api, tool_choice, **config)
    assert wire == []


def test_haiku_55_none_disables_thinking_through_high_only() -> None:
    api, wire = _anthropic("claude-haiku-5-5")
    _send(api, "auto", reasoning_effort="none")
    assert json.loads(wire[0].content)["thinking"] == {"type": "disabled"}
    _send(api, "auto", reasoning_effort="none", effort="high")
    body = json.loads(wire[1].content)
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"]["effort"] == "high"
    for effort in ("xhigh", "max"):
        with pytest.raises(ValueError, match="disabled thinking"):
            _send(api, "auto", reasoning_effort="none", effort=effort)
    assert len(wire) == 2


@pytest.mark.parametrize(
    ("model", "config", "message"),
    [
        ("claude-opus-5-5", {"reasoning_effort": "none"}, "cannot turn thinking off"),
        ("claude-sonnet-5-5", {"reasoning_effort": "none"}, "cannot turn thinking off"),
        ("claude-fable-5-1", {"reasoning_effort": "none"}, "cannot turn thinking off"),
        ("claude-opus-5", {"reasoning_effort": "none", "effort": "max"}, "disabled thinking"),
        ("claude-opus-4-6", {"effort": "xhigh"}, "does not support effort"),
        ("claude-haiku-4-5-20251001", {"effort": "high"}, "does not support effort"),
    ],
)
def test_unsupported_thinking_or_effort_rejects_instead_of_clamping(
    model: str, config: dict[str, Any], message: str
) -> None:
    api, wire = _anthropic(model)
    with pytest.raises(ValueError, match=message):
        _send(api, "auto", **config)
    assert wire == []


def test_anthropic_unknown_model_and_gateway_keep_stock_shaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown, wire = _anthropic("claude-custom-deployment")
    _send(unknown, "any")
    assert json.loads(wire[0].content)["tool_choice"] == {"type": "any"}

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    gateway, gateway_wire = _anthropic("claude-sonnet-5-5")
    assert gateway.base_url == "https://gateway.example.test"
    _send(gateway, "any")  # no GEODE claim about the gateway's contract
    assert json.loads(gateway_wire[0].content)["tool_choice"] == {"type": "any"}


def test_anthropic_endpoint_is_bound_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    api, wire = _anthropic("claude-sonnet-5-5")
    assert api.base_url == "https://api.anthropic.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    with pytest.raises(ValueError, match="forced tool_choice"):
        _send(api, "any")
    assert wire == []


def test_raw_stock_anthropic_prefix_is_an_unmanaged_escape_hatch() -> None:
    """Control: stock shaping drops explicit choices under thinking (hence the owned provider)."""
    from anthropic import AsyncAnthropic

    api = get_model("anthropic/claude-haiku-5-5", streaming=False, memoize=False).api
    wire: list[httpx.Request] = []
    api.client = AsyncAnthropic(
        api_key="fixture",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (
                    wire.append(r)
                    or httpx.Response(200, json=_anthropic_message("claude-haiku-5-5"))
                )
            )
        ),
    )
    _send(api, "any", reasoning_effort="medium")
    assert "tool_choice" not in json.loads(wire[0].content)


@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-opus-4-8"])
def test_disabled_thinking_with_max_stays_allowed_where_not_restricted(model: str) -> None:
    api, wire = _anthropic(model)
    _send(api, "auto", reasoning_effort="none", effort="max")
    body = json.loads(wire[0].content)
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"]["effort"] == "max"


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929"])
@pytest.mark.parametrize("reasoning_effort", ["medium", "high"])
def test_extended_thinking_models_keep_budget_bridge(model: str, reasoning_effort: str) -> None:
    api, wire = _anthropic(model)
    _send(api, "auto", reasoning_effort=reasoning_effort, max_tokens=32_768)
    body = json.loads(wire[0].content)
    assert body["thinking"]["type"] == "enabled"
    assert 1024 <= body["thinking"]["budget_tokens"] < body["max_tokens"]


@pytest.mark.parametrize("tool_choice", ["any", ToolFunction(name="lookup")])
@pytest.mark.parametrize(
    ("model", "config"),
    [
        ("claude-haiku-4-5-20251001", {"reasoning_effort": "medium"}),  # bridged budget
        ("claude-sonnet-4-5-20250929", {"reasoning_effort": "high"}),  # bridged budget
        ("claude-haiku-4-5-20251001", {"reasoning_tokens": 2048}),  # explicit budget
        ("claude-sonnet-4-5-20250929", {"reasoning_tokens": 2048}),
        ("claude-opus-4-6", {"reasoning_tokens": 2048}),
        ("claude-sonnet-4-6", {"reasoning_tokens": 2048}),
    ],
)
def test_manual_thinking_rejects_forced_tool_choice_before_request(
    model: str, config: dict[str, Any], tool_choice: Any
) -> None:
    api, wire = _anthropic(model)
    with pytest.raises(ValueError, match="manual thinking does not support forced"):
        _send(api, tool_choice, max_tokens=32_768, **config)
    assert wire == []


@pytest.mark.parametrize(
    ("model", "config", "thinking"),
    [
        ("claude-haiku-4-5-20251001", {}, None),  # thinking off
        ("claude-sonnet-4-5-20250929", {}, None),
        ("claude-opus-4-6", {"reasoning_effort": "medium"}, "adaptive"),
        ("claude-sonnet-4-6", {"reasoning_effort": "high"}, "adaptive"),
    ],
)
def test_forced_tool_choice_stays_valid_without_manual_thinking(
    model: str, config: dict[str, Any], thinking: str | None
) -> None:
    api, wire = _anthropic(model)
    _send(api, "any", max_tokens=32_768, **config)
    body = json.loads(wire[0].content)
    assert body["tool_choice"] == {"type": "any"}
    assert (body.get("thinking") or {}).get("type") == thinking


def test_direct_provider_applies_lifecycle_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.llm.errors import ModelSourceUnavailableError

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ModelSourceUnavailableError, match="retired"):
        get_model("anthropic-platform/claude-sonnet-4-20250514", memoize=False)
    # The lifecycle owner judges the actual endpoint: a gateway is not the Claude API.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    api = get_model("anthropic-platform/claude-sonnet-4-20250514", memoize=False).api
    assert api.base_url == "https://gateway.example.test"

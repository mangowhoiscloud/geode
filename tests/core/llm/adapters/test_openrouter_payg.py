"""Offline contract tests for the explicit OpenRouter PAYG route."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.hooks import HookEvent, HookSystem
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec, UsageSummary
from core.llm.adapters.dispatch import AdapterDispatchError, complete_text_via_adapters
from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter, _openrouter_extra_body
from core.llm.adapters.provider_inference import infer_provider_from_model
from core.llm.providers.openrouter import to_openrouter_model_id
from core.llm.token_tracker import TokenTracker
from openai import AsyncOpenAI


@pytest.mark.parametrize(
    ("geode_id", "upstream_id"),
    [
        ("openrouter/anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4"),
        ("openrouter/openrouter/free", "openrouter/free"),
        ("openrouter/openrouter/auto", "openrouter/auto"),
    ],
)
def test_model_id_strips_exactly_one_outer_namespace(
    geode_id: str,
    upstream_id: str,
) -> None:
    assert to_openrouter_model_id(geode_id) == upstream_id


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-4",
        "openrouter/",
        "openrouter/free",
        "openrouter/a b/c",
        "openrouter/a/b/c",
    ],
)
def test_model_id_rejects_ambiguous_or_malformed_references(model: str) -> None:
    with pytest.raises(ValueError):
        to_openrouter_model_id(model)


def test_compatibility_provider_inference_preserves_openrouter_identity() -> None:
    assert infer_provider_from_model("openrouter/anthropic/claude-sonnet-4") == "openrouter"


def test_provider_policy_allowlist_preserves_false_and_order() -> None:
    assert _openrouter_extra_body(
        {
            "openrouter": {
                "order": ["Anthropic", "Google"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
            }
        }
    ) == {
        "provider": {
            "order": ["Anthropic", "Google"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "zdr": True,
        }
    }


def test_provider_policy_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unsupported OpenRouter"):
        _openrouter_extra_body({"openrouter": {"max_price": {"prompt": 1}}})


def test_provider_composition_is_explicit_and_attributed() -> None:
    from core.llm.adapters.base import AdapterBillingType
    from core.llm.registry import get_provider_spec

    spec = get_provider_spec("openrouter")
    assert spec is not None
    assert spec.profile.provider == "openrouter"
    assert spec.credential.billing_type is AdapterBillingType.CREDITS
    assert spec.transport.api == "openai-chat-completions"
    assert spec.transport.native_capabilities == frozenset({"text_completion"})
    assert spec.extra_headers_factory is not None
    assert spec.extra_headers_factory("ignored") == {
        "HTTP-Referer": "https://mangowhoiscloud.github.io/geode/",
        "X-OpenRouter-Title": "GEODE",
        "X-OpenRouter-Metadata": "enabled",
    }


@pytest.mark.parametrize(
    "model", ["openrouter/openai/gpt-6-astra", "openrouter/anthropic/claude-fable-5"]
)
def test_chat_route_does_not_inherit_native_search_from_model_name(model: str) -> None:
    from core.llm.adapters._openai_common import build_chat_completion_kwargs
    from core.llm.model_catalog import get_model_catalog_spec
    from core.llm.tool_defer import TOOL_DEFER_THRESHOLD

    specs = tuple(
        ToolSpec(name=f"tool_{i}", description="tool", input_schema={"type": "object"})
        for i in range(TOOL_DEFER_THRESHOLD + 5)
    )
    req = AdapterCallRequest(
        model=model,
        messages=(Message(role="user", content="hi"),),
        tools=specs,
        deferred_tool_names=tuple(tool.name for tool in specs),
    )
    kwargs = build_chat_completion_kwargs(
        req,
        model=to_openrouter_model_id(model),
        provider="openrouter",
        adapter_name="openrouter-payg",
    )
    assert [tool["function"]["name"] for tool in kwargs["tools"]] == [s.name for s in specs]
    assert all(
        tool["type"] == "function" and "defer_loading" not in tool for tool in kwargs["tools"]
    )
    assert not get_model_catalog_spec(model, provider="openrouter").supports_tool_search


class _Completions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def test_missing_key_fails_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    adapter = OpenRouterPaygAdapter()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        asyncio.run(
            adapter.acomplete(
                AdapterCallRequest(
                    model="openrouter/openrouter/free",
                    messages=(Message(role="user", content="hi"),),
                )
            )
        )


def test_provider_error_log_omits_raw_upstream_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = RuntimeError('upstream rejected request; user_id="account-linked-id"')
    completions = _Completions(failure)
    adapter = OpenRouterPaygAdapter()
    monkeypatch.setattr(
        adapter,
        "_get_client",
        lambda model="": SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )

    with (
        caplog.at_level("WARNING", logger="core.llm.adapters.openrouter_payg"),
        pytest.raises(RuntimeError) as exc_info,
    ):
        asyncio.run(
            adapter.acomplete(
                AdapterCallRequest(
                    model="openrouter/deepseek/deepseek-v4-flash-0731",
                    messages=(Message(role="user", content="hi"),),
                )
            )
        )

    assert exc_info.value is failure
    assert "error_type=RuntimeError" in caplog.text
    assert "account-linked-id" not in caplog.text


def test_completion_forwards_chat_tools_and_captures_charge_and_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        id="gen-1",
        model="anthropic/claude-sonnet-4",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, cost=0.0042),
        openrouter_metadata={
            "strategy": "fallback",
            "attempt": 2,
            "endpoints": {
                "available": [
                    {"provider": "Google", "selected": False},
                    {"provider": "Anthropic", "selected": True},
                ]
            },
        },
    )
    completions = _Completions(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenRouterPaygAdapter()
    monkeypatch.setattr(adapter, "_get_client", lambda model="": client)

    result = asyncio.run(
        adapter.acomplete(
            AdapterCallRequest(
                model="openrouter/anthropic/claude-sonnet-4",
                messages=(Message(role="user", content="hi"),),
                tools=(ToolSpec(name="search", description="search", input_schema={}),),
                tool_choice={"type": "tool", "name": "search"},
                provider_options={"openrouter": {"allow_fallbacks": False}},
            )
        )
    )

    assert completions.kwargs["model"] == "anthropic/claude-sonnet-4"
    assert completions.kwargs["extra_body"] == {"provider": {"allow_fallbacks": False}}
    assert completions.kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "search"},
    }
    assert result.usage.reported_cost_usd == pytest.approx(0.0042)
    assert result.response_id == "gen-1"
    assert result.response_model == "anthropic/claude-sonnet-4"
    assert result.response_provider == "Anthropic"
    assert result.routing_strategy == "fallback"
    assert result.routing_attempt == 2


def test_reported_cost_wins_and_zero_is_not_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenTracker, "_persist_usage", lambda *args, **kwargs: None)
    tracker = TokenTracker()

    charged = tracker.record("openrouter/vendor/model", 1_000, 100, reported_cost_usd=0.25)
    free = tracker.record("openrouter/openrouter/free", 1_000, 100, reported_cost_usd=0.0)

    assert charged.cost_usd == pytest.approx(0.25)
    assert free.cost_usd == 0.0
    assert tracker.accumulator.total_cost_usd == pytest.approx(0.25)


@pytest.mark.parametrize("cost", [-1.0, float("inf"), float("nan"), True, "0.1"])
def test_usage_summary_rejects_invalid_provider_cost(cost: Any) -> None:
    error = TypeError if isinstance(cost, (bool, str)) else ValueError
    with pytest.raises(error):
        UsageSummary(reported_cost_usd=cost)


@pytest.mark.parametrize("capability", ["text", "agentic"])
@pytest.mark.parametrize(
    "model, effort, expected_effort",
    [
        ("openrouter/openai/gpt-6-sol", "low", "low"),
        ("openrouter/openai/gpt-6-sol", "max", "max"),
        ("openrouter/openai/gpt-6-sol", "none", "none"),
        ("openrouter/openai/gpt-6-sol", None, None),
        ("openrouter/openai/gpt-6-astra", "low", "low"),
        ("openrouter/openai/gpt-6-luna", "low", "low"),
        ("openrouter/openai/gpt-4.1", "low", None),
        ("openrouter/openai/unregistered-model", "low", None),
        ("openrouter/anthropic/claude-sonnet-4", "low", None),
        ("openrouter/z-ai/glm-5.3", "low", None),
    ],
)
def test_sdk_wire_preserves_text_route_usage_and_supported_effort(
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    model: str,
    effort: str | None,
    expected_effort: str | None,
) -> None:
    bodies: list[dict[str, Any]] = []
    hooks = HookSystem()
    rows: list[dict[str, Any]] = []
    hooks.register(HookEvent.LLM_CALL_ENDED, lambda _event, data: rows.append(dict(data)))
    system = f"Stable rules.\n\n{PROMPT_CACHE_BOUNDARY}current context</dynamic_context>"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openrouter.ai"
        assert request.url.path == "/api/v1/chat/completions"
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(
            200,
            json={
                "id": "gen-text",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "summary"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 13,
                    "total_tokens": 133,
                    "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 10},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                    "cost": 0.0042,
                },
            },
        )

    async def run() -> Any:
        async with AsyncOpenAI(
            api_key="fixture",
            base_url="https://openrouter.ai/api/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [adapter])
            monkeypatch.setattr(
                "core.agent.cognitive_state_ctx.get_session_id", lambda: "private-session"
            )
            if capability == "text":
                return await complete_text_via_adapters(
                    "prior conversation",
                    system=system,
                    model=model,
                    effort=effort,
                    max_tokens=10_000,
                    prefer_provider="openrouter",
                    prefer_source="payg",
                    purpose="context_compaction",
                    hooks=hooks,
                )
            return await adapter.acomplete(
                AdapterCallRequest(
                    model=model,
                    system_prompt=system,
                    messages=(Message(role="user", content="prior conversation"),),
                    max_tokens=10_000,
                    effort=effort or "",
                    temperature=1.0,
                    tools=(ToolSpec(name="lookup", description="lookup", input_schema={}),),
                    tool_choice="auto",
                    provider_options={
                        "openrouter": {
                            "only": ["openai"],
                            "allow_fallbacks": False,
                            "require_parameters": True,
                            "data_collection": "deny",
                        }
                    },
                )
            )

    result = asyncio.run(run())
    assert len(bodies) == 1
    body = bodies[0]
    assert body["model"] == to_openrouter_model_id(model)
    assert body["max_tokens"] == 10_000
    assert body.get("reasoning", {}).get("effort") == expected_effort
    assert body["session_id"] == "geode-" + hashlib.sha256(b"private-session").hexdigest()
    assert "private-session" not in json.dumps(body)
    assert body["messages"][-1]["role"] == "user"
    if model.startswith("openrouter/anthropic/"):
        assert body["messages"][-1]["content"] == [
            {"type": "text", "text": "prior conversation", "cache_control": {"type": "ephemeral"}}
        ]
    else:
        assert body["messages"][-1]["content"] == "prior conversation"
    if capability == "text":
        assert "temperature" not in body and "tools" not in body and "provider" not in body
    else:
        if model.startswith("openrouter/openai/gpt-6-"):
            # The relay does not advertise Platform's effort=none sampling exception.
            assert "temperature" not in body
        else:
            assert body["temperature"] == 1.0
        assert body["tools"][0]["function"]["name"] == "lookup"
        assert body["tool_choice"] == "auto"
        assert body["provider"] == {
            "only": ["openai"],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        }
    if model == "openrouter/openai/gpt-6-sol":
        assert body["messages"][0]["content"][0] == {
            "type": "text",
            "text": "Stable rules.\n\n",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    assert result.text == "summary"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 13
    assert result.usage.cached_input_tokens == 80
    assert result.usage.cache_write_tokens == 10
    assert result.usage.reasoning_tokens == 3
    assert result.usage.reported_cost_usd == 0.0042
    if capability == "text":
        assert (result.adapter_name, result.adapter_provider, result.adapter_source) == (
            "openrouter-payg",
            "openrouter",
            "payg",
        )
        assert len(rows) == 1
        assert rows[0]["model"] == model
        assert rows[0]["provider"] == "openrouter" and rows[0]["source"] == "payg"
        assert rows[0]["purpose"] == "context_compaction"
        assert rows[0]["effort"] == expected_effort
        assert rows[0]["usage"]["cached_input_tokens"] == 80
        assert rows[0]["cost_usd"] == 0.0042


@pytest.mark.parametrize("model, effort", [("openrouter/openai/gpt-5.5", "max"), ("", "low")])
def test_text_validation_does_not_select_a_direct_provider(
    monkeypatch: pytest.MonkeyPatch, model: str, effort: str
) -> None:
    from unittest.mock import Mock

    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    adapter = OpenRouterPaygAdapter()
    direct = OpenAIPaygAdapter()
    relay_client, direct_client = Mock(), Mock()
    monkeypatch.setattr(adapter, "_get_client", relay_client)
    monkeypatch.setattr(direct, "_get_client", direct_client)
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [direct, adapter])
    with pytest.raises(AdapterDispatchError) as caught:
        asyncio.run(
            complete_text_via_adapters(
                "input",
                model=model,
                effort=effort,
                prefer_provider="openrouter",
                prefer_source="payg",
            )
        )
    assert isinstance(caught.value.__cause__, ValueError)
    if model:
        from core.llm.errors import LLMRequestValidationError, is_request_fatal

        assert isinstance(caught.value.__cause__, LLMRequestValidationError)
        assert is_request_fatal(caught.value.__cause__)
    relay_client.assert_not_called()
    direct_client.assert_not_called()


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("explicit_policy", [True, False])
def test_structured_output_reaches_sdk_with_parameter_enforcement(
    monkeypatch: pytest.MonkeyPatch, strict: bool, explicit_policy: bool
) -> None:
    schema: dict[str, Any] = {
        "title": "verdict",
        "type": "object",
        "properties": {"pass": {"type": "boolean"}},
    }
    if strict:
        schema.update(required=["pass"], additionalProperties=False)
    policy = {"only": ["openai"], "allow_fallbacks": False} if explicit_policy else {}
    bodies: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        # An endpoint rejection remains an error, never an unstructured retry.
        return httpx.Response(400, json={"error": {"message": "unsupported schema"}})

    async def run() -> None:
        from openai import BadRequestError

        async with AsyncOpenAI(
            api_key="fixture",
            max_retries=0,
            base_url="https://openrouter.ai/api/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = OpenRouterPaygAdapter()
            monkeypatch.setattr(adapter, "_get_client", lambda model="": client)
            with pytest.raises(BadRequestError):
                await adapter.acomplete(
                    AdapterCallRequest(
                        model="openrouter/openai/gpt-6-sol",
                        messages=(Message(role="user", content="verify"),),
                        effort="",
                        temperature=1.0,
                        response_schema=schema,
                        provider_options={"openrouter": policy},
                    )
                )

    asyncio.run(run())
    assert len(bodies) == 1
    assert "temperature" not in bodies[0]
    assert bodies[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "verdict", "strict": strict, "schema": schema},
    }
    assert bodies[0]["provider"] == {**policy, "require_parameters": True}
    assert "require_parameters" not in policy


@pytest.mark.parametrize(
    "schema, policy",
    [({"type": "array"}, {}), ({"type": "object"}, {"require_parameters": False})],
)
def test_invalid_schema_or_optional_parameters_fail_before_client(
    monkeypatch: pytest.MonkeyPatch, schema: dict[str, Any], policy: dict[str, Any]
) -> None:
    from unittest.mock import Mock

    from core.llm.errors import LLMRequestValidationError

    adapter = OpenRouterPaygAdapter()
    client = Mock()
    monkeypatch.setattr(adapter, "_get_client", client)
    with pytest.raises(LLMRequestValidationError):
        asyncio.run(
            adapter.acomplete(
                AdapterCallRequest(
                    model="openrouter/openai/gpt-6-sol",
                    messages=(Message(role="user", content="verify"),),
                    response_schema=schema,
                    provider_options={"openrouter": policy},
                )
            )
        )
    client.assert_not_called()


@pytest.mark.parametrize("effort", ["low", "none"])
@pytest.mark.parametrize("temperature", [0.0, 0.5])
def test_unsupported_custom_sampling_is_fatal_before_client(
    monkeypatch: pytest.MonkeyPatch, effort: str, temperature: float
) -> None:
    from unittest.mock import Mock

    from core.llm.errors import LLMRequestValidationError, is_request_fatal

    adapter = OpenRouterPaygAdapter()
    client = Mock()
    monkeypatch.setattr(adapter, "_get_client", client)
    with pytest.raises(LLMRequestValidationError, match="temperature") as caught:
        asyncio.run(
            adapter.acomplete(
                AdapterCallRequest(
                    model="openrouter/openai/gpt-6-sol",
                    messages=(Message(role="user", content="input"),),
                    effort=effort,
                    temperature=temperature,
                )
            )
        )
    assert is_request_fatal(caught.value)
    client.assert_not_called()


def test_nonpositive_text_output_limit_is_fatal_before_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    from core.llm.errors import LLMRequestValidationError, is_request_fatal

    adapter = OpenRouterPaygAdapter()
    client = Mock()
    monkeypatch.setattr(adapter, "_get_client", client)
    with pytest.raises(LLMRequestValidationError) as caught:
        asyncio.run(
            adapter.acomplete_text("input", model="openrouter/openai/gpt-6-sol", max_tokens=0)
        )
    assert is_request_fatal(caught.value)
    client.assert_not_called()

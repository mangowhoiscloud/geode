"""Offline contract tests for the explicit OpenRouter PAYG route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec, UsageSummary
from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter, _openrouter_extra_body
from core.llm.adapters.provider_inference import infer_provider_from_model
from core.llm.providers.openrouter import to_openrouter_model_id
from core.llm.token_tracker import TokenTracker


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
    assert spec.transport.native_capabilities == frozenset()
    assert spec.extra_headers_factory is not None
    assert spec.extra_headers_factory("ignored") == {
        "HTTP-Referer": "https://mangowhoiscloud.github.io/geode/",
        "X-OpenRouter-Title": "GEODE",
        "X-OpenRouter-Metadata": "enabled",
    }


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
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)),
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
    monkeypatch.setattr(adapter, "_get_client", lambda: client)

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

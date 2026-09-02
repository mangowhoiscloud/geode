"""OpenRouter PAYG adapter over the shared Chat Completions transport."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from core.llm.adapters._openai_common import (
    build_async_openai_client,
    build_chat_completion_kwargs,
    translate_chat_response,
)
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    EnvironmentReport,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.providers.openrouter import to_openrouter_model_id

log = logging.getLogger(__name__)

_LIST_POLICY_KEYS = frozenset({"order", "only", "ignore", "quantizations"})
_BOOL_POLICY_KEYS = frozenset(
    {"allow_fallbacks", "require_parameters", "zdr", "enforce_distillable_text"}
)
_POLICY_KEYS = _LIST_POLICY_KEYS | _BOOL_POLICY_KEYS | {"data_collection", "sort"}
_SORT_VALUES = frozenset({"price", "throughput", "latency"})


def _openrouter_extra_body(provider_options: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the bounded V1 routing-policy subset before wire forwarding."""
    raw = provider_options.get("openrouter")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError("provider_options['openrouter'] must be a mapping")
    if unknown := sorted(set(raw) - _POLICY_KEYS):
        raise ValueError(f"unsupported OpenRouter provider option(s): {', '.join(unknown)}")

    policy: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _LIST_POLICY_KEYS:
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
                raise TypeError(f"OpenRouter option {key!r} must be a list of strings")
            items = list(value)
            if not items or any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(f"OpenRouter option {key!r} must contain non-empty strings")
            policy[key] = items
        elif key in _BOOL_POLICY_KEYS:
            if not isinstance(value, bool):
                raise TypeError(f"OpenRouter option {key!r} must be a bool")
            policy[key] = value
        elif key == "data_collection":
            if value not in {"allow", "deny"}:
                raise ValueError("OpenRouter data_collection must be 'allow' or 'deny'")
            policy[key] = value
        elif key == "sort":
            if value not in _SORT_VALUES:
                raise ValueError(
                    "OpenRouter sort must be one of 'price', 'throughput', or 'latency'"
                )
            policy[key] = value
    return {"provider": policy}


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _route_fields(response: Any) -> tuple[str, str, int]:
    metadata = _field(response, "openrouter_metadata")
    if metadata is None and callable(getattr(response, "model_dump", None)):
        metadata = response.model_dump().get("openrouter_metadata")
    if metadata is None:
        return "", "", 0

    selected_provider = ""
    endpoints = _field(metadata, "endpoints")
    available = _field(endpoints, "available") or ()
    if isinstance(available, (list, tuple)):
        for endpoint in available:
            if _field(endpoint, "selected") is True:
                provider = _field(endpoint, "provider")
                selected_provider = provider if isinstance(provider, str) else ""
                break
    strategy = _field(metadata, "strategy")
    attempt = _field(metadata, "attempt")
    return (
        selected_provider,
        strategy if isinstance(strategy, str) else "",
        (
            attempt
            if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0
            else 0
        ),
    )


@dataclass
class OpenRouterPaygAdapter:
    """Explicit OpenRouter identity with no direct-provider equivalence."""

    name: str = "openrouter-payg"
    provider: str = "openrouter"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.CREDITS
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("openrouter-payg"),
        init=False,
        repr=False,
    )

    def _get_client(self) -> Any:
        from core.config import settings
        from core.llm.registry import get_provider_spec

        api_key = settings.openrouter_api_key
        if not api_key:
            raise RuntimeError(
                "OpenRouterPaygAdapter: OPENROUTER_API_KEY not set. "
                "Run `/login add` or set the environment variable."
            )
        spec = get_provider_spec("openrouter")
        if spec is None:
            raise RuntimeError("OpenRouter provider composition is not registered")
        headers = spec.extra_headers_factory(api_key) if spec.extra_headers_factory else None
        return self._clients.get(
            lambda: build_async_openai_client(
                api_key,
                base_url=spec.default_base_url,
                default_headers=headers,
            )
        )

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        model = to_openrouter_model_id(req.model)
        extra_body = _openrouter_extra_body(req.provider_options)
        kwargs = build_chat_completion_kwargs(
            req,
            model=model,
            provider=self.provider,
            adapter_name=self.name,
            extra_body=extra_body,
        )
        try:
            response = await self._get_client().chat.completions.create(**kwargs)
        except Exception as exc:
            log.warning("openrouter-payg: request failed model=%s err=%s", req.model, exc)
            raise
        result = translate_chat_response(response)
        response_provider, routing_strategy, routing_attempt = _route_fields(response)
        return replace(
            result,
            response_provider=response_provider,
            routing_strategy=routing_strategy,
            routing_attempt=routing_attempt,
        )

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings

        if not settings.openrouter_api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("openrouter_api_key", "missing"),),
                hints=("Set OPENROUTER_API_KEY or run `/login add`.",),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("openrouter_api_key", f"set ({len(settings.openrouter_api_key)} chars)"),),
        )


__all__ = ["OpenRouterPaygAdapter"]

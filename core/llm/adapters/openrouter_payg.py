"""OpenRouter PAYG adapter over the shared Chat Completions transport."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from core.llm.adapters._capability_impls import openai_effort_kwargs
from core.llm.adapters._openai_common import (
    _is_openai_strict_compatible,
    build_async_openai_client,
    build_chat_completion_kwargs,
    get_openai_model_spec,
    translate_chat_response,
)
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    EnvironmentReport,
    Message,
    TextCompletionResult,
)
from core.llm.errors import LLMRequestValidationError
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.providers.openrouter import to_openrouter_model_id
from core.llm.strategies.plan_registry import resolve_payg_profile

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
    supports_text_completion: bool = True
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("openrouter-payg"),
        init=False,
        repr=False,
    )

    def _credential(self) -> tuple[str, str, str]:
        """Read the selected PAYG key, endpoint and non-secret provenance."""
        from core.config import settings
        from core.llm.registry import get_provider_spec

        spec = get_provider_spec(self.provider)
        if spec is None:
            raise RuntimeError("PAYG provider composition is not registered")
        base_url = spec.default_base_url
        profile = resolve_payg_profile(self.provider, base_url=base_url)
        if profile is not None:
            return profile.key, base_url, f"auth profile:{profile.name}"
        return settings.openrouter_api_key, base_url, "settings.openrouter_api_key"

    def _get_client(self) -> Any:
        from core.llm.registry import get_provider_spec

        api_key, base_url, _ = self._credential()
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
                base_url=base_url,
                default_headers=headers,
            ),
            identity=hashlib.sha256(f"{base_url}\0{api_key}".encode()).hexdigest(),
        )

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
        effort: str | None = None,
    ) -> TextCompletionResult:
        result = await self.acomplete(
            AdapterCallRequest(
                model=model,
                messages=(Message(role="user", content=prompt),),
                system_prompt=system,
                max_tokens=max_tokens,
                effort=effort or "",
            )
        )
        return TextCompletionResult(text=result.text, usage=result.usage)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        model = to_openrouter_model_id(req.model)
        if req.max_tokens <= 0:
            raise LLMRequestValidationError("OpenRouter max_tokens must be positive")
        extra_body = _openrouter_extra_body(req.provider_options) or {}
        openai_spec = (
            get_openai_model_spec(model.removeprefix("openai/"))
            if model.startswith("openai/")
            else None
        )
        if req.effort and openai_spec and openai_spec.reasoning_effort_values is not None:
            extra_body.update(openai_effort_kwargs(model.removeprefix("openai/"), req.effort))
        if openai_spec and not openai_spec.accepts_temperature:
            if req.temperature not in (None, 1.0):
                raise LLMRequestValidationError(
                    f"OpenRouter temperature is unsupported for {model!r}"
                )
            # The relay does not advertise Platform's effort=none sampling exception.
            # Omit GEODE's default sampling value; preserve the selected effort.
            req = replace(req, temperature=None)
        from core.agent.cognitive_state_ctx import get_session_id

        session_id = req.metadata.get("session_id") or get_session_id()
        if isinstance(session_id, str) and session_id:
            # Remote affinity must follow the logical session, not changing
            # system text or an SDK client's transport lifetime.
            extra_body["session_id"] = "geode-" + hashlib.sha256(session_id.encode()).hexdigest()
        kwargs = build_chat_completion_kwargs(
            req,
            model=model,
            provider=self.provider,
            adapter_name=self.name,
            extra_body=extra_body,
        )
        if req.response_schema is not None:
            if req.response_schema.get("type") != "object" or "anyOf" in req.response_schema:
                raise LLMRequestValidationError(
                    "OpenRouter response_schema requires an object root without anyOf"
                )
            policy = extra_body.setdefault("provider", {})
            if policy.get("require_parameters") is False:
                raise LLMRequestValidationError(
                    "OpenRouter response_schema requires provider.require_parameters=true"
                )
            policy["require_parameters"] = True
            kwargs["extra_body"] = extra_body
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(req.response_schema.get("title") or "response"),
                    "strict": _is_openai_strict_compatible(req.response_schema),
                    "schema": req.response_schema,
                },
            }
        if model.startswith("anthropic/claude-"):
            from core.llm.adapters._anthropic_common import _cache_shaped_system
            from core.llm.providers.anthropic import (
                apply_messages_cache_control,
                validate_cache_controls,
            )

            messages = kwargs["messages"]
            if req.system_prompt:
                messages[0]["content"] = _cache_shaped_system(req.system_prompt)
            # Chat carries the system marker inside messages; reserve only
            # tool slots here to avoid counting the same system marker twice.
            reserved = validate_cache_controls(messages=[], tools=kwargs.get("tools"))
            kwargs["messages"] = apply_messages_cache_control(
                messages, reserved_breakpoints=reserved
            )
            validate_cache_controls(messages=kwargs["messages"], tools=kwargs.get("tools"))
        elif (
            model.startswith("openai/")
            and get_openai_model_spec(model.removeprefix("openai/")).supports_explicit_prompt_cache
        ):
            from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY

            static, boundary, dynamic = req.system_prompt.partition(PROMPT_CACHE_BOUNDARY)
            if boundary and static.strip():
                kwargs["messages"][0]["content"] = [
                    {
                        "type": "text",
                        "text": static,
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    },
                    {"type": "text", "text": boundary + dynamic},
                ]
        try:
            response = await self._get_client().chat.completions.create(**kwargs)
        except Exception as exc:
            log.warning(
                "openrouter-payg: request failed model=%s error_type=%s",
                req.model,
                type(exc).__name__,
            )
            raise
        result = translate_chat_response(
            response, provider=self.provider, adapter_name=self.name, model=model
        )
        response_provider, routing_strategy, routing_attempt = _route_fields(response)
        return replace(
            result,
            response_provider=response_provider,
            routing_strategy=routing_strategy,
            routing_attempt=routing_attempt,
        )

    def test_environment(self) -> EnvironmentReport:
        api_key, _, _ = self._credential()
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("openrouter_api_key", "missing"),),
                hints=("Set OPENROUTER_API_KEY or run `/login add`.",),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("openrouter_api_key", f"set ({len(api_key)} chars)"),),
        )


__all__ = ["OpenRouterPaygAdapter"]

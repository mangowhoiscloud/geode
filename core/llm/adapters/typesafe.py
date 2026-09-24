"""Single-call SystemOne transport and typed Choice admission.

This decision-only adapter is composed by reflection/verification, never offered
as a root text-generation model. Direct TypeSafe and OpenRouter share the public
SystemOne wire contract; billing and route identity remain distinct.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, UsageSummary
from core.llm.registry import AdapterBillingType
from core.observability.redaction import redact_secrets

JEV_MODEL = "jev-1.13.0"
OPENROUTER_JEV_MODEL = "typesafe/jev-1.13"
_ENDPOINTS = {
    "typesafe": "https://api.typesafe.ai/v1/systemone",
    "openrouter": "https://openrouter.ai/api/v1/systemone",
}
_Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class _Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, _Probability]
    confidence: _Probability


def _safe_identifier(value: Any, api_key: SecretStr) -> str:
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value)
        and redact_secrets(value) == value
        and "apikey_" not in value
        and api_key.get_secret_value() not in value
        else ""
    )


def typesafe_request_id(response: httpx.Response, api_key: SecretStr) -> str:
    """Retain only the documented support join key, never arbitrary headers."""
    value = _safe_identifier(response.headers.get("x-typesafe-request-id", ""), api_key)
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) else ""


async def _call_systemone(
    client: httpx.AsyncClient,
    api_key: SecretStr,
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
) -> AdapterCallResult:
    response = await client.post(
        _ENDPOINTS[provider],
        json={**payload, "model": model},
        headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            "TypeSafe request failed" if provider == "typesafe" else "OpenRouter decision failed",
            request=response.request,
            response=response,
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    valid_body = isinstance(body, dict)
    body = body if valid_body else {}
    raw_usage = body.get("usage")
    raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
    counts = {
        key: value if type(value) is int and value >= 0 else None
        for key in ("input_tokens", "output_tokens")
        for value in [raw_usage.get(key)]
    }
    cost = raw_usage.get("cost") if provider == "openrouter" else None
    valid_cost = cost is None or (type(cost) in (int, float) and math.isfinite(cost) and cost >= 0)
    reported_cost = float(cost) if valid_cost and cost is not None else None
    return AdapterCallResult(
        text=json.dumps(body.get("answers")),
        usage=UsageSummary(
            input_tokens=counts["input_tokens"] or 0,
            output_tokens=counts["output_tokens"] or 0,
            input_tokens_present=counts["input_tokens"] is not None,
            output_tokens_present=counts["output_tokens"] is not None,
            reported_cost_usd=reported_cost,
        ),
        stop_reason="end_turn" if valid_body and valid_cost else "invalid_response",
        response_id=(
            typesafe_request_id(response, api_key)
            if provider == "typesafe"
            else _safe_identifier(body.get("id"), api_key)
        ),
        response_model=_safe_identifier(body.get("model"), api_key),
        response_provider=(
            "typesafe"
            if provider == "typesafe"
            else _safe_identifier(body.get("provider"), api_key)
        ),
    )


async def call_typesafe(
    client: httpx.AsyncClient, api_key: SecretStr, payload: dict[str, Any]
) -> AdapterCallResult:
    """Keep the fixed direct-route diagnostic API; observation is caller-owned."""
    return await _call_systemone(client, api_key, payload, provider="typesafe", model=JEV_MODEL)


def parse_choice_answers(
    text: str, questions: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Require all questions, finite normalized probabilities and an argmax choice."""
    answers = json.loads(text)
    if not isinstance(answers, dict) or answers.keys() != questions.keys():
        raise ValueError("decision fields changed")
    primitives = {}
    for key, question in questions.items():
        choice = _Choice.model_validate(answers[key])
        probabilities = choice.probabilities
        if (
            probabilities.keys() != question["criteria"].keys()
            or choice.choice not in probabilities
            or not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-5)
            or probabilities[choice.choice] != max(probabilities.values())
        ):
            raise ValueError("invalid choice distribution")
        primitives[key] = choice.model_dump()
    return primitives


class SystemOneAdapter:
    """Explicit, no-retry decision route with no text/tool-generation capability."""

    source = "payg"
    billing_type = AdapterBillingType.API

    def __init__(
        self, provider: str, api_key: SecretStr, *, client: httpx.AsyncClient | None = None
    ) -> None:
        if provider not in _ENDPOINTS or not api_key.get_secret_value().strip():
            raise ValueError("SystemOne requires a configured decision route")
        self.provider = provider
        self.name = f"{provider}-systemone"
        self.model = JEV_MODEL if provider == "typesafe" else OPENROUTER_JEV_MODEL
        self._api_key = api_key
        # An injected client stays caller-owned, including its event loop and
        # lifetime. Production creates and closes a fresh client for each call.
        self._injected_client = client

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        if (
            request.model != self.model
            or request.tools
            or request.deferred_tool_names
            or request.executable_tool_names
            or request.allowed_tool_names
            or request.tool_choice not in ("none", "auto", {"type": "none"})
            or len(request.messages) != 1
            or request.messages[0].role != "user"
            or not isinstance(request.messages[0].content, str)
        ):
            raise ValueError("SystemOne accepts only a text-only decision request")
        payload = json.loads(request.messages[0].content)
        if (
            not isinstance(payload, dict)
            or payload.keys() != {"state", "questions"}
            or not isinstance(payload["state"], dict)
            or not isinstance(payload["questions"], dict)
            or not payload["questions"]
        ):
            raise ValueError("SystemOne requires explicit state and questions")
        if len(json.dumps(payload, allow_nan=False).encode()) > 65_536:
            raise ValueError("SystemOne decision input exceeds the bounded envelope")
        if self._injected_client is not None:
            result = await _call_systemone(
                self._injected_client,
                self._api_key,
                payload,
                provider=self.provider,
                model=self.model,
            )
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                result = await _call_systemone(
                    client, self._api_key, payload, provider=self.provider, model=self.model
                )
        model_matches = result.response_model == self.model or (
            self.provider == "openrouter"
            and re.fullmatch(re.escape(self.model) + r"-\d{8}", result.response_model) is not None
        )
        if (
            not model_matches
            or result.response_provider.lower() != "typesafe"
            or result.stop_reason != "end_turn"
        ):
            # A completed but inadmissible response still consumed native usage.
            return replace(result, stop_reason="invalid_response")
        return result

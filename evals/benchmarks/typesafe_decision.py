"""Single-call TypeSafe transport and native Choice validation for diagnostics."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

import httpx
from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.observability.redaction import redact_secrets
from pydantic import BaseModel, ConfigDict, Field, SecretStr

JEV_MODEL = "jev-1.13.0"
_Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class _Choice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, _Probability]
    confidence: _Probability


def typesafe_request_id(response: httpx.Response, api_key: SecretStr) -> str:
    """Retain the documented support join key, never arbitrary header text."""
    value = response.headers.get("x-typesafe-request-id", "")
    return (
        value
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)
        and redact_secrets(value) == value
        and "apikey_" not in value
        and api_key.get_secret_value() not in value
        else ""
    )


async def call_typesafe(
    client: httpx.AsyncClient, api_key: SecretStr, payload: dict[str, Any]
) -> AdapterCallResult:
    """Perform one caller-owned request; observation and interpretation stay outside."""
    response = await client.post(
        "https://api.typesafe.ai/v1/systemone",
        json={**payload, "model": JEV_MODEL},
        headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            "TypeSafe request failed", request=response.request, response=response
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
    model = body.get("model")
    model = (
        model
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", model)
        else ""
    )
    return AdapterCallResult(
        text=json.dumps(body.get("answers")),
        usage=UsageSummary(
            input_tokens=counts["input_tokens"] or 0,
            output_tokens=counts["output_tokens"] or 0,
            input_tokens_present=counts["input_tokens"] is not None,
            output_tokens_present=counts["output_tokens"] is not None,
        ),
        stop_reason="end_turn" if valid_body else "invalid_response",
        response_id=typesafe_request_id(response, api_key),
        response_model=model,
        response_provider="typesafe",
    )


def parse_choice_answers(
    text: str, questions: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Require every fixed question, finite normalized probabilities and an argmax choice."""
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

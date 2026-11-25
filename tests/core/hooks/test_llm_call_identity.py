"""v13 ``llm.call.ended`` identity: sent knobs, digests, and route validity."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.hooks.llm_observation import observe_llm_call, route_check
from core.hooks.system import HookEvent
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    UsageSummary,
    sent_params_receipt,
)
from core.observability.activity_registry import map_hook_to_activity
from core.tools.plan import ToolSpec


class _Capture:
    def __init__(self) -> None:
        self.events: list[tuple[HookEvent, dict[str, Any]]] = []

    async def trigger_async(self, event: HookEvent, data: dict[str, Any]) -> None:
        self.events.append((event, dict(data)))


def _request(**overrides: Any) -> AdapterCallRequest:
    values: dict[str, Any] = {
        "model": "gpt-5.5",
        "messages": [Message(role="user", content="hi")],
        "system_prompt": "Mode: test.",
        "tools": (ToolSpec(name="lookup", description="d", input_schema={"type": "object"}),),
        "temperature": 0.0,
        "effort": "high",
    }
    values.update(overrides)
    return AdapterCallRequest(**values)


def test_gpt5_codex_request_records_temperature_as_dropped_not_sent() -> None:
    req = _request()
    receipt = sent_params_receipt(
        req, build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
    )

    assert "temperature" not in receipt["params_sent"]
    # The subscription backend manages output length server-side.
    assert receipt["params_dropped"] == ["max_tokens", "temperature"]
    assert receipt["params_sent"]["reasoning"]["effort"] == "high"
    assert receipt["provider_seed"] == "not-sent"


def test_sent_knobs_and_explicit_seed_are_read_from_the_wire() -> None:
    req = _request(model="gpt-4.1", temperature=0.2)
    receipt = sent_params_receipt(
        req, {"temperature": 0.2, "max_tokens": 10, "seed": 7, "messages": ["body"]}
    )
    assert receipt == {
        "params_sent": {"temperature": 0.2, "max_tokens": 10, "seed": 7},
        "params_dropped": [],
        "provider_seed": 7,
    }


@pytest.mark.parametrize(
    ("requested", "served", "expected"),
    [
        ("gpt-5.5", "gpt-5.5", "match"),
        ("gpt-5.5", "gpt-5.5-2026-01-15", "match"),
        ("claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "match"),
        ("gpt-5.5", "openai/gpt-5.5", "match"),
        ("openai/gpt-5.5", "azure/gpt-5.5", "mismatch"),
        ("gpt-5.5", "gpt-5.5-mini", "mismatch"),
        ("gpt-5.5", "", "unobserved"),
    ],
)
def test_route_check(requested: str, served: str, expected: str) -> None:
    assert route_check(requested, served) == expected


def _result(response_model: str, request: AdapterCallRequest) -> AdapterCallResult:
    return AdapterCallResult(
        text="ok",
        usage=UsageSummary(
            input_tokens=5,
            output_tokens=3,
            input_tokens_present=True,
            output_tokens_present=True,
            reasoning_tokens=2,
            reasoning_tokens_present=True,
        ),
        stop_reason="completed",
        response_id="resp_1",
        response_model=response_model,
        system_fingerprint="fp_abc",
        request_params=sent_params_receipt(request, {"reasoning": {"effort": "high"}}),
    )


def _ended(response_model: str) -> dict[str, Any]:
    hooks = _Capture()
    req = _request()

    async def call() -> AdapterCallResult:
        return _result(response_model, req)

    asyncio.run(
        observe_llm_call(
            call,
            hooks=hooks,  # type: ignore[arg-type]
            correlation={"session_id": "s"},
            model=req.model,
            provider="openai",
            adapter="codex-oauth",
            purpose="agentic_loop",
            request=req,
        )
    )
    [(event, payload)] = [item for item in hooks.events if item[0] is HookEvent.LLM_CALL_ENDED]
    return payload


def test_served_model_substitution_marks_attempt_invalid_in_durable_row() -> None:
    payload = _ended("gpt-5.4")
    assert payload["validity"] == "invalid"
    assert payload["invalid_reason"] == "route_contamination"

    row = map_hook_to_activity(HookEvent.LLM_CALL_ENDED, payload, run_id="r")
    identity = row.details.call_identity  # type: ignore[union-attr]
    assert identity.validity == "invalid"
    assert identity.route_check == "mismatch"
    assert row.details.response_model == "gpt-5.4"  # type: ignore[union-attr]
    assert row.details.usage.reasoning_tokens == 2  # type: ignore[union-attr]


def test_matching_call_keeps_digests_and_knob_receipt_without_bodies() -> None:
    payload = _ended("gpt-5.5")
    row = map_hook_to_activity(HookEvent.LLM_CALL_ENDED, payload, run_id="r")
    identity = row.details.call_identity  # type: ignore[union-attr]

    assert identity.validity == "valid"
    assert identity.system_fingerprint == "fp_abc"
    assert len(identity.system_prompt_sha256) == len(identity.tool_schema_sha256) == 64
    assert identity.temperature_requested == 0.0
    assert identity.params_dropped == ["max_tokens", "temperature"]
    assert "Mode: test." not in str(payload)

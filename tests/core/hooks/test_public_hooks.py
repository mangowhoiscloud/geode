from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, cast

import pytest
from core.hooks import (
    PUBLIC_HOOK_SCHEMA_VERSION,
    HookAction,
    HookCorrelation,
    HookDecision,
    HookInvocation,
    HookName,
    HookRegistry,
    InvalidHookPayloadError,
    public_hook_schema,
)
from jsonschema import Draft202012Validator


def _async_test(func: Callable[[], Awaitable[None]]) -> Callable[[], None]:
    @wraps(func)
    def run() -> None:
        asyncio.run(func())

    return run


def test_public_hook_allowlist_and_current_version_are_explicit() -> None:
    assert [hook.value for hook in HookName] == [
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "SessionStart",
        "SessionEnd",
        "SubagentStart",
        "SubagentStop",
        "PreVerify",
        "PostVerify",
        "Stop",
    ]
    assert PUBLIC_HOOK_SCHEMA_VERSION == "geode.public-hook.v2"


def test_unknown_hook_name_is_rejected() -> None:
    registry = HookRegistry()

    with pytest.raises(ValueError):
        registry.register(cast(HookName, "LLMCallStart"), lambda _invocation: None)


@_async_test
async def test_outcome_attributes_each_decision_to_its_handler() -> None:
    registry = HookRegistry()
    registry.register(
        HookName.USER_PROMPT_SUBMIT,
        lambda _invocation: HookDecision(action=HookAction.CONTINUE),
        name="first",
        priority=10,
    )
    registry.register(
        HookName.USER_PROMPT_SUBMIT,
        lambda _invocation: HookDecision(action=HookAction.CONTINUE),
        name="second",
        priority=20,
    )

    outcome = await registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={"user_input": "hello"},
    )

    assert outcome.decision_sources == ("first", "second")


def test_all_public_hook_schemas_are_generated_and_json_round_trip() -> None:
    schemas = {hook.value: public_hook_schema(hook) for hook in HookName}

    assert len(schemas) == 13
    round_tripped = json.loads(json.dumps(schemas, sort_keys=True))
    assert set(round_tripped) == {hook.value for hook in HookName}
    for schema in round_tripped.values():
        Draft202012Validator.check_schema(schema)


def test_version_one_correlation_schema_remains_byte_compatible() -> None:
    schema = public_hook_schema(
        HookName.PRE_TOOL_USE,
        version="geode.public-hook.v1",
    )
    correlation = schema["properties"]["correlation"]

    assert tuple(correlation["properties"]) == (
        "session_id",
        "turn_id",
        "run_id",
        "session_generation",
        "verify_attempt",
        "tool_call_id",
        "llm_call_id",
        "llm_attempt_id",
    )
    assert correlation["required"] == list(correlation["properties"])
    legacy = dataclasses.asdict(
        HookInvocation(
            name=HookName.PRE_TOOL_USE,
            payload={"tool_name": "ordinary", "arguments": {}},
        )
    )
    legacy["schema_version"] = "geode.public-hook.v1"
    legacy["correlation"].pop("step_id")
    assert list(Draft202012Validator(schema).iter_errors(legacy)) == []


def test_current_invocation_serializes_against_version_two_schema() -> None:
    invocation = HookInvocation(
        name=HookName.PRE_TOOL_USE,
        correlation=HookCorrelation(
            session_id="session-1",
            turn_id="turn-1",
            step_id="turn-1:step-1",
        ),
        payload={"tool_name": "ordinary", "arguments": {}},
    )

    errors = list(
        Draft202012Validator(public_hook_schema(HookName.PRE_TOOL_USE)).iter_errors(
            dataclasses.asdict(invocation)
        )
    )

    assert errors == []


def test_hook_correlation_preserves_version_one_positional_arguments() -> None:
    correlation = HookCorrelation(
        "session-1",
        "turn-1",
        "run-1",
        2,
        3,
        "tool-1",
        "llm-1",
        "attempt-1",
    )

    assert correlation.run_id == "run-1"
    assert correlation.session_generation == 2
    assert correlation.verify_attempt == 3
    assert correlation.tool_call_id == "tool-1"
    assert correlation.llm_call_id == "llm-1"
    assert correlation.llm_attempt_id == "attempt-1"
    assert correlation.step_id == ""


@_async_test
async def test_invalid_public_payload_is_rejected_before_dispatch() -> None:
    registry = HookRegistry()

    with pytest.raises(InvalidHookPayloadError, match="UserPromptSubmit"):
        await registry.invoke(HookName.USER_PROMPT_SUBMIT, payload={})


@_async_test
async def test_unknown_public_payload_field_is_rejected_before_dispatch() -> None:
    registry = HookRegistry()

    with pytest.raises(InvalidHookPayloadError, match="unexpected"):
        await registry.invoke(
            HookName.USER_PROMPT_SUBMIT,
            payload={"user_input": "hello", "unexpected": True},
        )


def test_exported_schema_is_a_defensive_copy() -> None:
    first = public_hook_schema(HookName.USER_PROMPT_SUBMIT)
    first["properties"]["payload"]["properties"].clear()

    second = public_hook_schema(HookName.USER_PROMPT_SUBMIT)

    assert "user_input" in second["properties"]["payload"]["properties"]


@_async_test
async def test_rewrites_compose_sequentially_and_payload_is_redacted() -> None:
    registry = HookRegistry()
    seen: list[dict[str, Any]] = []

    async def first(invocation: Any) -> HookDecision:
        seen.append(dict(invocation.payload))
        return HookDecision(
            action=HookAction.REWRITE,
            updates={"user_input": f"{invocation.payload['user_input']} one"},
        )

    async def second(invocation: Any) -> HookDecision:
        seen.append(dict(invocation.payload))
        return HookDecision(
            action=HookAction.REWRITE,
            updates={"user_input": f"{invocation.payload['user_input']} two"},
        )

    registry.register(HookName.USER_PROMPT_SUBMIT, first, name="first")
    registry.register(HookName.USER_PROMPT_SUBMIT, second, name="second")

    outcome = await registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={
            "user_input": "start",
            "authorization": "Bearer secret",
        },
    )

    assert seen[0]["user_input"] == "start"
    assert seen[1]["user_input"] == "start one"
    assert outcome.invocation.payload["user_input"] == "start one two"
    assert "authorization" not in outcome.invocation.payload
    assert outcome.invocation.payload["_redacted_fields"] == ["authorization"]


@_async_test
async def test_hook_cannot_return_an_action_owned_by_another_hook() -> None:
    registry = HookRegistry()

    async def invalid(_invocation: Any) -> HookDecision:
        return HookDecision(action=HookAction.ACCEPT)

    registry.register(HookName.USER_PROMPT_SUBMIT, invalid, name="invalid")

    outcome = await registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={"user_input": "hello"},
    )

    assert not outcome.decisions
    assert outcome.handler_errors == ("invalid: accept is not allowed for UserPromptSubmit",)


@_async_test
async def test_large_payload_keeps_the_hook_schema_envelope() -> None:
    registry = HookRegistry()

    outcome = await registry.invoke(
        HookName.POST_TOOL_USE,
        payload={
            "tool_name": "check",
            "arguments": {},
            "result": {f"row-{index}": "x" * 4_096 for index in range(20)},
            "has_error": False,
            "executed": True,
        },
    )

    assert set(outcome.invocation.payload) == {
        "tool_name",
        "arguments",
        "result",
        "has_error",
        "executed",
    }
    assert outcome.invocation.payload["result"]["_truncated"] is True
    assert len(json.dumps(outcome.invocation.payload).encode()) <= 32 * 1_024


@_async_test
async def test_handler_payload_mutation_is_isolated_and_rejected() -> None:
    registry = HookRegistry()

    def mutate(invocation: Any) -> None:
        cast(dict[str, Any], invocation.payload)["user_input"] = "mutated"

    registry.register(HookName.USER_PROMPT_SUBMIT, mutate, name="mutator")

    outcome = await registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={"user_input": "original"},
    )

    assert outcome.invocation.payload["user_input"] == "original"
    assert outcome.handler_errors == (
        "mutator: hook handlers cannot mutate invocation.payload; return REWRITE updates",
    )


@_async_test
async def test_non_rewrite_action_cannot_smuggle_payload_updates() -> None:
    registry = HookRegistry()
    registry.register(
        HookName.USER_PROMPT_SUBMIT,
        lambda _invocation: HookDecision(
            action=HookAction.CONTINUE,
            updates={"user_input": "smuggled"},
        ),
        name="smuggler",
    )

    outcome = await registry.invoke(
        HookName.USER_PROMPT_SUBMIT,
        payload={"user_input": "original"},
    )

    assert outcome.invocation.payload["user_input"] == "original"
    assert outcome.handler_errors == ("smuggler: updates are only allowed for rewrite decisions",)


@_async_test
async def test_block_stops_lower_priority_handlers() -> None:
    registry = HookRegistry()
    called: list[str] = []

    async def block(_invocation: Any) -> HookDecision:
        called.append("block")
        return HookDecision(action=HookAction.BLOCK, reason="policy")

    async def late(_invocation: Any) -> None:
        called.append("late")

    registry.register(HookName.PRE_TOOL_USE, late, name="late", priority=200)
    registry.register(HookName.PRE_TOOL_USE, block, name="block", priority=10)

    outcome = await registry.invoke(
        HookName.PRE_TOOL_USE,
        payload={"tool_name": "run_bash", "arguments": {}},
    )

    assert outcome.blocked is True
    assert called == ["block"]


@_async_test
async def test_blocking_sync_handler_is_bounded_off_the_event_loop() -> None:
    registry = HookRegistry()
    handler_started = threading.Event()
    release_handler = threading.Event()

    def blocking(_invocation: Any) -> HookDecision:
        handler_started.set()
        release_handler.wait(timeout=1.0)
        return HookDecision()

    registry.register(
        HookName.USER_PROMPT_SUBMIT,
        blocking,
        name="blocking",
        timeout_s=0.02,
    )

    started = time.monotonic()
    try:
        outcome = await registry.invoke(
            HookName.USER_PROMPT_SUBMIT,
            payload={"user_input": "hello"},
        )
    finally:
        release_handler.set()

    assert handler_started.is_set()
    assert time.monotonic() - started < 0.2
    assert outcome.decisions == ()
    assert len(outcome.handler_errors) == 1
    assert "blocking" in outcome.handler_errors[0]

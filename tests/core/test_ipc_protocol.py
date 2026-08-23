"""Golden compatibility tests for the public CLI IPC envelope."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.ipc_protocol import (
    IPC_EVENT_TYPES,
    IPC_FEATURES,
    IPC_LEGACY_PROTOCOL_VERSION,
    IPC_PROTOCOL_VERSION,
    MAX_IPC_MESSAGE_BYTES,
    IPCProtocolError,
    decode_message,
    encode_message,
    negotiate_protocol,
    validate_client_message,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "protocol"


def test_legacy_and_current_greetings_negotiate_from_golden_fixtures() -> None:
    legacy = decode_message((_FIXTURES / "ipc-v0-session.json").read_bytes())
    current = decode_message((_FIXTURES / "ipc-v1-session.json").read_bytes())

    assert negotiate_protocol(legacy.get("protocol_version"), legacy.get("features")) == (
        IPC_LEGACY_PROTOCOL_VERSION,
        (),
    )
    assert negotiate_protocol(current["protocol_version"], current["features"]) == (
        IPC_PROTOCOL_VERSION,
        IPC_FEATURES,
    )
    assert current["future_field"] == {"kept": True}


def test_future_protocol_version_fails_loud() -> None:
    with pytest.raises(IPCProtocolError, match="Unsupported IPC protocol"):
        negotiate_protocol("geode.ipc.v2", IPC_FEATURES)


def test_json_round_trip_preserves_unknown_fields() -> None:
    message = {
        "type": "prompt",
        "request_id": "request-1",
        "text": "hello",
        "future_field": [1, 2, 3],
    }

    assert decode_message(encode_message(message).rstrip(b"\n")) == message


@pytest.mark.parametrize(
    "payload",
    [b"[]", b"not-json", b'{"type":""}', b'{"type":"prompt","features":"bad"}'],
)
def test_invalid_envelopes_fail_loud(payload: bytes) -> None:
    with pytest.raises(IPCProtocolError):
        decode_message(payload)


def test_oversized_message_fails_before_transport() -> None:
    with pytest.raises(IPCProtocolError, match="exceeds"):
        encode_message({"type": "prompt", "text": "x" * MAX_IPC_MESSAGE_BYTES})


def test_known_payload_fields_are_typed_but_unknown_fields_are_allowed() -> None:
    validate_client_message({"type": "prompt", "text": "hello", "future_field": 1})
    validate_client_message({"type": "future_request", "anything": object()})

    with pytest.raises(IPCProtocolError, match="invalid type"):
        validate_client_message({"type": "prompt", "text": 42})


def test_public_event_vocabulary_is_exact() -> None:
    assert IPC_EVENT_TYPES == (
        "tool_start",
        "tool_end",
        "fast_chat_start",
        "tokens",
        "round_start",
        "thinking_start",
        "thinking_end",
        "turn_end",
        "context_event",
        "subagent_dispatch",
        "subagent_progress",
        "subagent_complete",
        "subagent_state",
        "session_cost",
        "model_switch_required",
        "cost_budget_exceeded",
        "time_budget_expired",
        "convergence_detected",
        "repeated_success_no_progress",
        "goal_decomposition",
        "progress_plan",
        "plan_step",
        "replan",
        "tool_backpressure",
        "tool_diversity_forced",
        "model_switched",
        "checkpoint_saved",
        "oauth_login_started",
        "oauth_login_pending",
        "oauth_login_success",
        "oauth_login_failed",
        "billing_error",
        "quota_exhausted",
        "llm_retry",
        "llm_error",
        "retry_wait",
        "budget_warning",
        "reasoning_summary",
        "pipeline_header",
        "pipeline_gather",
        "pipeline_analysis",
        "pipeline_evaluation",
        "pipeline_score",
        "pipeline_verification",
        "pipeline_result",
        "feedback_loop",
        "node_skipped",
    )

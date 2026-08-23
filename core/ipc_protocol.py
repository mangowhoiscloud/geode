"""Versioned, bounded wire contract for the local CLI IPC socket."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from core.unicode_safety import sanitize_jsonable

IPC_PROTOCOL_VERSION = "geode.ipc.v1"
IPC_LEGACY_PROTOCOL_VERSION = "geode.ipc.v0"
IPC_FEATURES = (
    "bounded_json",
    "request_correlation",
    "stable_events",
)
MAX_IPC_MESSAGE_BYTES = 1024 * 1024

# This is the public streaming vocabulary. Internal RuntimeEvent/HookEvent
# additions do not expand it automatically.
IPC_EVENT_TYPES = (
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
IPC_CONTROL_TYPES = frozenset({"ack", "exit_ack"})
_CLIENT_FIELD_TYPES: dict[str, dict[str, type[Any] | tuple[type[Any], ...]]] = {
    "prompt": {"text": str},
    "command": {"cmd": str, "args": str},
    "command_stream": {"cmd": str, "args": str},
    "resume": {"session_id": str, "continue": bool},
    "client_capability": {
        "is_tty": bool,
        "width": (int, str),
        "model": str,
        "cwd": str,
        "dangerously_skip_permissions": bool,
    },
    "approval_response": {"decision": str, "approval_id": str},
    "exit": {},
}


class IPCProtocolError(ValueError):
    """A wire message violates the negotiated IPC contract."""


def new_request_id() -> str:
    """Return an opaque request correlation identifier."""
    return uuid.uuid4().hex


def encode_message(message: Mapping[str, Any]) -> bytes:
    """Encode one bounded line-delimited JSON object."""
    _validate_envelope(message)
    encoded = (
        json.dumps(sanitize_jsonable(dict(message)), ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_IPC_MESSAGE_BYTES:
        raise IPCProtocolError(
            f"IPC message exceeds {MAX_IPC_MESSAGE_BYTES} bytes ({len(encoded)} bytes)"
        )
    return encoded


def decode_message(data: bytes) -> dict[str, Any]:
    """Decode one bounded envelope while preserving unknown fields."""
    if len(data) > MAX_IPC_MESSAGE_BYTES:
        raise IPCProtocolError(
            f"IPC message exceeds {MAX_IPC_MESSAGE_BYTES} bytes ({len(data)} bytes)"
        )
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IPCProtocolError("Invalid IPC JSON") from exc
    if not isinstance(decoded, dict):
        raise IPCProtocolError("IPC message must be a JSON object")
    _validate_envelope(decoded)
    return decoded


def negotiate_protocol(
    peer_version: object,
    peer_features: object,
) -> tuple[str, tuple[str, ...]]:
    """Negotiate the current protocol or the field-less legacy envelope."""
    if peer_version in (None, ""):
        return IPC_LEGACY_PROTOCOL_VERSION, ()
    if peer_version != IPC_PROTOCOL_VERSION:
        raise IPCProtocolError(f"Unsupported IPC protocol version: {peer_version!r}")
    offered = _validate_features(peer_features)
    return IPC_PROTOCOL_VERSION, tuple(feature for feature in IPC_FEATURES if feature in offered)


def validate_client_message(message: Mapping[str, Any]) -> None:
    """Validate known request fields; unknown fields and message types stay forward-compatible."""
    expected = _CLIENT_FIELD_TYPES.get(str(message.get("type", "")))
    if expected is None:
        return
    for field_name, field_type in expected.items():
        if field_name not in message:
            continue
        if not isinstance(message[field_name], field_type):
            raise IPCProtocolError(
                f"IPC field {field_name!r} has invalid type for {message['type']!r}"
            )


def _validate_envelope(message: Mapping[str, Any]) -> None:
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type or len(message_type) > 64:
        raise IPCProtocolError("IPC message type must be a non-empty string of at most 64 chars")
    request_id = message.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id or len(request_id) > 128
    ):
        raise IPCProtocolError("IPC request_id must be a non-empty string of at most 128 chars")
    protocol_version = message.get("protocol_version")
    if protocol_version is not None and (
        not isinstance(protocol_version, str) or len(protocol_version) > 64
    ):
        raise IPCProtocolError("IPC protocol_version must be a string of at most 64 chars")
    if "features" in message:
        _validate_features(message["features"])


def _validate_features(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IPCProtocolError("IPC features must be a list of strings")
    features: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 64:
            raise IPCProtocolError(
                "IPC feature names must be non-empty strings of at most 64 chars"
            )
        features.add(item)
    if len(features) > 64:
        raise IPCProtocolError("IPC features exceed the 64-item limit")
    return frozenset(features)


__all__ = [
    "IPC_CONTROL_TYPES",
    "IPC_EVENT_TYPES",
    "IPC_FEATURES",
    "IPC_LEGACY_PROTOCOL_VERSION",
    "IPC_PROTOCOL_VERSION",
    "MAX_IPC_MESSAGE_BYTES",
    "IPCProtocolError",
    "decode_message",
    "encode_message",
    "negotiate_protocol",
    "new_request_id",
    "validate_client_message",
]

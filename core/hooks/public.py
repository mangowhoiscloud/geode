"""Stable, bounded public hook contracts.

The public surface is deliberately smaller than the internal runtime-event
vocabulary. Handlers receive JSON-safe, secret-redacted data and may return
only the actions allowed for the selected :class:`HookName`.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from core.hooks.system import RuntimeEvent, RuntimeEventBus
from core.observability.redaction import redact_secrets

log = logging.getLogger(__name__)

PUBLIC_HOOK_SCHEMA_VERSION = "geode.public-hook.v1"
PUBLIC_HOOK_DEFAULT_TIMEOUT_S = 10.0
_MAX_STRING_CHARS = 4_096
_MAX_PAYLOAD_BYTES = 32 * 1_024
_MAX_COLLECTION_ITEMS = 64
_MAX_DEPTH = 8
_EVIDENCE_KINDS = frozenset(
    {"runtime_event", "sil_eval", "crucible_evidence", "native_receipt", "legacy"}
)
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "base64",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "headers",
        "password",
        "private_key",
        "raw_request",
        "refresh_token",
        "screenshot",
        "secret",
        "token",
    }
)


class HookName(StrEnum):
    """The complete version-one public hook allowlist."""

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    PERMISSION_REQUEST = "PermissionRequest"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"
    PRE_VERIFY = "PreVerify"
    POST_VERIFY = "PostVerify"
    STOP = "Stop"


class HookAction(StrEnum):
    """Typed decisions understood by public hook owners."""

    CONTINUE = "continue"
    REWRITE = "rewrite"
    BLOCK = "block"
    REQUEST_PERMISSION = "request_permission"
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    ADD_CONTEXT = "add_context"
    DEFER = "defer"
    STRENGTHEN = "strengthen"
    ACCEPT = "accept"
    REVISE = "revise"
    ESCALATE = "escalate"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class HookEvidenceReference:
    """Typed join from a verification decision to external authority."""

    kind: str
    schema_id: str
    authority: str
    reference: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "schema_id": self.schema_id,
            "authority": self.authority,
            "reference": self.reference,
        }


_ALLOWED_ACTIONS: dict[HookName, frozenset[HookAction]] = {
    HookName.USER_PROMPT_SUBMIT: frozenset(
        {HookAction.CONTINUE, HookAction.REWRITE, HookAction.BLOCK}
    ),
    HookName.PRE_TOOL_USE: frozenset(
        {
            HookAction.CONTINUE,
            HookAction.REWRITE,
            HookAction.BLOCK,
            HookAction.REQUEST_PERMISSION,
        }
    ),
    HookName.PERMISSION_REQUEST: frozenset({HookAction.ALLOW, HookAction.DENY, HookAction.ASK}),
    HookName.POST_TOOL_USE: frozenset(
        {HookAction.CONTINUE, HookAction.ADD_CONTEXT, HookAction.BLOCK}
    ),
    HookName.PRE_COMPACT: frozenset({HookAction.CONTINUE, HookAction.REWRITE, HookAction.DEFER}),
    HookName.POST_COMPACT: frozenset({HookAction.CONTINUE}),
    HookName.SESSION_START: frozenset({HookAction.CONTINUE}),
    HookName.SESSION_END: frozenset({HookAction.CONTINUE}),
    HookName.SUBAGENT_START: frozenset({HookAction.CONTINUE}),
    HookName.SUBAGENT_STOP: frozenset({HookAction.CONTINUE}),
    HookName.PRE_VERIFY: frozenset({HookAction.CONTINUE, HookAction.STRENGTHEN}),
    HookName.POST_VERIFY: frozenset({HookAction.ACCEPT, HookAction.REVISE, HookAction.ESCALATE}),
    HookName.STOP: frozenset({HookAction.FINALIZE, HookAction.CONTINUE}),
}


class DuplicateHookError(ValueError):
    """Raised when a public hook name would be replaced accidentally."""


class InvalidHookDecisionError(ValueError):
    """Raised when a handler returns authority its hook does not own."""


class InvalidHookPayloadError(ValueError):
    """Raised when a public hook input violates its versioned schema."""


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_NUMBER = {"type": "number"}
_BOOLEAN = {"type": "boolean"}
_OBJECT = {"type": "object"}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_EVIDENCE_REFERENCE = {
    "type": "object",
    "properties": {
        "kind": {"enum": sorted(_EVIDENCE_KINDS)},
        "schema_id": _STRING,
        "authority": _STRING,
        "reference": _STRING,
    },
    "required": ["kind", "schema_id", "authority", "reference"],
    "additionalProperties": False,
}
_EVIDENCE_REFERENCE_ARRAY = {
    "type": "array",
    "items": _EVIDENCE_REFERENCE,
    "maxItems": 32,
}
_VERIFY_PROPERTIES: dict[str, dict[str, Any]] = {
    "passed": _BOOLEAN,
    "mode": _STRING,
    "effective_mode": _STRING,
    "score": _NUMBER,
    "rubric_misses": _STRING_ARRAY,
    "should_retry": _BOOLEAN,
    "termination_reason": _STRING,
    "rounds": _INTEGER,
    "tool_call_count": _INTEGER,
    "candidate_summary": _STRING,
}
_PAYLOAD_SCHEMAS: dict[HookName, dict[str, Any]] = {
    HookName.USER_PROMPT_SUBMIT: {
        "properties": {"user_input": _STRING},
        "required": ["user_input"],
    },
    HookName.PRE_TOOL_USE: {
        "properties": {"tool_name": _STRING, "arguments": _OBJECT},
        "required": ["tool_name", "arguments"],
    },
    HookName.PERMISSION_REQUEST: {
        "properties": {
            "tool_name": _STRING,
            "safety_level": _STRING,
            "detail": _STRING,
        },
        "required": ["tool_name", "safety_level", "detail"],
    },
    HookName.POST_TOOL_USE: {
        "properties": {
            "tool_name": _STRING,
            "arguments": _OBJECT,
            "result": _OBJECT,
            "has_error": _BOOLEAN,
            "executed": _BOOLEAN,
        },
        "required": ["tool_name", "arguments", "result", "has_error", "executed"],
    },
    HookName.PRE_COMPACT: {
        "properties": {
            "model": _STRING,
            "provider": _STRING,
            "message_count": _INTEGER,
            "keep_recent": _INTEGER,
            "trigger": _STRING,
            "hard": _BOOLEAN,
        },
        "required": [
            "model",
            "provider",
            "message_count",
            "keep_recent",
            "trigger",
            "hard",
        ],
    },
    HookName.POST_COMPACT: {
        "properties": {
            "model": _STRING,
            "provider": _STRING,
            "original_message_count": _INTEGER,
            "new_message_count": _INTEGER,
            "keep_recent": _INTEGER,
            "trigger": _STRING,
            "persisted": _BOOLEAN,
        },
        "required": [
            "model",
            "provider",
            "original_message_count",
            "new_message_count",
            "keep_recent",
            "trigger",
            "persisted",
        ],
    },
    HookName.SESSION_START: {
        "properties": {
            "model": _STRING,
            "provider": _STRING,
            "resumed": _BOOLEAN,
            "status": _STRING,
        },
        "required": ["model", "provider", "resumed", "status"],
    },
    HookName.SESSION_END: {
        "properties": {"reason": _STRING, "status": _STRING},
        "required": ["reason", "status"],
    },
    HookName.SUBAGENT_START: {
        "properties": {
            "task_id": _STRING,
            "task_type": _STRING,
            "description": _STRING,
            "child_session_key": _STRING,
            "parent_session_key": _STRING,
        },
        "required": [
            "task_id",
            "task_type",
            "description",
            "child_session_key",
            "parent_session_key",
        ],
    },
    HookName.SUBAGENT_STOP: {
        "properties": {
            "task_id": _STRING,
            "task_type": _STRING,
            "success": _BOOLEAN,
            "status": _STRING,
            "duration_ms": _NUMBER,
            "error": _STRING,
            "child_session_key": _STRING,
        },
        "required": [
            "task_id",
            "task_type",
            "success",
            "status",
            "duration_ms",
            "error",
            "child_session_key",
        ],
    },
    HookName.PRE_VERIFY: {
        "properties": _VERIFY_PROPERTIES,
        "required": [
            "termination_reason",
            "rounds",
            "tool_call_count",
            "candidate_summary",
        ],
    },
    HookName.POST_VERIFY: {
        "properties": _VERIFY_PROPERTIES,
        "required": [
            "passed",
            "mode",
            "score",
            "rubric_misses",
            "termination_reason",
            "rounds",
            "tool_call_count",
            "candidate_summary",
        ],
    },
    HookName.STOP: {
        "properties": {
            **_VERIFY_PROPERTIES,
            "policy_action": _STRING,
            "evidence_refs": _EVIDENCE_REFERENCE_ARRAY,
        },
        "required": [
            "passed",
            "mode",
            "score",
            "rubric_misses",
            "termination_reason",
            "rounds",
            "tool_call_count",
            "candidate_summary",
            "policy_action",
            "evidence_refs",
        ],
    },
}


def public_hook_schema(hook: HookName) -> dict[str, Any]:
    """Generate the stable JSON Schema for one public hook envelope."""
    resolved = HookName(hook)
    payload = _PAYLOAD_SCHEMAS[resolved]
    return copy.deepcopy(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://geode.dev/schemas/hooks/v1/{resolved.value}.json",
            "title": resolved.value,
            "type": "object",
            "properties": {
                "schema_version": {"const": PUBLIC_HOOK_SCHEMA_VERSION},
                "name": {"const": resolved.value},
                "correlation": {
                    "type": "object",
                    "properties": {
                        "session_id": _STRING,
                        "turn_id": _STRING,
                        "run_id": _STRING,
                        "session_generation": _INTEGER,
                        "verify_attempt": _INTEGER,
                        "tool_call_id": _STRING,
                        "llm_call_id": _STRING,
                        "llm_attempt_id": _STRING,
                    },
                    "required": [
                        "session_id",
                        "turn_id",
                        "run_id",
                        "session_generation",
                        "verify_attempt",
                        "tool_call_id",
                        "llm_call_id",
                        "llm_attempt_id",
                    ],
                    "additionalProperties": False,
                },
                "payload": {
                    "type": "object",
                    "properties": {
                        **payload["properties"],
                        "_redacted_fields": _STRING_ARRAY,
                    },
                    "required": payload["required"],
                    "additionalProperties": False,
                },
                "decision": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "enum": sorted(action.value for action in _ALLOWED_ACTIONS[resolved])
                        },
                        "reason": _STRING,
                        "updates": _OBJECT,
                        "instruction": _STRING,
                        "additional_misses": _STRING_ARRAY,
                        "evidence_refs": _EVIDENCE_REFERENCE_ARRAY,
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
            "required": ["schema_version", "name", "correlation", "payload"],
            "additionalProperties": False,
        }
    )


@dataclass(frozen=True, slots=True)
class HookCorrelation:
    """Stable identifiers shared by in-process and external hook bridges."""

    session_id: str = ""
    turn_id: str = ""
    run_id: str = ""
    session_generation: int = 0
    verify_attempt: int = 0
    tool_call_id: str = ""
    llm_call_id: str = ""
    llm_attempt_id: str = ""


@dataclass(frozen=True, slots=True)
class HookInvocation:
    """One bounded public hook invocation."""

    name: HookName
    correlation: HookCorrelation = field(default_factory=HookCorrelation)
    payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PUBLIC_HOOK_SCHEMA_VERSION

    def with_payload(self, payload: Mapping[str, Any]) -> HookInvocation:
        return replace(self, payload=_sanitize_payload(payload))


@dataclass(frozen=True, slots=True)
class HookDecision:
    """A public hook's typed, bounded response."""

    action: HookAction = HookAction.CONTINUE
    reason: str = ""
    updates: Mapping[str, Any] = field(default_factory=dict)
    instruction: str = ""
    additional_misses: tuple[str, ...] = ()
    evidence_refs: tuple[HookEvidenceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class HookOutcome:
    """Composed result of all handlers registered for one public hook."""

    invocation: HookInvocation
    decisions: tuple[HookDecision, ...] = ()
    handler_errors: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return any(
            decision.action in {HookAction.BLOCK, HookAction.DENY} for decision in self.decisions
        )


HookHandler = Callable[
    [HookInvocation],
    HookDecision | None | Awaitable[HookDecision | None],
]


@dataclass(frozen=True, slots=True)
class _RegisteredHook:
    handler: HookHandler
    name: str
    priority: int
    timeout_s: float


class HookRegistry:
    """Register and invoke only the 13 versioned public hook contracts."""

    def __init__(self, *, events: RuntimeEventBus | None = None) -> None:
        self._events = events
        self._handlers: dict[HookName, list[_RegisteredHook]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        hook: HookName,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout_s: float | None = None,
    ) -> None:
        resolved = HookName(hook)
        handler_name = name or str(getattr(handler, "__name__", type(handler).__name__))
        resolved_timeout = (
            PUBLIC_HOOK_DEFAULT_TIMEOUT_S if timeout_s is None else max(0.0, timeout_s)
        )
        entry = _RegisteredHook(handler, handler_name, priority, resolved_timeout)
        with self._lock:
            registered = self._handlers.setdefault(resolved, [])
            if any(item.name == handler_name for item in registered):
                raise DuplicateHookError(
                    f"Hook {handler_name!r} is already registered for {resolved.value}"
                )
            registered.append(entry)
            registered.sort(key=lambda item: item.priority)

    def unregister(self, hook: HookName, name: str) -> bool:
        resolved = HookName(hook)
        with self._lock:
            registered = self._handlers.get(resolved, [])
            remaining = [item for item in registered if item.name != name]
            if len(remaining) == len(registered):
                return False
            if remaining:
                self._handlers[resolved] = remaining
            else:
                self._handlers.pop(resolved, None)
            return True

    def list_hooks(self) -> dict[str, list[str]]:
        with self._lock:
            return {
                hook.value: [item.name for item in handlers]
                for hook, handlers in self._handlers.items()
            }

    async def invoke(
        self,
        hook: HookName,
        *,
        payload: Mapping[str, Any] | None = None,
        correlation: HookCorrelation | None = None,
    ) -> HookOutcome:
        """Invoke handlers sequentially and compose permitted rewrites."""
        resolved = HookName(hook)
        sanitized_payload = _sanitize_payload(payload or {})
        self._validate_payload(resolved, sanitized_payload)
        invocation = HookInvocation(
            name=resolved,
            correlation=correlation or HookCorrelation(),
            payload=sanitized_payload,
        )
        with self._lock:
            handlers = tuple(self._handlers.get(resolved, ()))

        decisions: list[HookDecision] = []
        errors: list[str] = []
        for handler in handlers:
            started = time.monotonic()
            outcome = "ok"
            reason = ""
            try:
                # A frozen dataclass does not freeze nested dicts. Give every
                # handler an isolated payload and reject in-place mutation so
                # later policy handlers only observe attributed REWRITE
                # decisions.
                handler_invocation = invocation.with_payload(invocation.payload)
                payload_before = _payload_fingerprint(handler_invocation.payload)
                decision = await self._call(handler, handler_invocation)
                if _payload_fingerprint(handler_invocation.payload) != payload_before:
                    raise InvalidHookDecisionError(
                        "hook handlers cannot mutate invocation.payload; return REWRITE updates"
                    )
                if decision is None:
                    decision = HookDecision()
                self._validate_decision(resolved, decision)
                decision = _sanitize_decision(decision)
                if decision.action is HookAction.REWRITE:
                    updated_invocation = invocation.with_payload(
                        {**dict(invocation.payload), **dict(decision.updates)}
                    )
                    self._validate_payload(resolved, updated_invocation.payload)
                    invocation = updated_invocation
                decisions.append(decision)
                reason = decision.reason
                if decision.action in {HookAction.BLOCK, HookAction.DENY}:
                    outcome = decision.action.value
                    break
            except Exception as exc:
                outcome = "error"
                reason = type(exc).__name__
                errors.append(f"{handler.name}: {exc}")
            finally:
                await self._record_invocation(
                    hook=resolved,
                    extension=handler.name,
                    outcome=outcome,
                    reason=reason,
                    duration_ms=(time.monotonic() - started) * 1_000,
                    correlation=invocation.correlation,
                )
        return HookOutcome(invocation, tuple(decisions), tuple(errors))

    @staticmethod
    async def _call(handler: _RegisteredHook, invocation: HookInvocation) -> HookDecision | None:
        async def run() -> HookDecision | None:
            # A synchronous extension must not own the runtime event-loop
            # thread. ``to_thread`` also propagates ContextVars. Calling an
            # async function there only creates its coroutine object; the
            # coroutine itself is still awaited and cancelled on this loop.
            value = await asyncio.to_thread(handler.handler, invocation)
            if inspect.isawaitable(value):
                return await value
            return value

        if handler.timeout_s <= 0:
            return await run()
        return await asyncio.wait_for(run(), timeout=handler.timeout_s)

    @staticmethod
    def _validate_decision(hook: HookName, decision: HookDecision) -> None:
        if not isinstance(decision, HookDecision):
            raise InvalidHookDecisionError(
                f"{hook.value} handler returned {type(decision).__name__}, expected HookDecision"
            )
        if decision.action not in _ALLOWED_ACTIONS[hook]:
            raise InvalidHookDecisionError(
                f"{decision.action.value} is not allowed for {hook.value}"
            )
        if decision.action is HookAction.REWRITE and not decision.updates:
            raise InvalidHookDecisionError("rewrite requires non-empty updates")
        if decision.action is not HookAction.REWRITE and decision.updates:
            raise InvalidHookDecisionError("updates are only allowed for rewrite decisions")
        if (
            hook is HookName.POST_VERIFY
            and decision.action is HookAction.REVISE
            and not decision.instruction.strip()
        ):
            raise InvalidHookDecisionError("PostVerify revise requires an instruction")
        if (
            hook is HookName.STOP
            and decision.action is HookAction.CONTINUE
            and not decision.instruction.strip()
        ):
            raise InvalidHookDecisionError("Stop continue requires an instruction")

    @staticmethod
    def _validate_payload(hook: HookName, payload: Mapping[str, Any]) -> None:
        from jsonschema import Draft202012Validator

        errors = sorted(
            Draft202012Validator(
                {
                    "type": "object",
                    "properties": {
                        **_PAYLOAD_SCHEMAS[hook]["properties"],
                        "_redacted_fields": _STRING_ARRAY,
                    },
                    "required": _PAYLOAD_SCHEMAS[hook]["required"],
                    "additionalProperties": False,
                }
            ).iter_errors(payload),
            key=lambda error: tuple(str(part) for part in error.path),
        )
        if errors:
            raise InvalidHookPayloadError(f"Invalid {hook.value} payload: {errors[0].message}")

    async def _record_invocation(
        self,
        *,
        hook: HookName,
        extension: str,
        outcome: str,
        reason: str,
        duration_ms: float,
        correlation: HookCorrelation,
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.emit_async(
                RuntimeEvent.EXTENSION_INVOKED,
                {
                    "surface": "hook",
                    "name": hook.value,
                    "extension": extension,
                    "status": outcome,
                    "reason": redact_secrets(reason)[:512],
                    "duration_ms": round(duration_ms, 3),
                    "session_id": correlation.session_id,
                    "turn_id": correlation.turn_id,
                    "run_id": correlation.run_id,
                    "session_generation": correlation.session_generation,
                    "verify_attempt": correlation.verify_attempt,
                    "tool_call_id": correlation.tool_call_id,
                    "llm_call_id": correlation.llm_call_id,
                    "llm_attempt_id": correlation.llm_attempt_id,
                },
            )
        except Exception:
            log.warning(
                "Public hook invocation telemetry failed for %s/%s",
                hook.value,
                extension,
                exc_info=True,
            )


def _sanitize_decision(decision: HookDecision) -> HookDecision:
    return replace(
        decision,
        reason=redact_secrets(decision.reason)[:1_024],
        instruction=redact_secrets(decision.instruction)[:_MAX_STRING_CHARS],
        updates=_sanitize_payload(decision.updates),
        additional_misses=tuple(str(item)[:128] for item in decision.additional_misses[:32]),
        evidence_refs=tuple(
            _normalize_evidence_reference(item) for item in decision.evidence_refs[:32]
        ),
    )


def _normalize_evidence_reference(value: Any) -> HookEvidenceReference:
    if isinstance(value, HookEvidenceReference):
        raw = value.as_dict()
    elif isinstance(value, Mapping):
        raw = dict(value)
    elif isinstance(value, str):
        raw = {
            "kind": "legacy",
            "schema_id": "geode.hook-evidence-handle@1",
            "authority": "public hook extension",
            "reference": value,
        }
    else:
        raise InvalidHookDecisionError(
            f"unsupported evidence reference type: {type(value).__name__}"
        )
    kind = str(raw.get("kind") or "")
    if kind not in _EVIDENCE_KINDS:
        raise InvalidHookDecisionError(f"unsupported evidence reference kind: {kind!r}")
    fields = {
        key: redact_secrets(str(raw.get(key) or ""))[:512]
        for key in ("kind", "schema_id", "authority", "reference")
    }
    if any(not fields[key] for key in fields):
        raise InvalidHookDecisionError("evidence reference fields must be non-empty")
    return HookEvidenceReference(**fields)


def _sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_value(payload, depth=0)
    result = sanitized if isinstance(sanitized, dict) else {"value": sanitized}
    if _json_size(result) <= _MAX_PAYLOAD_BYTES:
        return result

    # Keep the hook-specific top-level envelope intact: replacing the whole
    # payload with a truncation marker would remove required schema fields
    # after a tool side effect has already completed. Bound each field while
    # preserving its JSON type instead.
    field_budget = max(512, _MAX_PAYLOAD_BYTES // max(1, len(result)))
    bounded = {key: _bound_json_value(value, field_budget) for key, value in result.items()}
    while _json_size(bounded) > _MAX_PAYLOAD_BYTES and field_budget > 128:
        field_budget //= 2
        bounded = {key: _bound_json_value(value, field_budget) for key, value in result.items()}
    if _json_size(bounded) > _MAX_PAYLOAD_BYTES:
        bounded = {key: _minimal_json_value(value) for key, value in result.items()}
    return bounded


def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _bound_json_value(value: Any, budget: int) -> Any:
    if _json_size(value) <= budget:
        return value
    if isinstance(value, str):
        suffix = "…[truncated]"
        raw_budget = max(0, budget - len(json.dumps(suffix).encode("utf-8")) - 2)
        raw = value.encode("utf-8")[:raw_budget]
        while raw:
            try:
                prefix = raw.decode("utf-8")
                break
            except UnicodeDecodeError:
                raw = raw[:-1]
        else:
            prefix = ""
        return prefix + suffix
    if isinstance(value, dict):
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        summary: dict[str, Any] = {
            "_truncated": True,
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "keys": [],
        }
        for key in value:
            candidate = {**summary, "keys": [*summary["keys"], str(key)[:128]]}
            if _json_size(candidate) > budget:
                break
            summary = candidate
        return summary
    if isinstance(value, list):
        bounded_items: list[Any] = []
        item_budget = max(32, budget // max(1, min(len(value), _MAX_COLLECTION_ITEMS)))
        for item in value[:_MAX_COLLECTION_ITEMS]:
            list_candidate = [*bounded_items, _bound_json_value(item, item_budget)]
            if _json_size(list_candidate) > budget:
                break
            bounded_items = list_candidate
        return bounded_items
    return value


def _minimal_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return ""
    if isinstance(value, dict):
        return {}
    if isinstance(value, list):
        return []
    return value


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return {"_truncated": "max_depth"}
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, str):
        redacted = redact_secrets(value)
        if len(redacted) <= _MAX_STRING_CHARS:
            return redacted
        return redacted[:_MAX_STRING_CHARS] + f"…[truncated:{len(redacted) - _MAX_STRING_CHARS}]"
    if isinstance(value, bytes | bytearray | memoryview):
        return {"_omitted_type": "bytes", "size": len(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        redacted_fields: list[str] = []
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= _MAX_COLLECTION_ITEMS:
                result["_truncated_items"] = len(value) - _MAX_COLLECTION_ITEMS
                break
            key = str(raw_key)[:128]
            if key.lower() in _SECRET_KEYS:
                redacted_fields.append(key)
                continue
            result[key] = _sanitize_value(item, depth=depth + 1)
        if redacted_fields:
            result["_redacted_fields"] = sorted(redacted_fields)
        return result
    if isinstance(value, (list, tuple)):
        items = list(value[:_MAX_COLLECTION_ITEMS])
        return [_sanitize_value(item, depth=depth + 1) for item in items]
    return {"_omitted_type": type(value).__name__}


__all__ = [
    "PUBLIC_HOOK_DEFAULT_TIMEOUT_S",
    "PUBLIC_HOOK_SCHEMA_VERSION",
    "DuplicateHookError",
    "HookAction",
    "HookCorrelation",
    "HookDecision",
    "HookEvidenceReference",
    "HookInvocation",
    "HookName",
    "HookOutcome",
    "HookRegistry",
    "InvalidHookDecisionError",
    "InvalidHookPayloadError",
    "public_hook_schema",
]

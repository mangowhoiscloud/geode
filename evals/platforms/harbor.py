"""Harbor external-agent adapter for GEODE terminal benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import logging
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.memory.atomic_write import atomic_write_json, atomic_write_text
from core.observability.redaction import redact_and_bound_text

if TYPE_CHECKING:

    class HarborBaseAgent:
        logs_dir: Path
        model_name: str | None

        def __init__(
            self,
            logs_dir: Path,
            model_name: str | None = None,
            **kwargs: Any,
        ) -> None: ...

    class HarborCodexAgent:
        logs_dir: Path
        logger: Any

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

        def populate_context_post_run(self, context: Any) -> None: ...

else:
    try:
        HarborBaseAgent = importlib.import_module("harbor.agents.base").BaseAgent
    except ImportError:  # Harbor is an opt-in benchmark dependency.
        HarborBaseAgent = object
    try:
        HarborCodexAgent = importlib.import_module("harbor.agents.installed.codex").Codex
    except ImportError:  # Harbor is an opt-in benchmark dependency.
        HarborCodexAgent = object


log = logging.getLogger(__name__)
_MAX_RECORDING_EVENT_CHARS = 64_000
_RECORDING_RECEIPT_SCHEMA = "geode.harbor-recording-receipt@1"


@dataclass
class HarborExecTool:
    environment: Any

    @property
    def name(self) -> str:
        return "terminal_exec"

    @property
    def description(self) -> str:
        return "Run one shell command in the isolated benchmark environment."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "cwd": {"type": ["string", "null"]},
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 600,
                    "default": 120,
                },
            },
            "additionalProperties": False,
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        command = str(kwargs.pop("command"))
        cwd_raw = kwargs.pop("cwd", None)
        cwd = str(cwd_raw) if cwd_raw is not None else None
        timeout_seconds = int(kwargs.pop("timeout_seconds", 120))
        result = await self.environment.exec(
            command=command,
            cwd=cwd,
            timeout_sec=timeout_seconds,
        )
        return {
            "result": result.stdout or "",
            "stderr": result.stderr or "",
            "return_code": result.return_code,
        }


def _usage(result: Any) -> dict[str, int | float]:
    usage = getattr(result, "usage", None)
    to_dict = getattr(usage, "to_dict", None)
    raw = to_dict() if callable(to_dict) else {}
    return raw if isinstance(raw, dict) else {}


def _agent_time_budget(value: float | None) -> float:
    budget = float(value or 0.0)
    if budget < 0:
        raise ValueError("agent_timeout_sec must be non-negative")
    return budget


def _usage_event_metadata(event: Any) -> dict[str, Any]:
    """Allowlisted numeric terminal evidence, never raw provider/tool payloads."""
    payload = event.payload
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}

    def identifier(value: Any, limit: int = 256) -> str | None:
        return (
            value
            if isinstance(value, str)
            and len(value) <= limit
            and not re.match(r"^[A-Za-z]:[/\\]", value)
            and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]*", value)
            else None
        )

    counters = {
        name: value
        if isinstance(value := usage.get(name), int) and not isinstance(value, bool) and value >= 0
        else None
        for name in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens")
    }
    long_write = usage.get("cache_write_1h_tokens")
    counters["cache_write_1h_tokens"] = (
        long_write
        if isinstance(long_write, int)
        and not isinstance(long_write, bool)
        and 0 <= long_write <= (counters["cache_write_tokens"] or 0)
        else None
    )
    reasoning = usage.get("reasoning_tokens")
    if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
        counters["reasoning_tokens"] = reasoning
    source_id = getattr(event, "id", None)
    occurred_at = getattr(event, "occurred_at", None)
    payload_hash = getattr(event, "payload_hash", None)
    purpose = payload.get("purpose")
    return {
        "session_id": identifier(getattr(event, "session_id", None)),
        "llm_call_id": identifier(getattr(event, "llm_call_id", None)),
        "tool_call_id": identifier(getattr(event, "tool_call_id", None)),
        "llm_attempt_id": identifier(getattr(event, "llm_attempt_id", None)),
        "source_event_id": source_id
        if isinstance(source_id, int) and not isinstance(source_id, bool) and source_id >= 0
        else None,
        "occurred_at": occurred_at
        if isinstance(occurred_at, int | float)
        and not isinstance(occurred_at, bool)
        and math.isfinite(occurred_at)
        else None,
        "source_payload_hash": payload_hash
        if isinstance(payload_hash, str) and re.fullmatch(r"[a-f0-9]{64}", payload_hash)
        else None,
        "model": identifier(payload.get("model")),
        "response_model": identifier(payload.get("response_model")),
        "provider": identifier(payload.get("provider")),
        "adapter": identifier(payload.get("adapter")),
        "purpose": purpose
        if isinstance(purpose, str)
        and purpose
        in {
            "agentic_loop",
            "turn_verification",
            "cognitive_reflection",
            "candidate_judge",
            "structured_decision",
            "text_completion",
            "context_compaction",
            "learning_extraction",
            "memory_dreaming",
            "context_exhaustion",
            "hosted_search",
        }
        else None,
        "source": identifier(payload.get("source"), 80),
        "effort": identifier(payload.get("effort"), 32),
        "error_type": identifier(payload.get("error_type"), 128),
        "usage": counters,
    }


def _summarize_usage(events: list[Any], *, known_sink_failure: bool = False) -> dict[str, Any]:
    """Project existing durable events, preserving unknowns and attempt IDs."""
    mapping_anomalies = 0
    for event in events:
        payload = getattr(event, "payload", {})
        is_call_event = getattr(event, "event", "") in {
            "llm_call_started",
            "llm_call_ended",
            "llm_call_start",
            "llm_call_end",
        } or event.action in {
            "llm.call.started",
            "llm.call.ended",
            "hook.llm_call_started",
            "hook.llm_call_ended",
        }
        if (
            is_call_event
            and isinstance(payload, dict)
            and (
                payload.get("_generic_projection")
                or "_mapping_error_type" in payload
                or "_fallback_reason" in payload
            )
        ):
            mapping_anomalies += 1
    degraded = known_sink_failure or mapping_anomalies > 0
    calls = [e for e in events if e.action == "llm.call.ended"]
    usages = [e.payload.get("usage") for e in calls]
    recorded = [u for u in usages if isinstance(u, dict)]
    started = [e for e in events if e.action == "llm.call.started"]
    start_ids = [(getattr(e, "session_id", None), e.llm_attempt_id) for e in started]
    end_ids = [(getattr(e, "session_id", None), e.llm_attempt_id) for e in calls]
    paired = (
        bool(start_ids)
        and all(session and attempt for session, attempt in start_ids + end_ids)
        and len(set(start_ids)) == len(start_ids)
        and len(set(end_ids)) == len(end_ids)
        and set(start_ids) == set(end_ids)
    )
    complete = paired and len(recorded) == len(calls) and not degraded
    result: dict[str, Any] = {
        "scope": "recorded-runtime-llm-attempts-only",
        "whole_runtime_complete": False,
        "observation_status": "degraded" if degraded else "no_known_faults",
        "known_sink_failure": known_sink_failure,
        "mapping_anomaly_events": mapping_anomalies,
        "limitation": (
            "whole-runtime producer coverage and background-writer quiescence require "
            "separate verification; paired retained events alone cannot establish either; "
            "turn-final judge calls share loop accounting; legacy call purpose remains unknown"
        ),
        "call_events": len(calls),
        "terminal_event_count": len(calls),
        "recorded_attempts_scope": (
            "canonical-llm-ended-events-only; duplicates retained; "
            "no synthetic missing starts or ends"
        ),
        "recorded_attempts": [_usage_event_metadata(event) for event in calls],
        "recorded_attempts_timestamp_unit": "unix-seconds-utc",
        "started_events": len(started),
        "usage_events": len(recorded),
        "attempt_pairing_complete": paired,
    }
    for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
        values = [u.get(field) for u in recorded]
        observed = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
        result[field] = sum(observed) if complete and len(observed) == len(calls) else None
        result[f"{field}_observed_sum"] = sum(observed)
        result[f"{field}_missing_events"] = len(calls) - len(observed)
    return result


def _atif_trajectory_from_geode(
    trajectory: Mapping[str, Any],
    *,
    model: str,
    provider: str,
    source: str,
    effort: str | None,
    version: str,
    metrics: Mapping[str, int | float | None],
) -> dict[str, Any]:
    integrity = trajectory.get("integrity")
    if not isinstance(integrity, Mapping) or not integrity.get("scope_complete"):
        raise ValueError("ATIF export requires a scope-complete canonical GEODE trajectory")

    raw_events = trajectory.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("ATIF export requires canonical GEODE events")
    events = [event for event in raw_events if isinstance(event, Mapping)]
    results = {
        (
            str(event.get("session_id") or ""),
            str(event.get("turn_id") or ""),
            str(event.get("call_id") or ""),
        ): event
        for event in events
        if event.get("kind") == "tool.completed"
    }

    steps: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        payload = event.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        base = {
            "step_id": len(steps) + 1,
            "timestamp": str(event.get("occurred_at") or ""),
            "message": str(payload.get("content") or ""),
        }
        if kind == "message.user":
            steps.append({**base, "source": "user"})
        elif kind == "message.assistant":
            steps.append(
                {
                    **base,
                    "source": "agent",
                    "model_name": model,
                    "reasoning_effort": effort,
                }
            )
        elif kind == "tool.called":
            call_id = str(event.get("call_id") or "")
            key = (
                str(event.get("session_id") or ""),
                str(event.get("turn_id") or ""),
                call_id,
            )
            result_event = results.get(key)
            arguments = payload.get("arguments")
            tool = str(payload.get("tool") or "")
            if (
                not call_id
                or not tool
                or not isinstance(arguments, Mapping)
                or result_event is None
            ):
                raise ValueError("ATIF export requires paired, identified canonical tool events")
            result_payload = result_event.get("payload")
            result_payload = result_payload if isinstance(result_payload, Mapping) else {}
            content = result_payload.get("result")
            if not isinstance(content, str):
                content = json.dumps(
                    content if content is not None else result_payload.get("summary", ""),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
            steps.append(
                {
                    **base,
                    "source": "agent",
                    "model_name": model,
                    "reasoning_effort": effort,
                    "tool_calls": [
                        {
                            "tool_call_id": call_id,
                            "function_name": tool,
                            "arguments": dict(arguments),
                        }
                    ],
                    "observation": {
                        "results": [
                            {
                                "source_call_id": call_id,
                                "content": content,
                                "extra": {
                                    "status": str(result_payload.get("status") or ""),
                                },
                            }
                        ]
                    },
                }
            )

    if not steps:
        raise ValueError("ATIF export requires at least one dialogue or tool step")
    return {
        "schema_version": "ATIF-v1.7",
        "session_id": str(trajectory.get("source", {}).get("session") or ""),
        "trajectory_id": str(trajectory.get("trajectory_id") or ""),
        "agent": {
            "name": "geode",
            "version": version,
            "model_name": model,
            "tool_definitions": [
                {
                    "name": "terminal_exec",
                    "description": "Run one shell command in the isolated benchmark environment.",
                    "parameters": HarborExecTool(None).parameters,
                }
            ],
            "extra": {"provider": provider, "source": source, "reasoning_effort": effort},
        },
        "steps": steps,
        "notes": (
            "Projected from GEODE's canonical session timeline. Tool calls are emitted as "
            "one-call steps because exact LLM response grouping is not retained; "
            "llm_call_count is therefore unknown."
        ),
        "final_metrics": {
            "total_prompt_tokens": metrics.get("input_tokens"),
            "total_completion_tokens": metrics.get("output_tokens"),
            "total_cached_tokens": metrics.get("cache_read_tokens"),
            "total_cost_usd": metrics.get("cost_usd"),
            "total_steps": len(steps),
        },
        "extra": {
            "source_schema": str(trajectory.get("schema_id") or ""),
            "source_trajectory_id": str(trajectory.get("trajectory_id") or ""),
            "source_replay_complete": bool(integrity.get("replay_complete")),
        },
    }


def _write_atif_trajectory(path: Path, payload: Mapping[str, Any]) -> None:
    trajectory_model = importlib.import_module("harbor.models.trajectories").Trajectory
    validated = trajectory_model.model_validate(payload)
    atomic_write_json(path, validated.to_json_dict(), indent=2)


def _recording_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _recording_text(value: Any) -> str:
    return (
        redact_and_bound_text(value, _MAX_RECORDING_EVENT_CHARS)
        .replace("\r\n", "\n")
        .replace("\n", "\r\n")
    )


def _recording_step_output(step: Mapping[str, Any]) -> list[str]:
    tool_calls = step.get("tool_calls")
    calls = (
        [call for call in tool_calls if isinstance(call, Mapping)]
        if isinstance(tool_calls, list)
        else []
    )
    chunks: list[str] = []
    if calls:
        for call in calls:
            name = str(call.get("function_name") or "tool")
            arguments = call.get("arguments")
            arguments = arguments if isinstance(arguments, Mapping) else {}
            action = arguments.get("command", arguments.get("input"))
            if action is None:
                action = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
            chunks.append(f"\x1b[1;36m$ [{name}]\x1b[0m {_recording_text(action)}\r\n")

        observation = step.get("observation")
        observation = observation if isinstance(observation, Mapping) else {}
        results = observation.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, Mapping):
                    continue
                content = _recording_text(result.get("content"))
                if content:
                    chunks.append(content + ("" if content.endswith("\r\n") else "\r\n"))
        return chunks

    message = _recording_text(step.get("message"))
    if message:
        source = str(step.get("source") or "event")
        label = "task" if source == "user" else source
        chunks.append(f"\x1b[1;33m[{label}]\x1b[0m {message}\r\n")
    return chunks


def _render_asciicast(trajectory: Mapping[str, Any]) -> tuple[str, dict[str, int]]:
    schema_version = trajectory.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.startswith("ATIF-v1."):
        raise ValueError("recording reconstruction requires an ATIF v1 trajectory")
    steps = trajectory.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("ATIF trajectory must contain at least one step")

    parsed = [
        _recording_timestamp(step.get("timestamp")) if isinstance(step, Mapping) else None
        for step in steps
    ]
    base = next((value for value in parsed if value is not None), None)
    agent = trajectory.get("agent")
    agent = agent if isinstance(agent, Mapping) else {}
    header: dict[str, Any] = {
        "version": 2,
        "width": 120,
        "height": 36,
        "title": f"Harbor ATIF replay — {agent.get('name') or 'agent'}",
        "env": {
            "TERM": "xterm-256color",
            "SHELL": "/bin/sh",
            "GEODE_RECORDING_PROVENANCE": "trajectory-reconstruction",
        },
    }
    if base is not None:
        header["timestamp"] = int(base.timestamp())

    events: list[list[Any]] = [
        [
            0.0,
            "o",
            "\x1b[1;35m[reconstructed]\x1b[0m Harbor ATIF replay; not a raw PTY capture.\r\n",
        ]
    ]
    previous = 0.0
    synthetic = 0
    clamped = 0
    for step, occurred_at in zip(steps, parsed, strict=True):
        if not isinstance(step, Mapping):
            continue
        if occurred_at is None or base is None:
            offset = previous + 0.001
            synthetic += 1
        else:
            offset = (occurred_at - base).total_seconds()
            if offset < previous:
                offset = previous
                clamped += 1
        previous = offset
        events.extend([round(offset, 6), "o", chunk] for chunk in _recording_step_output(step))

    if len(events) == 1:
        raise ValueError("ATIF trajectory contains no replayable content")
    lines = [json.dumps(header, ensure_ascii=False)]
    lines.extend(json.dumps(event, ensure_ascii=False) for event in events)
    return "\n".join(lines) + "\n", {
        "step_count": len(steps),
        "event_count": len(events),
        "synthetic_timestamp_count": synthetic,
        "clamped_timestamp_count": clamped,
    }


def write_harbor_recording(
    trajectory_path: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any] | None:
    """Write one derived cast and receipt; preserve any existing recording."""
    trajectory_path = Path(trajectory_path)
    recording_path = trajectory_path.with_name("recording.cast")
    receipt_path = trajectory_path.with_name("recording.receipt.json")
    if recording_path.exists() and not overwrite:
        return None

    source_bytes = trajectory_path.read_bytes()
    trajectory = json.loads(source_bytes)
    if not isinstance(trajectory, Mapping):
        raise ValueError("ATIF trajectory root must be an object")
    cast, timing = _render_asciicast(trajectory)
    cast_bytes = cast.encode("utf-8")
    receipt: dict[str, Any] = {
        "schema_id": _RECORDING_RECEIPT_SCHEMA,
        "recording_kind": "trajectory-reconstruction",
        "score_authority": False,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "path": trajectory_path.name,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "schema_version": str(trajectory.get("schema_version") or ""),
            "trajectory_id": str(trajectory.get("trajectory_id") or ""),
        },
        "output": {
            "path": recording_path.name,
            "sha256": hashlib.sha256(cast_bytes).hexdigest(),
            "format": "asciicast-v2",
        },
        "timing": timing,
        "privacy": {
            "known_secret_patterns": "redacted",
            "provider_reasoning": "omitted",
            "publication_state": "private-review-required",
        },
    }
    atomic_write_text(recording_path, cast)
    atomic_write_json(receipt_path, receipt, indent=2)
    return receipt


def backfill_harbor_recordings(
    root: Path,
    *,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, int]:
    """Create missing derived recordings below one closed Harbor job/run root."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    summary = {
        "trajectories": 0,
        "eligible": 0,
        "created": 0,
        "existing": 0,
        "failed": 0,
    }
    for trajectory_path in sorted(root.rglob("agent/trajectory.json")):
        summary["trajectories"] += 1
        if trajectory_path.with_name("recording.cast").exists() and not overwrite:
            summary["existing"] += 1
            continue
        try:
            if dry_run:
                trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
                if not isinstance(trajectory, Mapping):
                    raise ValueError("ATIF trajectory root must be an object")
                _render_asciicast(trajectory)
            else:
                write_harbor_recording(trajectory_path, overwrite=overwrite)
                summary["created"] += 1
            summary["eligible"] += 1
        except (OSError, ValueError, json.JSONDecodeError):
            summary["failed"] += 1
    return summary


def _write_recording_if_available(logs_dir: Path) -> None:
    trajectory_path = logs_dir / "trajectory.json"
    if not trajectory_path.is_file():
        return
    try:
        write_harbor_recording(trajectory_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Harbor recording reconstruction failed: %s", exc)


def _build_loop(
    environment: Any,
    *,
    model: str,
    provider: str,
    source: str,
    effort: str,
    timeout: float,
    max_tokens: int = 32768,
    max_rounds: int = 0,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.hooks.middleware import MiddlewareRegistry
    from core.hooks.system import HookSystem
    from core.llm.adapters.registry import bootstrap_builtins
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.tools.registry import ToolRegistry
    from core.wiring.runtime import build_policy_sources

    from evals.run_timeline import current_run_timeline as current_activity_sink

    policy_sources = build_policy_sources()
    bootstrap_builtins(policy_sources=policy_sources)
    tool = HarborExecTool(environment)
    registry = ToolRegistry()
    registry.register(tool)
    hooks = HookSystem()
    executor = ToolExecutor(
        action_handlers={tool.name: tool.aexecute},
        auto_approve=True,
        hitl_level=0,
        tool_input_schemas={tool.name: tool.parameters},
        middleware_registry=MiddlewareRegistry(events=hooks),
    )
    loop = AgenticLoop(
        ConversationContext(max_turns=200),
        executor,
        config=AgenticLoopConfig(
            source=source,
            effort=effort,
            max_tokens=max_tokens,
            max_rounds=max_rounds,
            time_budget_s=timeout,
            allowed_tool_names={tool.name},
            force_include_allowed_tools=True,
            system_prompt_override=(
                "Agent: GEODE inside a Harbor terminal benchmark. Complete the task in the "
                "isolated environment using terminal_exec. Inspect before editing, use command "
                "results as evidence, and stop after the requested state is verified."
            ),
        ),
        model=model,
        provider=provider,
        tool_registry=registry,
        quiet=True,
        hooks=hooks,
        activity_sink_provider=current_activity_sink,
        policy_sources=policy_sources,
    )
    # Observe the thin control without installing native behavioral hooks.
    # Both rails share its existing session DB; no parallel raw store.
    if loop._timeline is None:
        hooks.close()
        raise RuntimeError("Harbor observation requires the canonical session timeline")
    hooks.register_sink(
        HookPersistenceSink(
            HookEventStore(loop._timeline.db_path),
            session_key=loop._session_id,
            run_id=f"harbor-{loop._session_id}",
        ),
        name="harbor_observation",
    )
    return loop


class GeodeHarborAgent(HarborBaseAgent):
    """Run the current GEODE AgenticLoop against Harbor's external environment."""

    SUPPORTS_ATIF = True

    @staticmethod
    def name() -> str:
        return "geode"

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        *,
        provider: str = "openai",
        source: str = "subscription",
        effort: str = "max",
        agent_timeout_sec: float | None = None,
        max_tokens: int | None = None,
        max_rounds: int | None = None,
        **kwargs: Any,
    ) -> None:
        for name, value in (("max_tokens", max_tokens), ("max_rounds", max_rounds)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer when supplied")
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.provider = provider
        self.source = source
        self.effort = effort
        self.agent_timeout_sec = _agent_time_budget(agent_timeout_sec)
        self.max_tokens = 32768 if max_tokens is None else max_tokens
        self.max_rounds = 0 if max_rounds is None else max_rounds

    def version(self) -> str:
        return importlib.metadata.version("geode-agent")

    async def setup(self, environment: Any) -> None:
        return None

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        model = (self.model_name or "gpt-5.6-terra").removeprefix("geode/")
        loop = _build_loop(
            environment,
            model=model,
            provider=self.provider,
            source=self.source,
            effort=self.effort,
            timeout=self.agent_timeout_sec,
            max_tokens=self.max_tokens,
            max_rounds=self.max_rounds,
        )
        previous = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT")
        os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = "1"
        result = None
        error_type = None
        try:
            result = await loop.arun(instruction)
            if getattr(result, "error", None):
                await loop.amark_session_error()
            else:
                await loop.amark_session_completed()
        except BaseException as exc:
            error_type = type(exc).__name__
            try:
                await loop.amark_session_error()
            except BaseException as cleanup_error:
                log.warning("Harbor session finalization failed: %s", type(cleanup_error).__name__)
            raise
        finally:
            if previous is None:
                os.environ.pop("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", None)
            else:
                os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = previous
            try:
                loop._hooks.close()
            except BaseException as cleanup_error:
                if error_type is None:
                    raise
                log.warning("Harbor hook cleanup failed: %s", type(cleanup_error).__name__)
            try:
                self._export_result(instruction, context, loop, result, error_type)
            except BaseException as exc:
                if error_type is None:
                    raise
                # Retain Harbor's original timeout/error classification even
                # when incomplete dialogue cannot be converted to ATIF.
                log.warning("Harbor interrupted-run export failed: %s", type(exc).__name__)

    def _export_result(
        self,
        instruction: str,
        context: Any,
        loop: Any,
        result: Any,
        error_type: str | None,
    ) -> None:
        from core.observability.event_store import HookEventStore
        from core.observability.trajectory import export_trajectory, trajectory_from_sessions

        # Closing the sink also closes its reader. Open an independent reader
        # of the same DB after this loop's writers have stopped. Filter by
        # session so concurrent Harbor trials cannot contaminate the totals.
        store = HookEventStore(loop._timeline.db_path)
        try:
            events: list[Any] = []
            while batch := store.read(session_id=loop._session_id, limit=500, offset=len(events)):
                events.extend(batch)
        finally:
            store.close()
        usage = _summarize_usage(events, known_sink_failure=loop._hooks.has_sink_failures)
        context.n_input_tokens = usage["input_tokens"]
        context.n_cache_tokens = usage["cached_input_tokens"]
        context.n_output_tokens = usage["output_tokens"]
        context.cost_usd = _usage(result).get("cost_usd")
        context.metadata = {
            "geode_session_id": loop._session_id,
            "termination_reason": str(getattr(result, "termination_reason", "unknown")),
            "rounds": int(getattr(result, "rounds", 0) or 0),
            "error_type": error_type,
            "usage": usage,
        }
        source_identity = {
            "harness": "harbor",
            "session": loop._session_id,
            "task": hashlib.sha256(instruction.encode()).hexdigest(),
        }
        trajectory = trajectory_from_sessions(
            [loop._session_id],
            db_path=store.db_path,
            trajectory_id=f"harbor-{loop._session_id}",
            source=source_identity,
            outcome=context.metadata,
            provenance={"adapter": "evals.platforms.harbor"},
            privacy={"review_state": "local", "native_results_embedded": False},
            trajectory_class=("benchmark", "terminal", "tool", "lifecycle"),
            content_policy="digest",
        )
        export_trajectory(self.logs_dir / "geode-trajectory.json", trajectory)
        full_trajectory = trajectory_from_sessions(
            [loop._session_id],
            db_path=store.db_path,
            trajectory_id=f"harbor-{loop._session_id}",
            source=source_identity,
            outcome=context.metadata,
            provenance={"adapter": "evals.platforms.harbor"},
            privacy={"review_state": "local", "native_results_embedded": False},
            trajectory_class=("benchmark", "terminal", "tool", "lifecycle"),
            content_policy="full",
        )
        # Preserve canonical partial evidence before stricter ATIF conversion.
        export_trajectory(self.logs_dir / "geode-trajectory.private.json", full_trajectory)
        _write_atif_trajectory(
            self.logs_dir / "trajectory.json",
            _atif_trajectory_from_geode(
                full_trajectory,
                model=(self.model_name or "gpt-5.6-terra").removeprefix("geode/"),
                provider=self.provider,
                source=self.source,
                effort=self.effort,
                version=self.version(),
                metrics={
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "cache_read_tokens": usage["cached_input_tokens"],
                    "cost_usd": context.cost_usd,
                },
            ),
        )
        _write_recording_if_available(self.logs_dir)


class RecordedCodexHarborAgent(HarborCodexAgent):
    """Harbor Codex with post-run trajectory replay instrumentation."""

    SUPPORTS_ATIF = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "CODEX_FORCE_AUTH_JSON" in (kwargs.get("extra_env") or {}):
            raise ValueError(
                "Set CODEX_FORCE_AUTH_JSON in the Harbor process environment, not agent.env: "
                "Harbor treats AUTH flags as secrets and can corrupt numeric result fields."
            )
        super().__init__(*args, **kwargs)

    def populate_context_post_run(self, context: Any) -> None:
        super().populate_context_post_run(context)
        _write_recording_if_available(self.logs_dir)


def _recording_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconstruct Harbor recordings from ATIF traces.")
    parser.add_argument("root", type=Path, help="Closed Harbor job or run root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    summary = backfill_harbor_recordings(
        args.root,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(_recording_main())


__all__ = [
    "GeodeHarborAgent",
    "HarborExecTool",
    "RecordedCodexHarborAgent",
    "backfill_harbor_recordings",
    "write_harbor_recording",
]

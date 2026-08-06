#!/usr/bin/env python3
"""Exercise every public hook and trusted middleware boundary.

The probe uses three owning runtime paths:

- a live AgenticLoop tool turn for prompt/tool/verify/stop/session hooks;
- client compaction for PreCompact/PostCompact;
- SubAgentManager for SubagentStart/SubagentStop.

It writes an isolated SQLite store, the optional JSONL mirror, a machine
summary, and a redacted normalized trajectory ready for the external
geode-eval-artifacts repository.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, message: Any) -> None:
    if not condition:
        raise RuntimeError(f"hook behavior E2E gate failed: {message!r}")


async def _run(
    output_dir: Path,
    *,
    model: str,
    effort: str,
    geode_revision: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    runtime_home = output_dir / "geode-home"
    os.environ["GEODE_HOME"] = str(runtime_home)

    from core.agent.cognitive_state_ctx import set_session_id, set_turn_id
    from core.agent.context_manager import ContextWindowManager
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.sub_agent import SubAgentManager, SubTask
    from core.agent.tool_executor import ToolExecutor
    from core.hooks import (
        HookAction,
        HookDecision,
        HookEvidenceReference,
        HookName,
        HookRegistry,
        LlmCallRequest,
        MiddlewareRegistry,
        RuntimeEvent,
        RuntimeEventBus,
        ToolCallRequest,
    )
    from core.llm.adapters.registry import bootstrap_builtins
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.orchestration.isolated_execution import IsolatedRunner
    from core.self_improving.loop.observe.run_timeline import (
        RunTimeline,
        run_timeline_scope,
    )
    from core.tools.registry import ToolRegistry

    captured_at = _utc_now()
    run_id = f"hook-middleware-e2e-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    session_key = f"{run_id}:suite"
    sqlite_path = output_dir / "sessions.db"
    timeline_path = output_dir / "events.jsonl"
    events: list[dict[str, Any]] = []

    def record(actor: str, kind: str, scenario: str, payload: dict[str, Any]) -> None:
        events.append(
            {
                "actor": actor,
                "kind": kind,
                "payload": {"scenario": scenario, **payload},
                "sequence": len(events) + 1,
                "ts": _utc_now(),
            }
        )

    runtime_events = RuntimeEventBus()
    store = HookEventStore(sqlite_path)
    runtime_events.register_sink(
        HookPersistenceSink(store, session_key=session_key, run_id=run_id),
        name="hook_behavior_e2e",
    )
    public_hooks = HookRegistry(events=runtime_events)
    middleware = MiddlewareRegistry(events=runtime_events)

    def decision_for(hook: HookName, invocation: Any) -> HookDecision:
        if hook is HookName.USER_PROMPT_SUBMIT:
            return HookDecision(
                action=HookAction.REWRITE,
                updates={
                    "user_input": (
                        f"{invocation.payload['user_input']}\n"
                        "Complete the required probe before answering."
                    )
                },
                reason="behavior-e2e input rewrite",
            )
        if hook is HookName.PRE_TOOL_USE:
            return HookDecision(
                action=HookAction.REWRITE,
                updates={"arguments": {"marker": "public-hook-rewrite"}},
                reason="behavior-e2e tool rewrite",
            )
        if hook is HookName.PERMISSION_REQUEST:
            return HookDecision(
                action=HookAction.ALLOW,
                reason="isolated behavior-e2e probe",
            )
        if hook is HookName.POST_TOOL_USE:
            return HookDecision(
                action=HookAction.ADD_CONTEXT,
                instruction="The behavior probe completed through PostToolUse.",
            )
        if hook is HookName.PRE_COMPACT:
            return HookDecision(
                action=HookAction.REWRITE,
                updates={"keep_recent": 3},
                reason="bounded behavior-e2e compaction rewrite",
            )
        if hook is HookName.PRE_VERIFY:
            return HookDecision(
                action=HookAction.STRENGTHEN,
                evidence_refs=(
                    HookEvidenceReference(
                        kind="native_receipt",
                        schema_id="geode.hook-behavior-receipt@1",
                        authority="GEODE behavior E2E tool receipt",
                        reference="behavior-e2e:tool-receipt",
                    ),
                ),
            )
        if hook is HookName.POST_VERIFY:
            return HookDecision(
                action=HookAction.ACCEPT,
                evidence_refs=(
                    HookEvidenceReference(
                        kind="native_receipt",
                        schema_id="geode.hook-behavior-verifier@1",
                        authority="GEODE behavior E2E verifier",
                        reference="behavior-e2e:built-in-verifier",
                    ),
                ),
            )
        if hook is HookName.STOP:
            return HookDecision(action=HookAction.FINALIZE)
        return HookDecision(action=HookAction.CONTINUE)

    def make_hook_handler(hook: HookName) -> Any:
        def handler(invocation: Any) -> HookDecision:
            decision = decision_for(hook, invocation)
            record(
                "extension",
                "public_hook",
                (
                    "compaction"
                    if hook in {HookName.PRE_COMPACT, HookName.POST_COMPACT}
                    else (
                        "subagent"
                        if hook in {HookName.SUBAGENT_START, HookName.SUBAGENT_STOP}
                        else "live-agent"
                    )
                ),
                {
                    "action": decision.action.value,
                    "hook": hook.value,
                    "payload_sha256": _payload_digest(invocation.payload),
                    "session_id": invocation.correlation.session_id,
                    "turn_id": invocation.correlation.turn_id,
                },
            )
            return decision

        return handler

    for hook in HookName:
        public_hooks.register(
            hook,
            make_hook_handler(hook),
            name=f"behavior-e2e-{hook.value}",
        )

    def force_permission(invocation: Any) -> HookDecision:
        record(
            "extension",
            "public_hook",
            "live-agent",
            {
                "action": HookAction.REQUEST_PERMISSION.value,
                "hook": HookName.PRE_TOOL_USE.value,
                "payload_sha256": _payload_digest(invocation.payload),
                "session_id": invocation.correlation.session_id,
                "turn_id": invocation.correlation.turn_id,
            },
        )
        return HookDecision(
            action=HookAction.REQUEST_PERMISSION,
            reason="exercise PermissionRequest",
        )

    public_hooks.register(
        HookName.PRE_TOOL_USE,
        force_permission,
        name="behavior-e2e-force-permission",
        priority=200,
    )

    class ProbeMiddleware:
        def __init__(self) -> None:
            self.counts = {
                "tool_request": 0,
                "tool_execution": 0,
                "llm_request": 0,
                "llm_execution": 0,
            }

        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            self.counts["tool_request"] += 1
            record(
                "extension",
                "middleware",
                "live-agent",
                {
                    "surface": "tool_request",
                    "transformed": True,
                    "tool": request.tool_name,
                },
            )
            return request.with_arguments({"marker": "tool-request-middleware"})

        async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
            self.counts["tool_execution"] += 1
            call_id = f"tool-call-{self.counts['tool_execution']}"
            session_id = str(request.correlation.get("session_id") or "")
            turn_id = str(request.correlation.get("turn_id") or "")
            record(
                "assistant",
                "tool_call",
                "live-agent",
                {
                    "argument_sha256": _payload_digest(request.arguments),
                    "call_id": call_id,
                    "session_id": session_id,
                    "tool": request.tool_name,
                    "turn_id": turn_id,
                },
            )
            result = await next_call(request)
            record(
                "environment",
                "tool_result",
                "live-agent",
                {
                    "call_id": call_id,
                    "result_sha256": _payload_digest(result),
                    "session_id": session_id,
                    "status": "error" if result.get("error") else "ok",
                    "tool": request.tool_name,
                    "turn_id": turn_id,
                },
            )
            record(
                "extension",
                "middleware",
                "live-agent",
                {"surface": "tool_execution", "status": "called_next"},
            )
            return {**result, "tool_execution_middleware": "passed"}

        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            self.counts["llm_request"] += 1
            bounded_tokens = min(request.request.max_tokens, 8_192)
            record(
                "extension",
                "middleware",
                "live-agent",
                {
                    "max_tokens_after": bounded_tokens,
                    "max_tokens_before": request.request.max_tokens,
                    "surface": "llm_request",
                    "transformed": bounded_tokens != request.request.max_tokens,
                },
            )
            return request.with_request(
                dataclasses.replace(request.request, max_tokens=bounded_tokens)
            )

        async def llm_execution(self, request: LlmCallRequest, next_call: Any) -> Any:
            self.counts["llm_execution"] += 1
            result = await next_call(request)
            record(
                "extension",
                "middleware",
                "live-agent",
                {
                    "adapter": getattr(request.adapter, "name", ""),
                    "surface": "llm_execution",
                    "status": "ok",
                },
            )
            return result

    probe_middleware = ProbeMiddleware()
    middleware.register_tool_request(probe_middleware, name="behavior-e2e")
    middleware.register_tool_execution(probe_middleware, name="behavior-e2e")
    middleware.register_llm_request(probe_middleware, name="behavior-e2e")
    middleware.register_llm_execution(probe_middleware, name="behavior-e2e")

    class ProbeTool:
        name = "hook_behavior_probe"
        description = (
            "Required behavior E2E probe. Call exactly once with marker='model-input', "
            "then report completion."
        )
        parameters = {
            "type": "object",
            "properties": {"marker": {"type": "string"}},
            "required": ["marker"],
            "additionalProperties": False,
        }

        def __init__(self) -> None:
            self.calls: list[str] = []

        async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
            marker = str(kwargs["marker"])
            self.calls.append(marker)
            return {"marker": marker, "result": "behavior probe executed"}

    bootstrap_builtins()
    probe_tool = ProbeTool()
    tool_registry = ToolRegistry()
    tool_registry.register(probe_tool)
    executor = ToolExecutor(
        action_handlers={probe_tool.name: probe_tool.aexecute},
        hooks=runtime_events,
        hook_registry=public_hooks,
        middleware_registry=middleware,
        interactive_approval=False,
    )
    loop = AgenticLoop(
        ConversationContext(max_turns=50),
        executor,
        model=model,
        provider="openai",
        source="codex-oauth",
        effort=effort,
        max_tokens=16_384,
        max_rounds=6,
        time_budget_s=360,
        tool_registry=tool_registry,
        allowed_tool_names={probe_tool.name},
        hooks=runtime_events,
        enable_goal_decomposition=False,
        quiet=True,
        disable_settings_drift=True,
        session_id=f"{run_id}-live",
    )

    timeline = RunTimeline(
        session_id=run_id,
        gen_tag="hook-middleware-e2e",
        component="agentic_loop",
        path=timeline_path,
    )

    with run_timeline_scope(timeline):
        set_session_id(f"{run_id}-compact")
        set_turn_id("compact-turn")
        compact_messages = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"Behavior E2E compaction source turn {index}.",
                "seq": index + 1,
            }
            for index in range(12)
        ]
        context_manager = ContextWindowManager(
            hooks=runtime_events,
            hook_registry=public_hooks,
            quiet=True,
            session_id_provider=lambda: f"{run_id}-compact",
        )
        before_compaction = len(compact_messages)
        await context_manager._apply_overflow_strategy(
            {
                "strategy": "compact",
                "keep_recent": 4,
                "trigger": "behavior_e2e",
                "hard": False,
            },
            compact_messages,
            SimpleNamespace(compact_keep_recent=4),
            model,
            "openai",
        )
        record(
            "system",
            "compaction_result",
            "compaction",
            {
                "message_count_after": len(compact_messages),
                "message_count_before": before_compaction,
                "persisted": len(compact_messages) < before_compaction,
            },
        )

        set_session_id(f"{run_id}-parent")
        set_turn_id("subagent-turn")
        subagents = SubAgentManager(
            IsolatedRunner(),
            task_handler=lambda *_args, **_kwargs: {
                "summary": "isolated behavior E2E task completed"
            },
            timeout_s=30,
            hook_registry=public_hooks,
        )
        subagent_results = await subagents.adelegate(
            [
                SubTask(
                    "behavior-e2e-child",
                    "Exercise the sub-agent lifecycle boundary",
                    "analysis",
                    {"scope": "hook lifecycle"},
                )
            ]
        )
        record(
            "system",
            "subagent_result",
            "subagent",
            {
                "success": bool(subagent_results and subagent_results[0].success),
                "task_id": "behavior-e2e-child",
            },
        )

        live_result = await loop.arun(
            "Call hook_behavior_probe exactly once with marker 'model-input'. "
            "After the result, answer exactly: HOOK E2E COMPLETE."
        )
        await loop.amark_session_completed()
        record(
            "assistant",
            "final_result",
            "live-agent",
            {
                "output_sha256": _payload_digest(live_result.text),
                "rounds": live_result.rounds,
                "termination_reason": str(live_result.termination_reason),
            },
        )

    runtime_events.close()

    connection = sqlite3.connect(sqlite_path)
    try:
        extension_rows = connection.execute(
            "SELECT payload_json FROM hook_events WHERE event = ? ORDER BY id",
            (RuntimeEvent.EXTENSION_INVOKED.value,),
        ).fetchall()
        tool_rows = connection.execute(
            "SELECT event, payload_json FROM hook_events WHERE event IN (?, ?) ORDER BY id",
            (RuntimeEvent.TOOL_EXEC_STARTED.value, RuntimeEvent.TOOL_EXEC_ENDED.value),
        ).fetchall()
    finally:
        connection.close()
    sqlite_extensions = [json.loads(row[0]) for row in extension_rows]
    sqlite_tools = [(event, json.loads(payload)) for event, payload in tool_rows]
    timeline_rows = [
        json.loads(line)
        for line in timeline_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    timeline_extensions = [
        row for row in timeline_rows if row.get("event") == RuntimeEvent.EXTENSION_INVOKED.value
    ]

    observed_hooks = {
        str(event["payload"]["hook"]) for event in events if event["kind"] == "public_hook"
    }
    expected_hooks = {hook.value for hook in HookName}
    observed_middleware = {
        str(event["payload"]["surface"]) for event in events if event["kind"] == "middleware"
    }
    expected_middleware = {
        "tool_request",
        "tool_execution",
        "llm_request",
        "llm_execution",
    }
    hook_counts = {
        hook.value: sum(
            event["kind"] == "public_hook" and event["payload"]["hook"] == hook.value
            for event in events
        )
        for hook in HookName
    }
    expected_hook_counts = {
        hook.value: 2 if hook is HookName.PRE_TOOL_USE else 1 for hook in HookName
    }
    expected_tool_middleware_counts = {"tool_request": 1, "tool_execution": 1}
    llm_calls = probe_middleware.counts["llm_request"]
    expected_extension_rows = (
        sum(expected_hook_counts.values())
        + sum(expected_tool_middleware_counts.values())
        + (2 * llm_calls)
    )

    _require(
        observed_hooks == expected_hooks,
        {"missing_hooks": sorted(expected_hooks - observed_hooks)},
    )
    _require(
        hook_counts == expected_hook_counts,
        {"expected_hook_counts": expected_hook_counts, "observed": hook_counts},
    )
    _require(
        observed_middleware == expected_middleware,
        {"missing_middleware": sorted(expected_middleware - observed_middleware)},
    )
    _require(
        all(
            probe_middleware.counts[surface] == count
            for surface, count in expected_tool_middleware_counts.items()
        )
        and llm_calls >= 2
        and probe_middleware.counts["llm_execution"] == llm_calls,
        {
            "expected_tool_middleware_counts": expected_tool_middleware_counts,
            "llm_contract": "at least two paired request/execution calls",
            "observed": probe_middleware.counts,
        },
    )
    _require(
        probe_tool.calls == ["public-hook-rewrite"],
        {"tool_executor_calls": probe_tool.calls},
    )
    _require(
        len(subagent_results) == 1 and subagent_results[0].success,
        {"subagent_results": [result.success for result in subagent_results]},
    )
    _require(
        len(compact_messages) < before_compaction,
        {
            "compaction_after": len(compact_messages),
            "compaction_before": before_compaction,
        },
    )
    _require(
        [event for event, _payload in sqlite_tools]
        == [RuntimeEvent.TOOL_EXEC_STARTED.value, RuntimeEvent.TOOL_EXEC_ENDED.value],
        {"tool_events": [event for event, _payload in sqlite_tools]},
    )
    _require(
        all(
            payload.get("session_id") and payload.get("turn_id") for _event, payload in sqlite_tools
        ),
        {"tool_event_payloads": sqlite_tools},
    )
    tool_correlations = {
        (payload["session_id"], payload["turn_id"]) for _event, payload in sqlite_tools
    }
    _require(
        len(tool_correlations) == 1,
        {"tool_correlations": sorted(tool_correlations)},
    )
    _require(
        len(sqlite_extensions) == expected_extension_rows,
        {
            "expected_sqlite_extension_rows": expected_extension_rows,
            "observed": len(sqlite_extensions),
        },
    )
    _require(
        len(timeline_extensions) == expected_extension_rows,
        {
            "expected_timeline_extension_rows": expected_extension_rows,
            "observed": len(timeline_extensions),
        },
    )

    session_databases = [
        path
        for path in runtime_home.rglob("sessions.db")
        if path.resolve() != sqlite_path.resolve()
    ]
    persisted_compactions = 0
    for database in session_databases:
        connection = sqlite3.connect(database)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM context_artifacts "
                "WHERE session_id = ? AND kind = 'compaction_summary'",
                (f"{run_id}-compact",),
            ).fetchone()
            persisted_compactions += int(row[0] if row else 0)
        finally:
            connection.close()
    _require(
        persisted_compactions == 1,
        {"persisted_compactions": persisted_compactions},
    )

    published_at = _utc_now()
    from core.observability.trajectory import build_trajectory
    from core.observability.trajectory_release import stage_trajectory_release

    trajectory = build_trajectory(
        trajectory_id=f"geode-agenticloop-{run_id}",
        captured_at=captured_at,
        published_at=published_at,
        observed_on=datetime.now(UTC).strftime("%Y-%m-%d"),
        trajectory_class=("decision", "tool"),
        events=events,
        integrity={
            "canonicalization": (
                "UTF-8, LF, json.dumps(ensure_ascii=False, sort_keys=True, indent=2)"
            ),
            "scope_complete": True,
            "replay_complete": False,
            "fidelity": (
                "decision/tool trajectory; raw prompts, model reasoning, tool bodies, "
                "checkpoints, SQLite, and JSONL remain unpublished"
            ),
            "incompleteness": [],
            "replay_incompleteness": [
                "payload digests intentionally replace private prompt and result bodies"
            ],
            "pairing_rule": "tool_result.call_id equals the preceding tool_call.call_id",
        },
        outcome={
            "hook_coverage": {
                "covered": len(observed_hooks),
                "expected": len(expected_hooks),
                "missing": sorted(expected_hooks - observed_hooks),
            },
            "middleware_coverage": {
                "covered": len(observed_middleware),
                "expected": len(expected_middleware),
                "missing": sorted(expected_middleware - observed_middleware),
            },
            "result": "pass",
            "scored": False,
            "sqlite_extension_rows": len(sqlite_extensions),
            "terminal_state": str(live_result.termination_reason),
            "tool_calls": len(probe_tool.calls),
            "timeline_extension_rows": len(timeline_extensions),
            "unscored_reason": "release validation probe, not a benchmark task",
            "verifier": (
                "explicit release gates over exact hook/middleware multiplicity, exactly-once "
                "tool execution, SQLite/JSONL parity, correlation, and persisted compaction"
            ),
        },
        privacy={
            "license": "GEODE-owned run; no third-party dataset content",
            "redactions": [
                {
                    "rule": "publish payload digests instead of prompts/results",
                    "type": "content_reduction",
                },
                {
                    "rule": "exclude runtime home, SQLite, JSONL, and checkpoints",
                    "type": "artifact_allowlist",
                },
            ],
            "review_state": "reviewed",
        },
        provenance={
            "adapters": {"llm": "codex-oauth (source=subscription)"},
            "extraction_transform": (
                "in-process hook/middleware receipts normalized to decision/tool events"
            ),
            "geode_revision": geode_revision,
            "middleware_counts": probe_middleware.counts,
            "model_route": {
                "effort": effort,
                "model": model,
                "provider": "openai",
                "source": "subscription",
            },
            "storage_checks": {
                "compaction_artifacts": persisted_compactions,
                "sqlite_extension_rows": len(sqlite_extensions),
                "timeline_extension_rows": len(timeline_extensions),
            },
        },
        source={
            "harness": "scripts/eval/run_hook_behavior_e2e.py",
            "parents": None,
            "run": run_id,
            "session": session_key,
            "task": "validate GEODE public hooks and trusted middleware",
        },
    )
    _require(
        bool(trajectory["integrity"]["scope_complete"]),
        {
            "quality": trajectory["integrity"]["quality"],
            "scope_incompleteness": trajectory["integrity"]["scope_incompleteness"],
        },
    )

    publication_dir = stage_trajectory_release(
        output_dir / "publication",
        release_source="geode-agenticloop",
        release_scope="hook-middleware-behavior-e2e",
        trajectories={"trajectory.json": trajectory},
        published_at=published_at,
        require_complete=False,
        privacy_review={
            "reviewer": "GEODE hook behavior E2E release operator",
            "reviewed_at": published_at,
            "method": "allowlist review plus automated secret and identity scan",
            "scope": "hook-middleware-behavior-e2e",
            "attestation": (
                "Only the normalized decision/tool trajectory and content-bound "
                "manifest are approved for public release."
            ),
        },
        supersedes=("geode-agenticloop-hook-middleware-behavior-e2e-20260731T091808Z-d418e55ff8aa"),
    )
    manifest = json.loads((publication_dir / "manifest.json").read_text(encoding="utf-8"))
    secret_scan = dict(manifest["quality"]["secret_scan"])

    generated_files = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output_dir)
        generated_files.append(
            {
                "bytes": path.stat().st_size,
                "classification": (
                    "public"
                    if publication_dir in path.parents
                    else (
                        "local-evidence"
                        if path in {sqlite_path, timeline_path}
                        else "withheld-runtime"
                    )
                ),
                "path": relative.as_posix(),
                "sha256": _sha256(path),
            }
        )

    summary = {
        "artifact_inventory": generated_files,
        "captured_at": captured_at,
        "geode_revision": geode_revision,
        "hook_coverage": sorted(observed_hooks),
        "middleware_counts": probe_middleware.counts,
        "model_route": {
            "effort": effort,
            "model": model,
            "provider": "openai",
            "source": "subscription",
        },
        "publication_directory": publication_dir.relative_to(output_dir).as_posix(),
        "result": "pass",
        "run_id": run_id,
        "secret_scan": secret_scan,
        "sqlite_extension_rows": len(sqlite_extensions),
        "timeline_extension_rows": len(timeline_extensions),
    }
    _write_json(output_dir / "result.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--geode-revision", required=True)
    args = parser.parse_args()
    geode_revision = str(args.geode_revision)
    _require(
        re.fullmatch(r"[0-9a-f]{40}", geode_revision) is not None,
        {"geode_revision": geode_revision},
    )
    started = time.monotonic()
    result = asyncio.run(
        _run(
            args.output_dir.resolve(),
            model=str(args.model),
            effort=str(args.effort),
            geode_revision=geode_revision,
        )
    )
    print(
        json.dumps(
            {
                "duration_s": round(time.monotonic() - started, 3),
                **result,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

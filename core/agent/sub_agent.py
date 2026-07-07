"""SubAgentManager — delegate tasks to parallel sub-agents.

Leverages the existing IsolatedRunner infrastructure for concurrent
task execution, following the Claude Code pattern of parallel
sub-agent delegation.

Orchestration integration:
- TaskGraph: DAG-based dependency tracking per sub-task
- HookSystem: Event emission on task lifecycle (start/complete/fail)
- Deduplication of repeated task_id submissions via seen-set
- AgentRegistry: Agent-aware execution with context injection
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from core.agent.worker import WorkerRequest
from core.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
    IsolationResult,
)
from core.orchestration.task_system import Task, TaskGraph
from core.tools.base import load_tool_definition

if TYPE_CHECKING:
    from core.skills.agents import AgentRegistry

log = logging.getLogger(__name__)


# Matches a fenced code block (optional `json` / `JSON` lang tag, optional
# surrounding newlines). Smoke 7 surfaced both proximity and critic
# failing because the LLM (claude-cli without --json-schema wired
# through) returned otherwise-valid JSON wrapped in a ```json``` fence
# plus narrative prose. The pre-fix `json.loads(isolation.output)`
# rejected the wrapper and the SubAgentManager fell back to
# `{"raw": <wrapped-text>}` — which downstream consumers cannot
# interpret. Sister regex lives in
# `plugins/seed_generation/agents/base.py` (consumer-side defence
# from PR-JSON-CODEBLOCK-STRIP); this producer-side strip eliminates
# the {"raw": ...} fallback so all sub-agent consumers see a proper
# dict.
_JSON_CODEBLOCK_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def _strip_json_codeblock(text: str) -> str:
    """Unwrap a leading/trailing ```json``` fence around an LLM response.

    Returns the inner body if a fenced block is found (whitespace
    stripped), otherwise the original text unchanged. Plain (un-fenced)
    output passes through. The regex uses `re.search`, so prose
    preceding the fence is discarded.
    """
    match = _JSON_CODEBLOCK_RE.search(text)
    if match is None:
        return text
    return match.group(1).strip()


def _resolve_timeout_s(default: float) -> float:
    """Apply ``GEODE_SUBAGENT_TIMEOUT_S`` env override with clamp.

    PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — env knob for
    the SubAgentManager wall-clock cap so deployments can tune
    without code change. Clamp to ``[10, 3600]``:

    - Lower bound 10s — below this the orchestrator's per-phase
      framing overhead alone dominates; a sub-agent can't complete
      meaningful work.
    - Upper bound 3600s (1h) — matches openclaw's per-agent
      ``agents.defaults.timeoutSeconds`` documented range; longer
      runs should checkpoint + resume rather than hold a single
      subprocess open.

    Non-numeric or empty env values fall through to ``default``.
    """
    import os

    raw = os.environ.get("GEODE_SUBAGENT_TIMEOUT_S", "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return max(10.0, min(3600.0, value))


def _last_balanced_json_object(text: str) -> str | None:
    """Walk the text right-to-left and return the LAST balanced
    ``{...}`` substring whose first attempt at ``json.loads`` succeeds.

    PR-HANDOFF-SCHEMAS (2026-05-25) — fallback parser for the case
    where the LLM emitted JSON embedded inside prose. Smoke 15
    surfaced tool-using sub-agents ending with a prose summary while
    still including the structured object somewhere in the body.
    LLMs tend to put the final structured answer LAST, so we scan
    from the end. Returns ``None`` when no balanced + parseable
    block exists.

    Implementation: track open/close brace depth ignoring braces
    inside JSON strings (which honour backslash escapes). When a
    block's depth returns to zero we attempt ``json.loads``; the
    first one that parses wins.
    """
    if "{" not in text:
        return None
    # Collect end positions of every `}` that closes a top-level object.
    closes: list[int] = []
    depth = 0
    in_string = False
    escape = False
    start_idx = -1
    starts: list[int] = []
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx != -1:
                    starts.append(start_idx)
                    closes.append(i + 1)
                    start_idx = -1
    if not closes:
        return None
    # Try each candidate from last to first.
    for s, e in zip(reversed(starts), reversed(closes), strict=True):
        candidate = text[s:e]
        try:
            json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        return candidate
    return None


# Thread-local storage for subagent context (OpenClaw Spawn pattern)
_subagent_context = threading.local()

# Module-level announce queue: parent_session_key → list[SubAgentResult]
# Thread-safe via _announce_lock. Parent AgenticLoop polls this queue
# to inject completion notifications into its conversation context.
_announce_queue: dict[str, list[SubAgentResult]] = {}
_announce_lock = threading.Lock()

# TTL-based orphan cleanup for announce queue entries that are never drained
# (e.g. parent session crashed or was abandoned).
_announce_timestamps: dict[str, float] = {}
_ANNOUNCE_TTL_S = 300.0  # 5 min TTL for orphan results


def _cleanup_stale_announces() -> None:
    """Remove announce queue entries older than TTL."""
    now = time.time()
    with _announce_lock:
        stale_keys = [k for k, ts in _announce_timestamps.items() if now - ts > _ANNOUNCE_TTL_S]
        for k in stale_keys:
            _announce_queue.pop(k, None)
            _announce_timestamps.pop(k, None)


def drain_announced_results(parent_session_key: str) -> list[SubAgentResult]:
    """Drain all announced results for a parent session (thread-safe).

    Returns the list of completed SubAgentResults and clears the queue.
    Called by AgenticLoop._check_announced_results() each round.
    """
    _cleanup_stale_announces()
    with _announce_lock:
        results = _announce_queue.pop(parent_session_key, [])
        _announce_timestamps.pop(parent_session_key, None)
    return results


def cleanup_announce_queue(parent_session_key: str) -> None:
    """Remove orphan announce queue entry for a terminated session.

    Called on session end to prevent unbounded accumulation when parent
    sessions crash or are abandoned without draining.
    """
    with _announce_lock:
        _announce_queue.pop(parent_session_key, None)
        _announce_timestamps.pop(parent_session_key, None)


def get_subagent_context() -> tuple[bool, str]:
    """Return (is_subagent, child_session_key) from thread-local."""
    is_sub = getattr(_subagent_context, "is_subagent", False)
    key = getattr(_subagent_context, "child_session_key", "")
    return is_sub, key


# Task-type → default agent mapping
_TYPE_AGENT_MAP: dict[str, str] = {
    "analyze": "data_analyst",
    "search": "web_researcher",
    "compare": "data_analyst",
}

# Default denied tools for sub-agents (sandbox hardening).
# These tools should only be invoked by the parent agent.
SUBAGENT_DENIED_TOOLS: set[str] = {
    "set_api_key",  # credential changes — parent only
    "manage_auth",  # auth profile management — parent only
    "manage_login",  # plans + credentials + routing — parent only
    "profile_update",  # user profile changes — parent only
    "calendar_create_event",  # external system mutation — parent only
    "calendar_sync_scheduler",  # external system mutation — parent only
    "delegate_task",  # recursive delegation — explicit depth control preferred
}


@dataclass
class SubTask:
    """A task to delegate to a sub-agent.

    ``source`` (v0.99.40 Follow-up A): one of
    :data:`core.llm.adapters.CONCRETE_SOURCES` (``"payg"`` / ``"subscription"`` /
    ``"adapter"``) or empty to inherit the parent loop's default
    (``"payg"``). The spawned worker's :class:`AgenticLoop` uses
    :func:`core.llm.adapters.resolve_for` to pick the concrete
    :class:`LLMAdapter` (PR-MAINPATH-67 deleted the legacy provider-only
    ``resolve_agentic_adapter`` fallback). The picker
    (``plugins/seed_generation/picker.py``) translates its
    ``RoleBinding.source`` into one of the concrete values via
    :func:`binding_to_adapter_source`.
    """

    task_id: str
    description: str
    task_type: str  # "analyze", "search", "compare"
    args: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None  # Explicit agent override
    # PR-SUBAGENT-ROLES (2026-07-02) — built-in capability role
    # (``core.agent.subagent_roles.SUBAGENT_ROLES``). When set to a
    # registered role, the spawned worker's tool surface is narrowed to
    # the role's allowlist (via the denied_tools rail) and the parent
    # validates the result against the role's pydantic output model at
    # the parse site. Empty / unknown role = legacy behaviour unchanged
    # (opt-in registry).
    role: str = ""
    source: str = ""  # adapter source; empty lets worker infer from provider
    # PR-VOTER-PROVIDER-WIRE (2026-05-25) — per-task model override.
    # Pre-fix every SubTask inherited ``worker_model = settings.model``
    # (or the AgentDefinition's model if ``agent_ctx`` resolved). That
    # silently mis-routed callers that needed a per-call binding —
    # e.g. ranker.py:285 spawns one SubTask per voter, each carrying
    # the voter's distinct ``(model, provider, source)`` triple, but
    # the dispatch path only honored ``source``; ``worker_model`` fell
    # back to the parent's default → ``_resolve_provider(worker_model)``
    # returned the wrong provider key → ``resolve_for(provider, source)``
    # picked the wrong adapter (smoke 17 RESUME evidence: voter binding
    # ``claude-cli`` voter dispatched via ``codex-cli`` subprocess
    # adapter, because the parent's default model resolved to
    # ``openai-codex`` provider via ``_PROVIDER_NORMALIZATION``).
    # Empty preserves back-compat: callers that don't need per-task
    # override (the common case) still inherit settings/agent_ctx.
    model: str = ""
    # PR-JSON-WIRE (2026-05-25) — per-task JSON Schema that constrains
    # the spawned LLM call's response to the role's expected shape.
    # Threads through ``WorkerRequest.response_schema`` →
    # ``AgenticLoop.response_schema`` → ``AdapterCallRequest.response_schema``
    # → claude-cli ``--json-schema`` / codex-cli ``--output-schema``.
    # Without forcing, structured-output roles (pilot / proximity /
    # critic / evolver / meta_reviewer) regularly hit invalid-JSON
    # responses (smoke 14 pilot: LLM emitted ``...all zero...``
    # prose ellipsis inside a JSON object). Empty None preserves
    # back-compat — caller without a schema still gets free-form text.
    response_schema: dict[str, Any] | None = None
    # PR-CODEX-GPT55-OUTPUT-EMIT (2026-05-26) — per-task reasoning
    # effort override. Empty string preserves the legacy
    # difficulty-driven path (``_DIFFICULTY_TO_EFFORT`` →
    # ``settings.agentic_effort`` fallback). When set, wins over both
    # ``task.difficulty`` and ``settings.agentic_effort`` — used by
    # the ranker voter pathway to pin ``effort="none"`` (Sprint G,
    # 2026-05-26) because the vote task (single A/B/tie + 1-sentence
    # rationale) is a classification, not a multi-step reasoning
    # problem. Smoke 20 evidence: 36 codex-oauth-empty-text dumps at
    # ``effort="medium"`` (the silent SubTask default) where gpt-5.5
    # burned its entire output budget on encrypted reasoning items
    # and emitted zero message text, collapsing the ranker phase.
    # Smoke 21 confirmed the same failure mode under ``effort="low"``
    # (PR-CODEX-GPT55-OUTPUT-EMIT), so Sprint G dropped to
    # ``effort="none"`` — ctx7 OpenAI Responses API "Sampling
    # Parameters" registers ``"none"`` as the documented mechanism
    # to disable reasoning entirely on reasoning-capable models so
    # the model emits user-facing text directly.
    effort: str = ""


@dataclass
class SubResult:
    """Result from a sub-agent execution.

    PR-SEEDGEN-TOKENS (2026-05-30) — ``prompt_tokens`` / ``completion_tokens``
    / ``usd_spent`` carry the sub-agent's LLM usage so fan-out roles
    (generator / ranker / pilot) and single-shot roles can sum it into
    their returned ``SeedAgentResult``. These are 0 for subscription /
    CLI-routed calls (the subscription path does not expose token usage).
    """

    task_id: str
    description: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    # LLM usage for this sub-agent (0 for subscription calls — not faked).
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_spent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


class ErrorCategory(StrEnum):
    """Sub-agent error classification for retry policy."""

    TIMEOUT = "timeout"
    API_ERROR = "api_error"
    VALIDATION = "validation"
    RESOURCE = "resource"
    DEPTH_EXCEEDED = "depth_exceeded"
    UNKNOWN = "unknown"


@dataclass
class SubAgentResult:
    """Standardized result from sub-agent execution (P2-A).

    Every sub-agent returns this format, enabling:
    - Consistent LLM parsing (``summary`` always present)
    - Token guard (``summary`` preserved on truncation)
    - Error classification + retry decisions
    - Depth tracking for recursive orchestration
    """

    task_id: str
    task_type: str
    status: Literal["ok", "error", "timeout", "partial"] = "ok"
    depth: int = 0
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    token_usage: dict[str, int] | None = None
    children_count: int = 0
    error_category: str | None = None
    error_message: str | None = None
    retryable: bool = False
    announced: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @property
    def success(self) -> bool:
        return self.status == "ok"


@dataclass
class SubagentRunRecord:
    """Track parent-child relationship (OpenClaw Spawn pattern)."""

    run_id: str
    task_id: str
    child_session_key: str
    parent_session_key: str
    task_type: str
    started_at: float = 0.0
    completed_at: float = 0.0
    outcome: str = "pending"  # pending | ok | error


class SubAgentManager:
    """Delegate tasks to parallel sub-agents using IsolatedRunner.

    Orchestration features:
    - **TaskGraph**: DAG-based dependency tracking per sub-task.
    - **HookSystem**: Emits SUBAGENT_STARTED/COMPLETED/FAILED events.
    - **Dedup**: Filters duplicate task_id submissions via seen-set.
    - **AgentRegistry**: Resolves agent definitions for context injection.
    - **Toolkit-scoped capability** (P2-B revised, 2026-06-11 Codex audit):
      subprocess workers receive native tool handlers resolved from the
      declared toolkit (``core/agent/worker.py``). The ``mcp_manager`` /
      ``skill_registry`` references held here are for in-process use only
      and are NOT serialized to workers. Controlled by ``depth`` /
      ``max_depth``.
    """

    def __init__(
        self,
        runner: IsolatedRunner,
        task_handler: Any | None = None,
        *,
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — raised
        # 120 → 600 (10 min) on operator directive ("야심차게 잡아도 돼.
        # 300초 그이상으로 잡아"). Matches the per-agent-run wall-clock
        # convergence from openclaw (`agents/timeout.ts:3` 48h default)
        # while still leaving room for the IsolationConfig outer cap.
        # 120s was too tight for tool-using sub-agents — smoke 16
        # evolver TimeoutError surfaced at 122s in
        # ``plan.decompose_async``. Pilot's 90s Petri audit alone
        # leaves <30s for plan + tool overhead at 120s; 600s gives
        # multi-round tool reasoning the headroom it needs. Override
        # via ``GEODE_SUBAGENT_TIMEOUT_S`` env (clamped [10, 3600]).
        timeout_s: float = 600.0,
        hooks: HookSystem | None = None,
        agent_registry: AgentRegistry | None = None,
        parent_session_key: str = "",
        # P2-B: Full AgenticLoop inheritance
        action_handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        depth: int = 0,
        max_depth: int = 1,  # Depth=1 enforced (Claude Code pattern: sub-agents cannot recurse)
        max_total_subagents: int = 15,  # session-wide cap on total sub-agents spawned
        # Sandbox hardening: tool scope restriction
        denied_tools: set[str] | None = None,
        time_budget_s: float = 0.0,
        # Sandbox: additional working directories for sub-agent scope
        working_dirs: list[str] | None = None,
    ) -> None:
        self._runner = runner
        self._task_handler = task_handler
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — env override
        # for the wall-clock cap, clamped to a sane range so a bad
        # `GEODE_SUBAGENT_TIMEOUT_S=abc` or `=99999999` doesn't break
        # subprocess accounting. 10s lower bound matches the smoke
        # smallest phase (proximity ~0.2ms is fine; literature_review
        # ~30s on cache hit needs > 10s headroom).
        self._timeout_s = _resolve_timeout_s(timeout_s)
        self._time_budget_s = time_budget_s
        self._hooks = hooks
        self._agent_registry = agent_registry
        self._parent_session_key = parent_session_key
        self._run_records: dict[str, SubagentRunRecord] = {}
        self._records_lock = threading.Lock()
        # P2-B fields
        self._action_handlers = action_handlers
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._depth = depth
        self._max_depth = max_depth
        self._max_total_subagents = max_total_subagents
        # Monotonic per-session spawn counter, guarded by ``_records_lock``.
        # SubAgentManager is built once per session (services.py
        # ``_build_sub_agent_manager``), so this counts the session total.
        self._spawned_total = 0
        # Sandbox hardening: filter denied tools from action_handlers
        self._denied_tools: set[str] = denied_tools or set()
        # Sandbox: additional working directories for sub-agent
        self._working_dirs = working_dirs or []
        # Announce mechanism (OpenClaw Spawn+Announce pattern)
        self._announce_enabled = bool(parent_session_key)

    async def adelegate(
        self,
        tasks: list[SubTask],
        *,
        on_progress: Callable[[SubResult], None] | None = None,
        on_activity: Callable[[dict[str, Any]], None] | None = None,
        announce: bool = True,
        default_model: str = "",
    ) -> list[SubResult]:
        """Async sibling of :meth:`delegate` — ``asyncio.gather`` based fan-out.

        PR-Async-Phase-C (2026-05-22) — replaces the polling collection loop
        with native async. Each task runs in its own
        :class:`IsolatedRunner.arun` coroutine (which uses ``asyncio.to_thread``
        to off-load the blocking subprocess/thread wait); ``asyncio.gather``
        completes when all tasks finish. Backpressure is suspended-coroutine
        cost (~1 KB) instead of thread/subprocess RSS — fits cleanly with
        async caller paths (Pipeline.arun, async tool handlers).

        Contract parity with sync :meth:`delegate`: same depth guard, dedup,
        sandbox directory expansion, hooks, run-record bookkeeping, announce
        semantics. Only the *waiting* mechanic differs (asyncio.gather vs
        polling).

        Fleet view Stage 1.5 — when ``on_activity`` is provided (only the
        interactive ``delegate_task`` turn path passes it), each spawned worker
        is asked to emit live per-tool activity (``WorkerRequest.emit_activity``)
        and every ``{"type":"activity", ...}`` line the worker streams before its
        result is forwarded to ``on_activity`` as it arrives. ``None`` (seed-gen /
        headless / tests) keeps the pure single-result-line worker contract.
        """
        import asyncio

        if not tasks:
            return []

        # Explicit depth guard (defense-in-depth alongside denied_tools)
        if self._depth >= self._max_depth:
            log.warning(
                "Sub-agent depth limit reached (%d/%d), rejecting %d tasks",
                self._depth,
                self._max_depth,
                len(tasks),
            )
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error=f"Depth limit exceeded ({self._depth}/{self._max_depth})",
                )
                for t in tasks
            ]

        tasks = self._deduplicate(tasks)
        if not tasks:
            log.info("All tasks coalesced — nothing to execute")
            return []

        # Session-wide total sub-agent cap (settings.max_total_subagents).
        # Reserve under the records lock so concurrent adelegate calls in the
        # same session cannot jointly overshoot the budget. Overflow tasks get
        # an explicit failed SubResult rather than silently spawning.
        cap_overflow: list[SubResult] = []
        with self._records_lock:
            remaining = self._max_total_subagents - self._spawned_total
            accepted = tasks if remaining >= len(tasks) else tasks[: max(remaining, 0)]
            self._spawned_total += len(accepted)
        if len(accepted) < len(tasks):
            rejected = tasks[len(accepted) :]
            log.warning(
                "Session sub-agent cap reached (%d/%d) — rejecting %d task(s)",
                self._spawned_total,
                self._max_total_subagents,
                len(rejected),
            )
            cap_overflow = [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error=f"Session sub-agent limit reached ({self._max_total_subagents})",
                )
                for t in rejected
            ]
        if not accepted:
            return cap_overflow
        tasks = accepted

        # Expand sandbox for sub-agent working directories
        added_dirs: list[Path] = []
        if self._working_dirs:
            from core.tools.sandbox import add_working_directory

            for dir_str in self._working_dirs:
                dir_path = Path(dir_str)
                if dir_path.is_dir():
                    add_working_directory(dir_path)
                    added_dirs.append(dir_path)

        graph = self._build_task_graph(tasks)

        # Build per-task IsolationConfig + run-record + hook STARTED in
        # the same shape sync delegate uses.
        from core.memory.session_key import build_subagent_session_key

        per_task_setup: list[tuple[SubTask, Any, IsolationConfig]] = []
        for task in tasks:
            graph.mark_running(task.task_id)
            self._emit_hook(HookEvent.SUBAGENT_STARTED, task)

            child_key = build_subagent_session_key(
                task.args.get("subject_id", task.args.get("subject", "unknown")), task.task_id
            )

            import uuid as _uuid

            record = SubagentRunRecord(
                run_id=_uuid.uuid4().hex[:12],
                task_id=task.task_id,
                child_session_key=child_key,
                parent_session_key=self._parent_session_key,
                task_type=task.task_type,
                started_at=time.time(),
            )
            with self._records_lock:
                self._run_records[task.task_id] = record
                if len(self._run_records) > 200:
                    oldest_key = next(iter(self._run_records))
                    self._run_records.pop(oldest_key, None)

            config = IsolationConfig(
                session_id=task.task_id,
                timeout_s=self._timeout_s,
                post_to_main=False,
                prefix=f"SubAgent:{task.task_type}",
                metadata={
                    "description": task.description,
                    "task_type": task.task_type,
                    "child_session_key": child_key,
                },
            )
            fn_or_request: Any
            if self._action_handlers is not None:
                fn_or_request = self._build_worker_request(
                    task,
                    default_model=default_model,
                    emit_activity=on_activity is not None,
                )
            else:
                # _execute_subtask is bound method; arun expects callable
                # passed via args/kwargs. The thread-mode path is sync.
                fn_or_request = self._execute_subtask
            per_task_setup.append((task, fn_or_request, config))

        # Launch ALL tasks concurrently via asyncio.gather over IsolatedRunner.arun.
        # arun's signature: arun(fn_or_request, *, args=(), kwargs=None, config=None)
        # For the legacy thread mode, args=(task,) carries the SubTask payload.
        async def _run_one(task: SubTask, fn_or_request: Any, config: IsolationConfig) -> SubResult:
            try:
                if self._action_handlers is not None:
                    # Subprocess mode — WorkerRequest carries the payload.
                    # Stage 1.5 — forward live activity lines (no-op when the
                    # caller didn't request activity: emit_activity stays False).
                    isolation = await self._runner.arun(
                        fn_or_request, config=config, on_activity=on_activity
                    )
                else:
                    # Thread mode — legacy callable + SubTask arg.
                    isolation = await self._runner.arun(fn_or_request, args=(task,), config=config)
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("adelegate: arun raised for %s — %s", task.task_id, exc)
                isolation = None
            sub_result = self._to_sub_result(task, isolation)
            if sub_result.success:
                graph.mark_completed(task.task_id, result=sub_result.output)
                self._emit_hook(HookEvent.SUBAGENT_COMPLETED, task, sub_result=sub_result)
            else:
                graph.mark_failed(task.task_id, error=sub_result.error or "unknown")
                # PR-COMM-3b — pass ``sub_result`` so the agent_runtime_state
                # writer receives ``status="failed"``. Pre-fix only ``error``
                # was passed and the status field was silently missing on
                # production failures (Codex MCP review catch).
                self._emit_hook(
                    HookEvent.SUBAGENT_FAILED,
                    task,
                    sub_result=sub_result,
                    error=sub_result.error,
                )
            if on_progress is not None:
                try:
                    on_progress(sub_result)
                except Exception:
                    log.warning(
                        "on_progress callback failed for %s",
                        task.task_id,
                        exc_info=True,
                    )
            return sub_result

        try:
            results: list[SubResult] = await asyncio.gather(
                *[
                    _run_one(task, fn_or_request, config)
                    for task, fn_or_request, config in per_task_setup
                ]
            )

            # Update run records with outcomes (G7 observability)
            now = time.time()
            with self._records_lock:
                for sub_result in results:
                    rec = self._run_records.get(sub_result.task_id)
                    if rec is not None:
                        rec.completed_at = now
                        rec.outcome = "ok" if sub_result.success else "error"

            # Announce completed results to parent (OpenClaw Spawn+Announce)
            if announce and self._announce_enabled and self._parent_session_key:
                for sub_result in results:
                    summary = ""
                    if sub_result.success:
                        summary = sub_result.output.get("summary", "") if sub_result.output else ""
                        if not summary:
                            summary = (
                                str(sub_result.output)[:200] if sub_result.output else "completed"
                            )
                    else:
                        summary = sub_result.error or "failed"
                    agent_result = SubAgentResult(
                        task_id=sub_result.task_id,
                        task_type=sub_result.description,
                        status="ok" if sub_result.success else "error",
                        summary=summary,
                        data=sub_result.output,
                        duration_ms=sub_result.duration_ms,
                        error_message=sub_result.error,
                    )
                    self._announce_result(self._parent_session_key, agent_result)
        finally:
            # PR-Async-Phase-C step 4b fix-up — sandbox cleanup must run
            # even when the caller cancels ``adelegate`` mid-gather; a
            # missed ``remove_working_directory`` would leak the
            # sub-agent's writable paths into the parent's sandbox.
            if added_dirs:
                from core.tools.sandbox import remove_working_directory

                for dir_path in added_dirs:
                    remove_working_directory(dir_path)

        succeeded = sum(1 for r in results if r.success)
        log.info(
            "SubAgent async batch complete: %d/%d succeeded",
            succeeded,
            len(results),
        )
        # Append any tasks rejected by the session cap so the caller sees one
        # SubResult per submitted task (spawned outcomes + cap rejections).
        return list(results) + cap_overflow

    @property
    def hooks(self) -> HookSystem | None:
        return self._hooks

    def get_run_records(self) -> dict[str, SubagentRunRecord]:
        """Return a snapshot of all run records for observability."""
        with self._records_lock:
            return dict(self._run_records)

    def _announce_result(self, parent_session_key: str, child_result: SubAgentResult) -> None:
        """Announce a completed sub-agent result to the parent session.

        Pushes the result into the module-level ``_announce_queue`` so
        the parent AgenticLoop can pick it up on the next round via
        ``drain_announced_results()``.  Marks ``child_result.announced``
        to prevent double-announce.

        OpenClaw Spawn+Announce pattern: child completes -> parent is
        notified asynchronously -> parent injects summary into context.
        """
        with _announce_lock:
            if child_result.announced:
                return
            child_result.announced = True
            _announce_queue.setdefault(parent_session_key, []).append(child_result)
            _announce_timestamps[parent_session_key] = time.time()
        log.debug(
            "Announced result: task_id=%s to parent=%s (status=%s)",
            child_result.task_id,
            parent_session_key,
            child_result.status,
        )

    def _build_worker_request(
        self, task: SubTask, *, default_model: str = "", emit_activity: bool = False
    ) -> WorkerRequest:
        """Build a WorkerRequest for subprocess execution (Phase 2).

        The subprocess inherits API keys via env vars. Model config and
        denied tools are passed explicitly.

        ``emit_activity`` (fleet-view Stage 1.5) is threaded onto the request so
        the worker installs its stdout activity side-channel. Default False keeps
        the legacy pure single-result-line contract for seed-gen / headless.
        """
        # Use the reloaded singleton (config.toml overlay is applied at
        # session-create via reload_settings_from_disk) so [subagent] max_tokens
        # and [model] actually reach the worker — a fresh ``Settings()`` sees
        # env + defaults only and silently drops every config.toml value.
        from core.config import _resolve_provider, settings

        denied_set = set(self._denied_tools) | {"delegate_task"}

        # PR-SUBAGENT-ROLES (2026-07-02) — resolve the built-in capability
        # role. Unknown role names log a WARNING and fall through to the
        # legacy default surface (the registry is opt-in; a typo must not
        # zero out the sub-agent). A registered role narrows the tool
        # surface via the EXISTING denied_tools rail (denied = all −
        # allowed) — computed here, enforced by the worker's ToolExecutor.
        from core.agent.subagent_roles import (
            SUBAGENT_ROLES,
            get_role,
            output_schema_line,
            role_denied_tools,
        )

        role_def = get_role(task.role) if task.role else None
        if task.role and role_def is None:
            log.warning(
                "delegate_task: unknown sub-agent role %r — running with the "
                "default tool surface (known roles: %s)",
                task.role,
                sorted(SUBAGENT_ROLES),
            )
        if role_def is not None:
            from core.tools.base import load_all_tool_definitions

            all_tool_names = [d["name"] for d in load_all_tool_definitions()]
            denied_set |= role_denied_tools(role_def, all_tool_names)
        denied = list(denied_set)

        # Adaptive effort based on task difficulty hint
        _DIFFICULTY_TO_EFFORT = {"low": "low", "medium": "medium", "high": "high"}
        difficulty = getattr(task, "difficulty", "medium")
        task_effort = _DIFFICULTY_TO_EFFORT.get(difficulty, settings.agentic_effort)
        # PR-CODEX-GPT55-OUTPUT-EMIT (2026-05-26) — explicit per-task
        # effort override wins over both ``task.difficulty`` and
        # ``settings.agentic_effort``. Empty string falls through to
        # the difficulty/settings path (legacy behaviour). The ranker
        # voter SubTasks set this to ``"low"`` to keep gpt-5.5 from
        # burning its entire output budget on encrypted reasoning for
        # a classification call (smoke 20: 36 empty-text dumps).
        if task.effort:
            task_effort = task.effort

        # S2-wire (2026-05-18): resolve AgentDefinition if task.agent is set
        # so the worker can apply the agent's system_prompt + tools + model.
        # Pre-S2-wire, _resolve_agent was only called by the legacy task-
        # handler path; the production subprocess path defaulted to GEODE's
        # generic prompt regardless of task.agent.
        agent_ctx = self._resolve_agent(task)
        agent_name = ""
        agent_system_prompt = ""
        agent_allowed_tools: list[str] = []
        # CSP-1 (2026-05-22) — propagate the AgentDefinition's
        # ``toolkit:`` frontmatter into the worker so
        # ``filter_handlers`` can expand it via
        # ``core/tools/toolkits.toml``. Empty string when the agent
        # didn't declare one — the worker falls back to
        # ``agent_allowed_tools`` (legacy) or the ``_default`` toolkit.
        agent_toolkit = ""
        # PR-SUBAGENT-MODEL-ALIGN (2026-06-14) — base model is the loop's LIVE
        # model (forwarded from the delegate_task ToolContext) so delegation
        # tracks a mid-session ``/model`` switch, symmetric with web_search.
        # ``settings.model`` is the fallback for callers without a live context
        # (services bootstrap / tests). AgentDefinition + per-task overrides
        # below still win, preserving the voter/agent-model semantics.
        worker_model = default_model or settings.model
        if agent_ctx is not None:
            agent_name = str(agent_ctx.get("agent_name", ""))
            agent_system_prompt = str(agent_ctx.get("system_prompt", ""))
            tools_raw = agent_ctx.get("tools") or []
            agent_allowed_tools = [str(t) for t in tools_raw]
            toolkit_raw = agent_ctx.get("toolkit")
            if toolkit_raw:
                agent_toolkit = str(toolkit_raw)
            # AgentDefinition model override wins over settings default.
            if agent_ctx.get("model"):
                worker_model = str(agent_ctx["model"])
        # PR-VOTER-PROVIDER-WIRE (2026-05-25) — per-task model override
        # is the strongest signal: it comes from the live binding the
        # caller already resolved (ranker picker → voter.model). Wins
        # over both ``settings.model`` and AgentDefinition's model.
        # Empty string preserves legacy behaviour (settings/agent_ctx).
        if task.model:
            worker_model = task.model

        # PR-SUBAGENT-ROLES (2026-07-02) — a registered role supplies the
        # tool ALLOWLIST when the AgentDefinition declared neither a
        # toolkit nor a tools: list. Without this, filter_handlers' Tier 3
        # would apply the minimal ``_default`` toolkit (read_document +
        # grep_files) and silently strip role tools (verifier's run_bash,
        # repo_researcher's glob_files/session_search). The denied set
        # computed above remains the hard rail either way — an agent
        # toolkit cannot re-open tools outside the role's allowlist.
        description = task.description
        if role_def is not None:
            if not agent_toolkit and not agent_allowed_tools:
                agent_allowed_tools = list(role_def.tools)
            # Generation-side pressure: one line carrying the role's
            # output JSON schema, appended to the prompt the worker
            # assembles from ``description``. Parent-side validation at
            # ``_to_sub_result`` is the enforcement; this line raises the
            # odds the first response already conforms.
            schema_line = output_schema_line(role_def)
            if schema_line:
                description = f"{description}\n\n{schema_line}"

        # Sub-agent lineage (2026-05-21) — capture the calling parent
        # loop's session_id from the ContextVar bound in
        # ``AgenticLoop._emit_session_start_signals``. Falls back to
        # empty for top-level / test contexts where no loop is bound.
        # ``parent_session_key`` is the SubAgentManager construction
        # kwarg (or empty when the manager was built at gateway
        # startup without a parent context).
        from core.agent.cognitive_state_ctx import get_session_id

        parent_uuid = get_session_id()

        return WorkerRequest(
            task_id=task.task_id,
            task_type=task.task_type,
            description=description,
            args=task.args,
            denied_tools=denied,
            model=worker_model,
            provider=_resolve_provider(worker_model),
            timeout_s=self._timeout_s,
            time_budget_s=self._time_budget_s,
            thinking_budget=settings.agentic_thinking_budget,
            subagent_max_tokens=settings.subagent_max_tokens,
            effort=task_effort,
            agent_name=agent_name,
            agent_system_prompt=agent_system_prompt,
            agent_allowed_tools=agent_allowed_tools,
            toolkit=agent_toolkit,
            parent_session_key=self._parent_session_key,
            parent_session_id=parent_uuid,
            source=task.source,
            # PR-JSON-WIRE (2026-05-25) — thread per-task JSON Schema
            # from SubTask down to the worker subprocess for
            # structured-output forcing.
            response_schema=task.response_schema,
            # Fleet view Stage 1.5 — ask the worker to stream live per-tool
            # activity when the caller wired an activity callback.
            emit_activity=emit_activity,
        )

    def _resolve_agent(self, task: SubTask) -> dict[str, Any] | None:
        """Resolve agent context.

        Priority: task.agent > _TYPE_AGENT_MAP > None.
        """
        if self._agent_registry is None:
            return None
        agent_name = task.agent or _TYPE_AGENT_MAP.get(task.task_type)
        if agent_name is None:
            return None
        agent_def = self._agent_registry.get(agent_name)
        if agent_def is None:
            log.debug("Agent '%s' not found in registry", agent_name)
            return None
        # ADR-012 M2 (2026-05-21) — agent-contracts.json policy override.
        # role / system_prompt / tools 만 mutate 가능 (model 은 Tier 2).
        # 정책 부재 시 agent_def 그대로 — no behavior change.
        from core.agent.agent_contracts_policy import (
            _load_agent_contracts_override,
            apply_agent_contracts_policy,
        )

        agent_def = apply_agent_contracts_policy(agent_def, _load_agent_contracts_override())
        return {
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "system_prompt": agent_def.system_prompt,
            "tools": agent_def.tools,
            "toolkit": agent_def.toolkit,
            "model": agent_def.model,
        }

    def _build_task_graph(self, tasks: list[SubTask]) -> TaskGraph:
        graph = TaskGraph()
        for task in tasks:
            graph.add_task(
                Task(
                    task_id=task.task_id,
                    name=task.description,
                    metadata={
                        "task_type": task.task_type,
                        **task.args,
                    },
                )
            )
        return graph

    def _deduplicate(self, tasks: list[SubTask]) -> list[SubTask]:
        """Filter duplicate task_id submissions via seen-set."""
        seen: set[str] = set()
        unique: list[SubTask] = []
        for task in tasks:
            if task.task_id not in seen:
                seen.add(task.task_id)
                unique.append(task)
            else:
                log.debug("Dedup: skipping duplicate task_id=%s", task.task_id)
        return unique

    def _emit_hook(
        self,
        event: HookEvent,
        task: SubTask,
        *,
        sub_result: SubResult | None = None,
        error: str | None = None,
    ) -> None:
        if self._hooks is None:
            return
        data: dict[str, Any] = {
            "source": "sub_agent",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "description": task.description,
        }
        # PR-COMM-3b (2026-05-24) — surface the active RunTranscript's
        # ``component`` so the SQLite agent_runtime_state writer (registered
        # below in this PR) can persist "what subsystem this sub-agent was
        # serving" (seed-generation / petri-audit / agentic_loop / ...).
        # Falls back to "agentic_loop" when there's no active transcript
        # (REPL / ad-hoc spawn outside an orchestrator scope).
        try:
            from core.self_improving.loop.observe.run_transcript import current_run_transcript

            run_transcript = current_run_transcript()
            data["component"] = (
                run_transcript.component if run_transcript is not None else "agentic_loop"
            )
        except Exception:
            data["component"] = "agentic_loop"
        if sub_result is not None:
            data["duration_ms"] = sub_result.duration_ms
            data["success"] = sub_result.success
            # PR-COMM-3b — derive a stable status string for the
            # ``last_run_status`` column. Matches the seed-generation
            # cycle's own status vocabulary.
            data["status"] = "completed" if sub_result.success else "failed"
            # Include result summary in SUBAGENT_COMPLETED hook data
            # (OpenClaw Announce pattern — hooks carry the completion summary)
            if event == HookEvent.SUBAGENT_COMPLETED:
                summary = sub_result.output.get("summary", "") if sub_result.output else ""
                if not summary:
                    summary = str(sub_result.output)[:200] if sub_result.output else ""
                data["summary"] = summary
        if error is not None:
            data["error"] = error
        try:
            self._hooks.trigger(event, data)
        except Exception:
            log.warning(
                "Hook trigger failed for %s on task %s",
                event.value,
                task.task_id,
                exc_info=True,
            )

    def _execute_subtask(self, task: SubTask) -> str:
        """Execute a single sub-task in thread mode (legacy handler path only).

        Production sub-agents (P2-B with action_handlers) use subprocess via
        WorkerRequest instead. This method is kept for backward compatibility
        with tests and legacy task_handler consumers.

        NOTE: Thread mode cannot enforce denied_tools because the task_handler
        callback is opaque. Use subprocess mode (action_handlers) for security.
        """
        if self._denied_tools:
            raise RuntimeError(
                f"Thread mode cannot enforce denied_tools for task {task.task_id}. "
                "Use subprocess mode (action_handlers) for security."
            )

        from core.memory.session_key import build_subagent_session_key

        child_key = build_subagent_session_key(
            task.args.get("subject_id", task.args.get("subject", "unknown")), task.task_id
        )
        _subagent_context.is_subagent = True
        _subagent_context.child_session_key = child_key
        try:
            return self._execute_with_handler(task)
        except Exception as exc:
            log.error("SubTask %s failed: %s", task.task_id, exc, exc_info=True)
            return json.dumps({"error": str(exc)})
        finally:
            _subagent_context.is_subagent = False
            _subagent_context.child_session_key = ""

    def _execute_with_handler(self, task: SubTask) -> str:
        """Legacy path: simple task_handler function call."""
        if self._task_handler is None:
            return json.dumps({"error": "No task handler configured"})
        agent_context = self._resolve_agent(task)
        try:
            result: dict[str, Any] = self._task_handler(
                task.task_type,
                task.args,
                agent_context=agent_context,
            )
        except TypeError:
            result = self._task_handler(task.task_type, task.args)
        return json.dumps(result, default=str)

    def _to_sub_result(self, task: SubTask, isolation: IsolationResult | None) -> SubResult:
        if isolation is None:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=f"Timeout after {self._timeout_s}s",
            )
        if not isolation.success:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=isolation.error,
                duration_ms=isolation.duration_ms,
                # PR-SEEDGEN-TOKENS — a sub-agent can burn tokens before
                # failing; forward whatever the worker reported (0 for
                # subscription calls) so cost accounting stays honest.
                prompt_tokens=isolation.prompt_tokens,
                completion_tokens=isolation.completion_tokens,
                usd_spent=isolation.usd_spent,
            )
        output: dict[str, Any]
        raw_text = isolation.output or ""

        # PR-SUBAGENT-ROLES (2026-07-02) — when the task ran under a
        # registered role with an output model, validate here at the
        # parse site instead of the legacy best-effort JSON scavenging.
        # ``validate_role_output`` NEVER raises: it returns either
        # ``{"validated": True, "data": ...}`` or an observable
        # ``{"validated": False, "error": ..., "raw": ...}`` structured
        # error (+ log.warning inside) — no JSONDecodeError reaches the
        # loop, no un-validated garbage propagates as a role result.
        if task.role:
            from core.agent.subagent_roles import get_role, validate_role_output

            role_def = get_role(task.role)
            if role_def is not None:
                validated_output = validate_role_output(role_def, raw_text)
                if validated_output is not None:
                    return SubResult(
                        task_id=task.task_id,
                        description=task.description,
                        success=True,
                        output=validated_output,
                        duration_ms=isolation.duration_ms,
                        prompt_tokens=isolation.prompt_tokens,
                        completion_tokens=isolation.completion_tokens,
                        usd_spent=isolation.usd_spent,
                    )

        candidate_text = _strip_json_codeblock(raw_text) if raw_text else raw_text
        try:
            parsed = json.loads(candidate_text) if candidate_text else {}
            output = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, RecursionError):
            # PR-HANDOFF-SCHEMAS — last-resort scan for an embedded
            # balanced {...} JSON object before falling back to raw.
            # Smoke 15 surfaced tool-using sub-agents that ended with
            # prose but had a valid JSON block somewhere earlier in
            # the response.
            embedded = _last_balanced_json_object(raw_text)
            if embedded is not None:
                try:
                    parsed_emb = json.loads(embedded)
                    output = parsed_emb if isinstance(parsed_emb, dict) else {"raw": raw_text}
                except (json.JSONDecodeError, RecursionError):
                    output = {"raw": raw_text}
            else:
                output = {"raw": raw_text}
        return SubResult(
            task_id=task.task_id,
            description=task.description,
            success=True,
            output=output,
            duration_ms=isolation.duration_ms,
            # PR-SEEDGEN-TOKENS — forward worker LLM usage to fan-out roles.
            prompt_tokens=isolation.prompt_tokens,
            completion_tokens=isolation.completion_tokens,
            usd_spent=isolation.usd_spent,
        )

    def _to_agent_result(self, task: SubTask, isolation: IsolationResult | None) -> SubAgentResult:
        """Convert IsolationResult to standardized SubAgentResult (P2-A)."""
        if isolation is None:
            return SubAgentResult(
                task_id=task.task_id,
                task_type=task.task_type,
                status="timeout",
                summary=f"Task timed out after {self._timeout_s}s",
                error_category=ErrorCategory.TIMEOUT,
                error_message=f"Timeout after {self._timeout_s}s",
                retryable=True,
            )
        if not isolation.success:
            category = self._classify_error(isolation.error or "")
            return SubAgentResult(
                task_id=task.task_id,
                task_type=task.task_type,
                status="error",
                summary=f"Failed: {isolation.error or 'unknown'}",
                error_category=category,
                error_message=isolation.error,
                retryable=category in {ErrorCategory.TIMEOUT, ErrorCategory.API_ERROR},
                duration_ms=isolation.duration_ms,
            )
        result_payload: dict[str, Any]
        raw_text = isolation.output or ""
        candidate_text = _strip_json_codeblock(raw_text) if raw_text else raw_text
        try:
            parsed = json.loads(candidate_text) if candidate_text else {}
            result_payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, RecursionError):
            # PR-HANDOFF-SCHEMAS — embedded {...} fallback (see
            # _last_balanced_json_object docstring).
            embedded = _last_balanced_json_object(raw_text)
            if embedded is not None:
                try:
                    parsed_emb = json.loads(embedded)
                    result_payload = (
                        parsed_emb if isinstance(parsed_emb, dict) else {"raw": raw_text}
                    )
                except (json.JSONDecodeError, RecursionError):
                    result_payload = {"raw": raw_text}
            else:
                result_payload = {"raw": raw_text}
        summary = result_payload.get("summary", "")
        if not summary:
            summary = str(result_payload.get("tier", result_payload.get("status", "")))[:200]
        return SubAgentResult(
            task_id=task.task_id,
            task_type=task.task_type,
            status="ok",
            summary=summary,
            data=result_payload,
            duration_ms=isolation.duration_ms,
        )

    @staticmethod
    def _classify_error(error_msg: str) -> str:
        """Classify error message into ErrorCategory."""
        lower = error_msg.lower()
        if "timeout" in lower or "timed out" in lower:
            return ErrorCategory.TIMEOUT
        if "api" in lower or "rate limit" in lower or "authentication" in lower:
            return ErrorCategory.API_ERROR
        if "validation" in lower or "required" in lower or "invalid" in lower:
            return ErrorCategory.VALIDATION
        if "memory" in lower or "disk" in lower or "resource" in lower:
            return ErrorCategory.RESOURCE
        if "depth" in lower:
            return ErrorCategory.DEPTH_EXCEEDED
        return ErrorCategory.UNKNOWN


DELEGATE_TOOL_DEFINITION: dict[str, Any] = load_tool_definition("delegate_task")

"""AgenticLoop — while(tool_use) agentic execution loop.

Claude Code-style agentic loop that continues until the LLM
emits end_turn (no more tool calls). All free-text user input
is routed directly here.

Supports:
- Multi-intent: "분석하고 비교해줘" → sequential tool calls
- Multi-turn: context preserved across interactions
- Self-correction: LLM can retry or adjust based on tool results
- Goal decomposition: compound requests auto-decomposed into sub-goal DAGs
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Set
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.config.policy_source import EMPTY_POLICY_SOURCES, PolicySourceBundle
from core.hooks import (
    HookAction,
    HookCorrelation,
    HookEvent,
    HookName,
    HookRegistry,
    HookSystem,
    LlmCallRequest,
    MiddlewareRegistry,
)
from core.llm.adapters.base import EmptyModelOutputError
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError
from core.tools.personal_data import PERSONAL_DATA_TOOLS
from core.ui.agentic_ui import OperationLogger
from core.ui.status import TextSpinner

from . import (
    _collaboration_mailbox,
    _context,
    _goal,
    _lifecycle,
    _model_switching,
    _planner_dispatch,
    _response,
)
from ._tool_factory import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,
    TOOL_LAZY_LOAD_THRESHOLD,
    get_agentic_tools,
)
from .models import (
    AgenticResult,
    TerminationReason,
    _context_exhausted_message,
    _ContextExhaustedError,
)

# Confidence-adaptive compute allocation — the reflection node's
# ``CognitiveState.confidence`` (0..1) steers how much extra LLM compute
# the loop spends on itself. High stable confidence stretches the
# reflection cadence (fewer belief-update calls); low confidence forces
# a reflection every round and edge-triggers a replan. Thresholds are
# deliberately module constants, not settings knobs — one adaptive
# on/off knob exists (``cognitive_reflection_adaptive``).
REFLECTION_STRETCH_CONFIDENCE = 0.8  # confidence >= → interval doubled
REFLECTION_FORCE_CONFIDENCE = 0.4  # confidence < → reflect every round
REPLAN_LOW_CONFIDENCE = 0.4  # confidence < → edge-triggered replan

if TYPE_CHECKING:
    from core.agent.capability_graph import CapabilityGraph
    from core.agent.task_preflight import TaskPreflight
    from core.llm.adapters.base import AdapterCallRequest
    from core.observability.run_event import RunEventSinkProvider
    from core.tools.plan import BoundToolPlan
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


def _validate_bound_request_rewrite(
    original: AdapterCallRequest,
    effective: AdapterCallRequest,
) -> None:
    """Fail closed when middleware widens or relabels a bound tool request."""
    if (
        effective.tool_plan_hash != original.tool_plan_hash
        or effective.tool_plan_generation != original.tool_plan_generation
    ):
        raise ValueError("LLM middleware cannot change bound tool plan identity")

    if effective.tools != original.tools:
        raise ValueError("LLM middleware cannot change bound tool specs")
    if effective.deferred_tool_names != original.deferred_tool_names:
        raise ValueError("LLM middleware cannot change bound deferred tools")
    if effective.allowed_tool_names != original.allowed_tool_names:
        raise ValueError("LLM middleware cannot change bound tool allowlist")
    if effective.denied_tool_names != original.denied_tool_names:
        raise ValueError("LLM middleware cannot change bound tool denylist")
    if effective.executable_tool_names != original.executable_tool_names:
        raise ValueError("LLM middleware cannot change bound executable tools")


_FAIL_FAST_VALUES = frozenset({"1", "true", "yes", "on"})
_FAIL_FAST_RETRY_DELAY_S = 1.0
_FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS = 3


def _fail_fast_adapter_errors_enabled() -> bool:
    return (
        os.environ.get("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "").strip().lower()
        in _FAIL_FAST_VALUES
    )


async def _acomplete_with_fail_fast_pre_execution_retry(
    adapter: Any,
    request: Any,
    *,
    on_retry: Callable[[Exception, int, int], Awaitable[None]] | None = None,
    complete: Callable[[Any, Any], Awaitable[Any]] | None = None,
) -> Any:
    """Retry bounded pre-execution failures without reopening completed tool work.

    Normal AgenticLoop calls already retry after ``_call_llm`` returns
    ``None``. Strict evaluator routes instead raise adapter errors immediately
    so infrastructure cannot become semantic output. Preserve that boundary
    while giving a connection-class stream failure one same-adapter retry. An
    empty completed response gets at most three total attempts because repeated
    GPT-5.4 subscription empties have occurred at the previous two-attempt
    boundary. Every attempt uses the identical request before tool execution.
    """

    async def invoke() -> Any:
        if complete is not None:
            return await complete(adapter, request)
        return await adapter.acomplete(request)

    try:
        return await invoke()
    except Exception as exc:
        if not _fail_fast_adapter_errors_enabled():
            raise
        from core.llm.adapters.dispatch import _is_connection_transient

        if isinstance(exc, EmptyModelOutputError):
            empty_errors = [exc]
            for attempt in range(2, _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS + 1):
                log.warning(
                    "AgenticLoop: fail-fast empty model output (%s); "
                    "retrying the same adapter (attempt %d/%d)",
                    type(empty_errors[-1]).__name__,
                    attempt,
                    _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS,
                )
                if on_retry is not None:
                    await on_retry(
                        empty_errors[-1],
                        attempt,
                        _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS,
                    )
                await asyncio.sleep(_FAIL_FAST_RETRY_DELAY_S * (attempt - 1))
                try:
                    result = await invoke()
                except EmptyModelOutputError as retry_error:
                    empty_errors.append(retry_error)
                    if attempt == _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS:
                        retry_error.include_actionable_attempts(empty_errors[:-1])
                        raise
                    continue
                for empty_error in empty_errors:
                    empty_error.mark_recovered()
                return result
            raise AssertionError("bounded empty-output retry loop did not terminate") from exc
        if not _is_connection_transient(exc):
            raise
        log.warning(
            "AgenticLoop: fail-fast transport error (%s); retrying the same adapter once",
            type(exc).__name__,
        )
        if on_retry is not None:
            await on_retry(exc, 2, 2)
        await asyncio.sleep(_FAIL_FAST_RETRY_DELAY_S)
        return await invoke()


def _saved_cwd_matches_current(stored_cwd: str, current_cwd: str) -> bool:
    """cwd-equality check for the claude-cli resume gate.

    Contract: True when either side is empty (no per-task cwd → skip the
    gate); otherwise ``Path.resolve()`` equality (normalises symlinks /
    ``..`` / trailing slashes). Resolution failure → False (force fresh
    session).
    """
    from pathlib import Path

    if not stored_cwd or not current_cwd:
        return True
    try:
        return Path(stored_cwd).resolve() == Path(current_cwd).resolve()
    except (OSError, RuntimeError):
        # resolution failure → mismatch (force fresh session)
        return False


def _load_prior_session_id(session_id: str) -> str:
    """Return the claude-cli session_id from this sub-agent's prior turn.

    Contract: claude-cli session storage is cwd-keyed, so the saved
    ``cwd`` must equal ``get_task_isolated_cwd()`` or the id is unusable.
    Returns ``""`` on cwd mismatch, missing session, or any I/O/parse
    error (force a fresh session — never crash, never resume a stale id).
    Reads SQLite runtime-state first, then the legacy session.json file.
    """
    from core.agent.task_isolation import get_task_isolated_cwd

    current_cwd = get_task_isolated_cwd() or ""

    # SQLite primary — per-agent row landed by record_agent_session_end.
    try:
        from core.observability.agent_runtime_state import get_agent_runtime_state

        state = get_agent_runtime_state(session_id)
        if state is not None and state.claude_cli_session_id:
            stored_cwd = str(state.session_resume_params.get("cwd", ""))
            if _saved_cwd_matches_current(stored_cwd, current_cwd):
                return state.claude_cli_session_id
            log.info(
                "session %s saved for cwd=%r — skipping resume in cwd=%r",
                state.claude_cli_session_id,
                stored_cwd,
                current_cwd,
            )
            return ""
    except Exception:
        log.debug(
            "agent_runtime_state read failed for %s — falling back to session.json",
            session_id,
            exc_info=True,
        )

    # File fallback — when the SQLite runtime-state row is absent.
    try:
        from core.observability.run_dir import resolve_sub_agent_path

        session_path = resolve_sub_agent_path(session_id, "session.json")
    except Exception:
        log.debug(
            "resolve_sub_agent_path failed for %s — no resume id",
            session_id,
            exc_info=True,
        )
        return ""
    if session_path is None or not session_path.exists():
        return ""
    try:
        import json

        payload = json.loads(session_path.read_text(encoding="utf-8"))
        cached = payload.get("claude_cli_session_id", "")
        if not cached:
            return ""
        # same paired-cwd gate; missing key → skip gate (back-compat)
        stored_cwd_file = str(payload.get("cwd", ""))
        if not _saved_cwd_matches_current(stored_cwd_file, current_cwd):
            log.info(
                "session %s (file) saved for cwd=%r — skipping resume in cwd=%r",
                cached,
                stored_cwd_file,
                current_cwd,
            )
            return ""
        return str(cached)
    except Exception:
        log.debug("session.json read failed for %s", session_id, exc_info=True)
        return ""


def _persist_session_id(session_id: str, emitted_session_id: str) -> None:
    """Persist the claude-cli session_id this turn emitted for the next
    turn's ``--resume <id>``.

    Dual-write: SQLite ``agent_runtime_state.claude_cli_session_id``
    (primary, covers the case where the id is emitted before the round's
    SESSION_ENDED hook fires) + the legacy session.json file. The cwd is
    paired into both writes (storage is cwd-keyed). Empty
    ``emitted_session_id`` is a no-op (non-claude-cli adapters).
    """
    if not emitted_session_id:
        return

    # cwd the session was written from — reader's gate is keyed on it
    from core.agent.task_isolation import get_task_isolated_cwd

    write_cwd = get_task_isolated_cwd() or ""
    resume_params = {"cwd": write_cwd} if write_cwd else {}

    # SQLite primary write — upsert the resumable session_id
    try:
        from core.observability.agent_runtime_state import record_agent_session_end

        record_agent_session_end(
            agent_id=session_id,
            claude_cli_session_id=emitted_session_id,
            session_resume_params=resume_params,
        )
    except Exception:
        log.debug(
            "agent_runtime_state write failed for %s — file fallback only",
            session_id,
            exc_info=True,
        )

    # File-fallback write — mirrors the SQLite primary.
    try:
        from core.observability.run_dir import resolve_sub_agent_path

        session_path = resolve_sub_agent_path(session_id, "session.json")
    except Exception:
        log.debug(
            "resolve_sub_agent_path failed for %s — file fallback skipped",
            session_id,
            exc_info=True,
        )
        return
    if session_path is None:
        return
    try:
        import json
        import time

        payload = {
            "claude_cli_session_id": emitted_session_id,
            "updated_at": time.time(),
        }
        # pair cwd here too — reader's gate is symmetric across both paths
        if write_cwd:
            payload["cwd"] = write_cwd
        session_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.debug("session.json write failed for %s", session_id, exc_info=True)


def _tool_args_signature(tool_input: Any) -> str:
    """Short stable signature of a tool call's arguments.

    The diversity guard folds this into the call identity so that two calls
    of the same tool only count as a no-progress repeat when their arguments
    ALSO match. Five ``grep_files`` with five different patterns therefore
    produce five distinct signatures and never look like a stuck loop, while
    the identical call issued over and over does.
    """
    import hashlib
    import json

    try:
        canonical = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = repr(tool_input)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """

    DEFAULT_MAX_ROUNDS = 0  # 0 = unlimited (time-based control via time_budget_s)
    DEFAULT_MAX_TOKENS = 32768
    WRAP_UP_HEADROOM = 2  # force text response N rounds before max
    _WRAP_UP_TIME_HEADROOM_S = 30.0  # force text 30s before time budget expires

    def __init__(  # noqa: PLR0913 — config knobs grow incrementally; refactor pending
        self,
        context: ConversationContext,
        tool_executor: ToolExecutor,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        thinking_budget: int = 0,  # 0 = disabled; >0 = Extended Thinking tokens (legacy)
        effort: str = "high",  # "low" | "medium" | "high" | "max" (adaptive thinking)
        time_budget_s: float = 0.0,  # 0 = no time limit (OpenClaw pattern)
        cost_budget: float = 0.0,  # 0 = defer to settings.cost_limit_usd (0 there too = no limit)
        model: str | None = None,
        provider: str = "anthropic",
        tool_registry: ToolRegistry | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        hooks: HookSystem | None = None,
        enable_goal_decomposition: bool = True,
        parent_session_key: str = "",
        parent_session_id: str = "",
        system_suffix: str = "",
        system_prompt_override: str | None = None,
        quiet: bool = False,
        disable_settings_drift: bool = False,
        allowed_tool_names: set[str] | None = None,
        force_include_allowed_tools: bool = False,
        source: str = "",
        session_id: str = "",
        response_schema: dict[str, Any] | None = None,
        allow_actionable_partial_on_empty: bool = False,
        yield_after_tool_round: bool = False,
        activity_sink_provider: RunEventSinkProvider | None = None,
        policy_sources: PolicySourceBundle | None = None,
    ) -> None:
        self.context = context
        self.executor = tool_executor
        self._parent_session_key = parent_session_key
        self._parent_session_id = parent_session_id
        self._system_suffix = system_suffix
        # When set, replaces the default role/instruction body (skill
        # context + agentic suffix still appended). Drives AgentDefinition
        # sub-agents off their own role contract.
        self._system_prompt_override = system_prompt_override
        self._quiet = quiet  # suppress spinner (sub-agent, headless)
        # Evaluator-owned simulators can preserve tool actions from a completed
        # round when the following model continuation is irrecoverably empty.
        # Ordinary agents retain the strict exception boundary by default.
        self._allow_actionable_partial_on_empty = allow_actionable_partial_on_empty
        # External half-duplex orchestrators can own the next model turn. The
        # default AgenticLoop contract remains while(tool_use); opted-in callers
        # yield only after one completed tool batch has been recorded.
        self._yield_after_tool_round = yield_after_tool_round
        self._activity_sink_provider = activity_sink_provider
        self._policy_sources = policy_sources or EMPTY_POLICY_SOURCES
        from core.tools.plan import BoundToolPlan as _BoundToolPlan

        executor_plan = getattr(tool_executor, "_bound_tool_plan", None)
        bound_tool_plan = executor_plan if isinstance(executor_plan, _BoundToolPlan) else None
        if (
            bound_tool_plan is not None
            and allowed_tool_names is not None
            and not set(bound_tool_plan.tool_names) <= allowed_tool_names
        ):
            raise ValueError("bound_tool_plan must be filtered before applying an allowlist")
        self._bound_tool_plan = bound_tool_plan
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self._thinking_budget = thinking_budget
        self._effort = effort
        self._time_budget_s = time_budget_s
        # Adaptive compute: track consecutive text-only rounds for overthinking detection
        self._consecutive_text_only_rounds = 0
        self._total_empty_rounds = 0
        # Low-confidence replan is edge-triggered: fires once when
        # confidence drops below REPLAN_LOW_CONFIDENCE, re-arms only
        # after confidence recovers — prevents a replan storm while
        # confidence stays low.
        self._low_confidence_replan_armed = True
        # No positive cost_budget → fall back to settings.cost_limit_usd so
        # the config knob (`cost.limit_usd`) reaches the enforced guard 3
        # (80% warn / 100% hard stop), not just the COST_WARNING /
        # COST_LIMIT_EXCEEDED hook events. A positive caller value (e.g.
        # supervised services' monthly-budget wiring) always wins; there is
        # deliberately no "explicit 0 disables the settings knob" escape.
        # Snapshot at construction is intentional (session-bound budget);
        # the hook path in _response.py live-reads the knob instead.
        if cost_budget <= 0.0:
            try:
                from core.config import settings as _settings

                limit_raw = getattr(_settings, "cost_limit_usd", 0.0)
                # isinstance filters MagicMock auto-attrs in fixtures
                if isinstance(limit_raw, int | float) and limit_raw > 0:
                    cost_budget = float(limit_raw)
            except Exception:
                log.debug("settings.cost_limit_usd read failed", exc_info=True)
        self._cost_budget = cost_budget
        self._loop_start_time: float = 0.0
        # No explicit model → prefer settings.act_model (Plan/Act split),
        # else ANTHROPIC_PRIMARY.
        if model is None:
            try:
                from core.config import settings

                # isinstance(str) filters MagicMock auto-attrs in fixtures
                act_raw = getattr(settings, "act_model", "")
                act_model = act_raw.strip() if isinstance(act_raw, str) else ""
            except Exception:
                log.debug("settings.act_model read failed", exc_info=True)
                act_model = ""
            # live read — config change takes effect without restart
            from core.config import ANTHROPIC_PRIMARY

            self.model = act_model or ANTHROPIC_PRIMARY
        else:
            self.model = model
        self._provider = provider  # "anthropic", "openai", or "glm"
        # When True, sync_model_from_settings is a no-op — caller's model
        # stays sticky for the loop's lifetime.
        self._disable_settings_drift = disable_settings_drift
        # set by update_model_async on model change; the run-loop rebuilds
        # system_prompt before the next LLM call.
        self._prompt_dirty: bool = False
        self._last_plan_hint: str = ""
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._hooks = hooks
        executor_hooks = getattr(tool_executor, "hook_registry", None)
        executor_middleware = getattr(tool_executor, "middleware_registry", None)
        self._hook_registry = (
            executor_hooks
            if isinstance(executor_hooks, HookRegistry)
            else HookRegistry(events=hooks)
        )
        self._middleware_registry = (
            executor_middleware
            if isinstance(executor_middleware, MiddlewareRegistry)
            else MiddlewareRegistry(events=hooks)
        )
        self._turn_id = ""
        self._verify_root_turn_id = ""
        self._verify_root_user_input = ""
        self._verify_attempt = 0
        self._verify_attempt_results: list[AgenticResult] = []
        self._verification_evidence_refs: list[dict[str, Any]] = []
        self._pending_verification: dict[str, Any] = {}
        self._verify_continuation_budget = 2
        self._session_generation = 1
        self._public_session_started = False
        self._public_session_ended = False
        # No explicit source → infer_source promotes an OAuth provider to
        # "subscription". _source_explicit tracks the pin so a cross-provider
        # /model switch only re-infers when the source was inferred here.
        self._source_explicit = bool(source)
        if not source:
            from core.llm.adapters._source_inference import infer_source

            source = infer_source(provider)
        self._source = source
        # security: model-visible tool schemas filtered to the allowlist —
        # the full surface must not leak past the whitelist (None = no
        # filter). Stored on self so refresh_tools re-applies it on rebuild.
        self._allowed_tool_names = allowed_tool_names
        # Sub-agent/toolkit and benchmark grants may explicitly outrank the
        # mutable global tool policy. Ordinary session allowlists only narrow.
        self._force_include_allowed_tools = force_include_allowed_tools
        mcp_tool_list = mcp_manager.get_all_tools() if mcp_manager is not None else None
        transient_tool_names = self._transient_tool_names(mcp_tool_list)
        # Epoch snapshot pairs with the arun refresh gate: a server recycle
        # bumps the manager epoch and invalidates this tool snapshot.
        self._mcp_epoch = mcp_manager.connection_epoch if mcp_manager is not None else 0
        runtime_tools = get_agentic_tools(
            tool_registry,
            mcp_tools=mcp_tool_list,
            force_include=allowed_tool_names if force_include_allowed_tools else None,
            provider=self._provider,
            source=self._source,
            policy_sources=self._policy_sources,
        )
        if allowed_tool_names is not None:
            runtime_tools = [t for t in runtime_tools if t.get("name") in allowed_tool_names]
        self._transient_tools: tuple[dict[str, Any], ...] = ()
        self._transient_deferred_tool_names: tuple[str, ...] = ()
        if bound_tool_plan is not None:
            self._apply_bound_tool_plan(
                runtime_tools,
                transient_tool_names=transient_tool_names,
            )
        else:
            self._tools = runtime_tools
        self._capability_graph: CapabilityGraph | None = None
        self._task_preflight: TaskPreflight | None = None
        self._capability_graph_digest: str = ""
        self._last_llm_error: str | None = None  # last error type for user message
        # Per-loop structured-output JSON schema (None = free-form text);
        # threaded into every _call_llm's AdapterCallRequest.response_schema.
        self._response_schema: dict[str, Any] | None = response_schema
        from core.llm.adapters import resolve_for
        from core.llm.adapters.registry import normalize_registry_provider

        registry_provider = normalize_registry_provider(self._provider)
        # Adapter resolution: direct registry-name lookup, else legacy
        # category-axis path. Missing adapter HARD-FAILS (no silent fallback).
        from core.llm.adapters.registry import AdapterNotFoundError, get_adapter

        try:
            self._new_adapter: Any = get_adapter(self._source)
        except AdapterNotFoundError:
            self._new_adapter = resolve_for(registry_provider, self._source)
        # latest claude-cli sessionId the adapter emitted — SESSION_ENDED
        # carries it to the agent_runtime_state writer (empty for others)
        self._last_emitted_session_id: str = ""
        self._op_logger = OperationLogger(quiet=self._quiet)
        self._error_recovery = ErrorRecoveryStrategy(tool_executor)

        # Immutable session history: canonical SQLite rows with an optional
        # run-scoped JSONL projection.
        self._timeline: Any | None = None
        self._session_id: str = ""
        self._goal_store: Any | None = None
        try:
            import uuid as _uuid

            from core.observability.session_timeline import SessionTimeline

            # caller-provided session_id wins (keeps the worker's artifacts
            # under one sub_agents/<task_id>/ dir); else ephemeral s-<uuid>
            if session_id:
                self._session_id = session_id
            else:
                self._session_id = f"s-{_uuid.uuid4().hex[:12]}"
            self._timeline = SessionTimeline(self._session_id)
            from core.memory.goals import GoalStore

            self._goal_store = GoalStore(self._timeline.db_path)
        except Exception:
            log.warning("Session timeline init failed", exc_info=True)
        from core.observability.session_metrics import SessionMetrics, current_session_metrics

        ambient_metrics = current_session_metrics()
        self._session_metrics = (
            ambient_metrics
            if ambient_metrics.session_id == self._session_id or ambient_metrics.gen_tag
            else SessionMetrics(
                session_id=self._session_id,
                component="agentic_loop",
                started_at=time.time(),
            )
        )
        try:
            from core.agent.capability_graph import build_capability_graph
            from core.agent.evidence_ledger import EvidenceLedger
            from core.llm.providers.anthropic import is_computer_use_enabled

            self._capability_graph = build_capability_graph(
                model=self.model,
                provider=self._provider,
                source=self._source,
                visible_tool_names={
                    str(tool.get("name", "")) for tool in self._tools if tool.get("name")
                },
                computer_use_enabled=is_computer_use_enabled(),
            )
            self._evidence_ledger: Any | None = EvidenceLedger.for_session(
                self._session_id,
                turn_id_provider=lambda: self._turn_id,
            )
            # PR-HITL-APPROVAL-FSM (2026-07-02) — hand the session ledger to
            # the executor so approval-FSM terminal states (granted/denied +
            # executed/skipped) land as evidence rows. getattr-guarded: tests
            # construct the loop with executor doubles that lack the hook.
            _attach_ledger = getattr(tool_executor, "attach_evidence_ledger", None)
            if callable(_attach_ledger):
                _attach_ledger(self._evidence_ledger)
        except Exception:
            self._capability_graph = None
            self._evidence_ledger = None
            log.debug("Capability graph/evidence ledger init failed", exc_info=True)

        # ToolCallProcessor: orchestrates tool_use block execution. Pull
        # (provider, source) from the resolved adapter — the loop's own
        # fields can hold pre-normalisation values the registry collapses,
        # while dispatch's _apply_prefer compares against the adapter's.
        _ctx_provider = getattr(self._new_adapter, "provider", self._provider)
        _ctx_source = getattr(self._new_adapter, "source", self._source)
        self._tool_processor = ToolCallProcessor(
            executor=tool_executor,
            op_logger=self._op_logger,
            error_recovery=self._error_recovery,
            hooks=hooks,
            mcp_manager=mcp_manager,
            timeline=self._timeline,
            model=self.model,
            provider=_ctx_provider,
            source=_ctx_source,
            adapter_name=getattr(self._new_adapter, "name", ""),
        )

        # Goal decomposition: auto-decompose compound requests into sub-goal DAGs
        self._enable_goal_decomposition = enable_goal_decomposition

        # LLM-call retry budget; at the cap the loop exits with
        # model_action_required so the user picks a model via /model.
        self._consecutive_llm_failures: int = 0
        self._LLM_RETRY_CAP: int = 5  # max retries before giving up
        self._pre_execution_retry_errors: list[str] = []

        from core.agent.context_manager import ContextWindowManager

        self._ctx_mgr = ContextWindowManager(
            hooks=hooks,
            hook_registry=self._hook_registry,
            quiet=quiet,
            session_id_provider=lambda: self._session_id or None,
        )

        # Convergence detection — 3 identical errors break the loop.
        from core.agent.convergence import ConvergenceDetector

        self._convergence = ConvergenceDetector()

        # Diversity forcing — detect the SAME tool called with IDENTICAL
        # arguments N times in a row (a genuine no-progress loop). Entries are
        # ``(tool_name, args_signature)`` tuples.
        self._consecutive_tool_tracker: list[tuple[str, str]] = []

        # full message persistence for /resume
        self._checkpoint: Any | None = None
        try:
            from core.memory.session_checkpoint import SessionCheckpoint

            self._checkpoint = SessionCheckpoint()
        except Exception:
            log.warning("SessionCheckpoint init failed", exc_info=True)

        # Cognitive state container — goal set on first arun(); round-end
        # fields updated each round; hypotheses/confidence by the reflection node.
        from core.agent.cognitive_state import CognitiveState

        self.cognitive_state = CognitiveState()

    # ------------------------------------------------------------------
    # Lifecycle / metrics — delegate to ``_lifecycle``
    # ------------------------------------------------------------------

    @property
    def pre_execution_retry_errors(self) -> tuple[str, ...]:
        """Connection/empty-output retries observed in the current arun."""

        return tuple(self._pre_execution_retry_errors)

    def _save_checkpoint(self, user_input: str, round_idx: int = 0) -> bool:
        """Delegates to :func:`_lifecycle.save_checkpoint`."""
        return _lifecycle.save_checkpoint(self, user_input, round_idx)

    def mark_session_paused(self) -> None:
        """Delegates to :func:`_lifecycle.mark_session_paused`."""
        return _lifecycle.mark_session_paused(self)

    async def amark_session_completed(self) -> None:
        """Durably complete and emit the public SessionEnd boundary."""
        await _lifecycle.mark_session_completed_async(self)

    async def amark_session_paused(self) -> None:
        """Durably pause while keeping the public session lifetime open."""
        await _lifecycle.mark_session_paused_async(self)

    async def amark_session_error(self) -> None:
        """Durably error and emit the public SessionEnd boundary."""
        await _lifecycle.mark_session_error_async(self)

    def restore_from_checkpoint(self, state: Any) -> None:
        """Delegates to :func:`_lifecycle.restore_loop_state` — the single
        resume surgery (session id + cognitive state + guard counters)."""
        return _lifecycle.restore_loop_state(self, state)

    def _record_timeline_end(
        self,
        result: Any,
        verify_payload: dict[str, Any] | None = None,
    ) -> None:
        """Delegates to :func:`_lifecycle.record_timeline_end`."""
        return _lifecycle.record_timeline_end(self, result, verify_payload)

    async def _afinalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Delegates to :func:`_lifecycle.finalize_and_return_async`."""
        return await _lifecycle.finalize_and_return_async(self, result, user_input, round_idx)

    def _build_reasoning_metrics(self, result: AgenticResult) -> Any:
        """Delegates to :func:`_lifecycle.build_reasoning_metrics`."""
        return _lifecycle.build_reasoning_metrics(self, result)

    def _emit_quota_panel(self, exc: BillingError) -> None:
        """Delegates to :func:`_lifecycle.emit_quota_panel`."""
        return _lifecycle.emit_quota_panel(self, exc)

    def _inject_credential_breadcrumb(self) -> None:
        """Delegates to :func:`_lifecycle.inject_credential_breadcrumb`."""
        return _lifecycle.inject_credential_breadcrumb(self)

    async def _emit_cognitive(self, event: HookEvent, **payload: Any) -> None:
        """Emit a cognitive-cycle event with the state snapshot attached.

        Centralises the (a) hook-system None-guard, (b) session_id
        injection, (c) ``cognitive_state`` snapshot embedding so each
        call site stays a one-liner and ``arun`` doesn't balloon past
        the ruff complexity gates.
        """
        if not self._hooks:
            return
        await self._hooks.trigger_async(
            event,
            {
                "session_id": self._session_id,
                "cognitive_state": self.cognitive_state.to_snapshot(),
                **payload,
            },
        )

    async def _record_text_only_round(self, round_idx: int, *, text: str) -> None:
        """Record round end + emit REFLECT/UPDATE_MEMORY for text-only
        completions (``stop_reason != "tool_use"``).

        Contract: ACT/OBSERVE are NOT emitted (no action taken). If
        ``cognitive_reflection_enabled`` is on, the reflection node still
        gets one final chance to update beliefs from the terminal text
        snapshot before REFLECT/UPDATE_MEMORY fire. ``last_action`` =
        ``"text-only"``, ``last_observation`` = 80-char head of the text
        (distinguishes no-action from failed-tool turns).
        """
        head = text.strip().replace("\n", " ")
        if len(head) > 80:
            head = head[:80] + "…"
        self.cognitive_state.record_round(
            action="text-only",
            observation=head or "(empty text)",
        )
        await self._maybe_reflect([])
        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1)

    async def _run_cognitive_act_observe_cycle(
        self, response: Any, round_idx: int
    ) -> list[dict[str, Any]]:
        """Emit ACT before the tool batch, run the batch, emit OBSERVE
        after, update :attr:`cognitive_state` round-end fields, emit
        REFLECT + UPDATE_MEMORY.

        Preserves the cognitive-cycle event ordering (PERCEIVE -> PLAN ->
        ACT -> OBSERVE -> REFLECT -> UPDATE_MEMORY).
        """
        tool_names: list[str] = []
        for block in getattr(response, "content", None) or []:
            if getattr(block, "type", None) == "tool_use":
                tool_names.append(getattr(block, "name", "unknown"))

        await self._emit_cognitive(
            HookEvent.COGNITIVE_ACT,
            round=round_idx + 1,
            tool_names=tool_names,
        )

        tool_results = await self._tool_processor.process(response)

        await self._emit_cognitive(
            HookEvent.COGNITIVE_OBSERVE,
            round=round_idx + 1,
            tool_names=tool_names,
            result_count=len(tool_results),
        )

        # deterministic round-end update — reflection node overwrites below
        self.cognitive_state.record_round(
            action=("tools: " + ", ".join(tool_names)) if tool_names else "text-only",
            observation=f"{len(tool_results)} tool result(s)",
        )

        # Raw personal Workspace results stay in the active model turn only.
        # Reflection can use a separately configured provider and persists its
        # hypotheses, so skip that secondary processing for the whole batch if
        # any personal-data tool ran.  The deterministic count/tool-name
        # snapshot above remains available to cognitive listeners.
        personal_tools = sorted(set(tool_names).intersection(PERSONAL_DATA_TOOLS))
        if personal_tools:
            log.info(
                "reflection skipped for personal-data tool batch: tools=%s",
                ",".join(personal_tools),
            )
        else:
            # reflection runs before the REFLECT hook so listeners see the
            # LLM-derived belief update, not the deterministic snapshot
            await self._maybe_reflect(tool_results)

        await self._emit_cognitive(HookEvent.COGNITIVE_REFLECT, round=round_idx + 1)
        await self._emit_cognitive(HookEvent.COGNITIVE_UPDATE_MEMORY, round=round_idx + 1)

        return tool_results

    async def _maybe_reflect(self, tool_results: list[dict[str, Any]]) -> None:
        """Call the reflection node if enabled.

        Reads ``settings.cognitive_reflection_enabled`` lazily (toggle
        takes effect next round, no restart). ``reflection_interval=N``
        thins the cadence; the first round always reflects. Errors are
        swallowed inside ``reflect_async`` (loop stays robust to a flaky
        reflection model).
        """
        from core.config import settings

        if not settings.cognitive_reflection_enabled:
            return
        interval = max(1, int(settings.cognitive_reflection_interval))
        # Confidence-adaptive cadence: high stable confidence buys fewer
        # belief-update calls (interval doubled), low confidence forces a
        # reflection every round. Reads the LAST reflection's confidence —
        # staleness during a stretch is the accepted trade (verify still
        # watches every turn). None (no reflection yet) → base interval.
        confidence = self.cognitive_state.confidence
        if getattr(settings, "cognitive_reflection_adaptive", True) and isinstance(
            confidence, int | float
        ):
            if confidence >= REFLECTION_STRETCH_CONFIDENCE:
                interval *= 2
            elif confidence < REFLECTION_FORCE_CONFIDENCE:
                interval = 1
        # round_count is 1-based (record_round ran just before this);
        # (round_count - 1) % interval == 0 → rounds 1, 1+N, 1+2N, ...
        round_count = self.cognitive_state.round_count
        if interval > 1 and (round_count - 1) % interval != 0:
            log.debug(
                "reflection skipped: round=%d interval=%d (next at round %d)",
                round_count,
                interval,
                round_count + (interval - (round_count - 1) % interval),
            )
            return
        from core.agent.loop._reflection import reflect_async

        raw_model = settings.cognitive_reflection_model
        configured_model = raw_model.strip() if isinstance(raw_model, str) else ""
        inherit_loop_model = not configured_model
        reflection_model = configured_model or self.model
        reflection_provider = self._provider if inherit_loop_model else None
        reflection_source = (
            getattr(self._new_adapter, "source", self._source) if inherit_loop_model else None
        )

        reflection_kwargs: dict[str, Any] = {}
        active_middleware = getattr(self, "_middleware_registry", None)
        if active_middleware is not None:
            reflection_kwargs["middleware_registry"] = active_middleware
        await reflect_async(
            self.cognitive_state,
            tool_results,
            model=reflection_model,
            max_tokens=settings.cognitive_reflection_max_tokens,
            provider=reflection_provider,
            source=reflection_source,
            policy_sources=self._policy_sources,
            **reflection_kwargs,
        )

    async def _emit_session_start_signals(self, user_input: str) -> AgenticResult | None:
        """Emit the turn-start signals. Owns the USER_INPUT_RECEIVED
        observation, cognitive-state goal init + ContextVar bind,
        COGNITIVE_PERCEIVE emit, conversation-context append, SessionTimeline
        ``record_session_start`` / ``record_user_message``, and the
        SESSION_STARTED hook.

        Returns ``None`` on the happy path. Returns an
        :class:`AgenticResult` (with ``termination_reason="input_blocked"``)
        The public UserPromptSubmit decision runs at the start of ``arun``
        before preflight or decomposition.
        """
        # Internal observation only; public control belongs to HookRegistry.
        if self._hooks:
            await self._hooks.trigger_async(
                HookEvent.USER_INPUT_RECEIVED,
                {
                    "user_input": user_input,
                    "session_id": self._session_id,
                    "turn_id": self._turn_id,
                },
            )

        # goal = first arun()'s input (later calls keep it so observations
        # accumulate against one goal)
        if not self.cognitive_state.goal:
            self.cognitive_state.goal = user_input
        # Bind CognitiveState/session ids to ContextVars so tool-executor
        # hooks read the live state without coupling to AgenticLoop. Binding
        # is asyncio-task-scoped; the next arun overwrites idempotently.
        from core.agent.cognitive_state_ctx import (
            set_cognitive_state,
            set_parent_session_id,
            set_parent_session_key,
            set_session_id,
            set_turn_id,
        )

        set_cognitive_state(self.cognitive_state)
        set_session_id(self._session_id)
        set_turn_id(getattr(self, "_turn_id", ""))
        # Sub-agent lineage → Episode rows (empty for top-level loops)
        set_parent_session_key(self._parent_session_key)
        set_parent_session_id(self._parent_session_id)
        await self._emit_cognitive(
            HookEvent.COGNITIVE_PERCEIVE,
            user_input=user_input,
        )

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Durable history: session generation + this turn's user message.
        if self._timeline is not None:
            self._timeline.record_session_start(model=self.model, provider=self._provider)
            self._timeline.record_user_message(user_input)

        # fresh per-session adapter usage counter → SESSION_ENDED adapter_usage
        from core.llm.adapters.dispatch import begin_session_adapter_tracking

        begin_session_adapter_tracking()

        # Hook: SESSION_START
        if self._hooks:
            await self._hooks.trigger_async(
                HookEvent.SESSION_STARTED,
                {
                    "model": self.model,
                    "provider": self._provider,
                    "session_id": self._session_id,
                    "resumed": len(self.context.messages) > 1,
                },
            )

        return None

    async def _dispatch_llm_call(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        round_idx: int,
        spinner: TextSpinner,
    ) -> AgenticResponse | AgenticResult | None:
        """Dispatch the LLM call and handle the simple exceptions.

        Returns:
          * ``AgenticResponse`` on a successful call (caller proceeds
            with response processing).
          * ``AgenticResult`` on ``BillingError`` or
            ``UserCancelledError`` (caller ``return``s this verbatim).
          * ``None`` when ``_call_llm`` returns ``None`` (caller's
            existing error-classification path handles it).

        ``_ContextExhaustedError`` is NOT caught — propagates so the
        caller's aggressive-recovery path runs intact. Stops ``spinner``
        before emitting quota/cancel output (caller's finally also stops it).
        """
        try:
            return await self._call_llm(system_prompt, messages, round_idx=round_idx)
        except BillingError as exc:
            spinner.stop()
            self._emit_quota_panel(exc)
            return self._terminal_result(
                TerminationReason.BILLING_ERROR,
                exc.user_message(),
                rounds=round_idx + 1,
            )
        except UserCancelledError:
            spinner.stop()
            log.info("LLM call interrupted by user")
            return self._terminal_result(
                TerminationReason.USER_CANCELLED,
                "Interrupted.",
                rounds=round_idx + 1,
            )

    async def _sync_model_and_rebuild_prompt(
        self,
        system_prompt: str,
        reflection_hint: str | None = None,
        verification_hint: str | None = None,
    ) -> str:
        """Sync model drift + rebuild the system prompt.

        Rebuilds when the model drifted (``settings.model`` changed),
        ``_prompt_dirty`` is set (direct ``update_model_async``), or advisory
        plan progress changed. On rebuild, re-applies the preflight /
        reflection / verification / plan hints inside the dynamic envelope so
        a mid-arun change does not drop them. Returns the (possibly-rebuilt)
        prompt; clears ``_prompt_dirty``.
        """
        drift_detected = await self._sync_model_from_settings_async()
        prompt_dirty = self._prompt_dirty
        _plan_consume = getattr(self, "_consume_plan_hint", None)
        raw_plan_hint = _plan_consume() if callable(_plan_consume) else ""
        plan_hint = raw_plan_hint if isinstance(raw_plan_hint, str) else ""
        last_plan_hint = getattr(self, "_last_plan_hint", "")
        if not isinstance(last_plan_hint, str):
            last_plan_hint = plan_hint
        plan_changed = plan_hint != last_plan_hint
        if drift_detected or prompt_dirty or plan_changed:
            from core.agent.loop._context import inject_runtime_hints

            system_prompt = inject_runtime_hints(
                self._build_system_prompt(),
                getattr(self, "_preflight_hint", ""),
                reflection_hint,
                verification_hint,
                plan_hint if isinstance(plan_hint, str) else "",
            )
            self._prompt_dirty = False
            self._last_plan_hint = plan_hint
            # Fire PROMPT_ASSEMBLED on each per-round rebuild (no-op if no hooks)
            hooks = getattr(self, "_hooks", None)
            if hooks:
                from core.hooks import HookEvent

                reason = (
                    "model_drift"
                    if drift_detected
                    else ("prompt_dirty" if prompt_dirty else "plan_progress")
                )
                await hooks.trigger_async(
                    HookEvent.PROMPT_ASSEMBLED,
                    {
                        "model": self.model,
                        "provider": self._provider,
                        "reason": reason,
                        "x2_injected": True,  # identity line always present
                        "prompt_len": len(system_prompt),
                    },
                )
        return system_prompt

    def _check_round_guards(self, round_idx: int) -> str | None:
        """Run the round-entry guards.

        Returns ``None`` to proceed, else a short guard-name string
        (``arun`` breaks the while-loop on a non-None response).

        Guards (Karpathy P3): ``round_limit`` (``max_rounds > 0``, 0-based
        index), ``time_budget`` (``time_budget_s > 0``, wall clock vs
        ``_loop_start_time``), and the session-wide budget/handoff check.
        """
        import time as _time

        if self.max_rounds > 0 and round_idx >= self.max_rounds:
            return "round_limit"
        if self._time_budget_s > 0:
            elapsed = _time.monotonic() - self._loop_start_time
            if elapsed >= self._time_budget_s:
                return "time_budget"
        # session-wide cap + T-threshold handoff (getattr tolerates stub loops)
        handoff_check = getattr(self, "_check_session_budget_and_maybe_handoff", None)
        if handoff_check is not None:
            handoff_reason: str | None = handoff_check()
            if handoff_reason is not None:
                return handoff_reason
        return None

    def _terminal_result(
        self,
        reason: TerminationReason,
        text: str,
        *,
        rounds: int,
        error: bool = False,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> AgenticResult:
        """Sole birth-place of terminal results — the loop's exit alphabet.

        Every terminal exit constructs its :class:`AgenticResult` here, so
        the reachable terminal-state space is exactly
        :class:`TerminationReason` (pinned by
        ``tests/core/agent/test_loop_state_machine.py``). ``error=True``
        mirrors *reason* into ``AgenticResult.error`` — the legacy dual
        encoding some consumers still read. ``tool_calls=None`` keeps the
        dataclass default (empty list) for pre-tool exits; pass
        ``self._tool_processor.tool_log`` explicitly where the exit carries
        tool work.
        """
        result = AgenticResult(
            text=text,
            rounds=rounds,
            error=str(reason) if error else None,
            termination_reason=reason,
        )
        if tool_calls is not None:
            result.tool_calls = tool_calls
        return result

    async def _apply_user_prompt_hook(
        self,
        user_input: str,
    ) -> tuple[str, AgenticResult | None]:
        """Apply the public input boundary before any planning or model work."""
        outcome = await self._hook_registry.invoke(
            HookName.USER_PROMPT_SUBMIT,
            payload={"user_input": user_input},
            correlation=HookCorrelation(
                session_id=self._session_id,
                turn_id=self._turn_id,
            ),
        )
        if outcome.blocked:
            reason = next(
                (
                    decision.reason
                    for decision in outcome.decisions
                    if decision.action is HookAction.BLOCK
                ),
                "Blocked by UserPromptSubmit hook",
            )
            return user_input, self._terminal_result(
                TerminationReason.INPUT_BLOCKED,
                reason,
                rounds=0,
            )
        effective = outcome.invocation.payload.get("user_input")
        return (effective if isinstance(effective, str) else user_input), None

    async def _begin_turn(
        self,
        user_input: str,
        continuation: HookCorrelation | None,
        *,
        internal_continuation: bool = False,
    ) -> tuple[str, AgenticResult | None]:
        """Reset per-turn state and cross the public input boundary."""
        import uuid

        from core.observability.session_metrics import set_current_session_metrics

        set_current_session_metrics(self._session_metrics)

        self._tool_processor.reset()
        self._op_logger.reset()
        self._pre_execution_retry_errors.clear()
        self._turn_id = f"t-{uuid.uuid4().hex[:12]}"
        if self._timeline is not None:
            self._timeline.bind_turn(
                self._turn_id,
                session_generation=int(getattr(self, "_session_generation", 1)),
            )
        from core.observability.session_timeline import set_current_session_timeline

        set_current_session_timeline(self._timeline)
        if continuation is None:
            self._verify_root_turn_id = self._turn_id
            self._verify_root_user_input = ""
            self._verify_attempt = 0
            self._verify_attempt_results = []
        else:
            self._verify_root_turn_id = continuation.turn_id or self._turn_id
            self._verify_attempt = continuation.verify_attempt

        from core.agent.cognitive_state_ctx import set_session_id, set_turn_id

        set_session_id(self._session_id)
        set_turn_id(self._turn_id)
        if continuation is not None:
            return user_input, None
        if internal_continuation:
            from core.agent.cognitive_state_ctx import (
                set_cognitive_state,
                set_parent_session_id,
                set_parent_session_key,
            )

            set_cognitive_state(self.cognitive_state)
            set_parent_session_key(self._parent_session_key)
            set_parent_session_id(self._parent_session_id)
            self._verify_root_user_input = user_input
            return user_input, None
        effective, blocked = await self._apply_user_prompt_hook(user_input)
        self._verify_root_user_input = effective
        return effective, blocked

    def _refresh_mcp_tools_at_turn_start(self) -> None:
        """Refresh a lazy or stale MCP schema snapshot."""
        if self._mcp_manager is None or (
            len(self._tools) >= TOOL_LAZY_LOAD_THRESHOLD
            and self._mcp_manager.connection_epoch == self._mcp_epoch
        ):
            return
        added = self.refresh_tools()
        self._mcp_epoch = self._mcp_manager.connection_epoch
        if added > 0:
            log.info("MCP tools lazy-loaded: +%d tools (total %d)", added, len(self._tools))

    async def _open_turn(
        self,
        user_input: str,
        *,
        verification_continuation: bool = False,
        goal_continuation: Any | None = None,
        goal_continuation_trigger: str = "active_goal",
    ) -> AgenticResult | None:
        """Publish legacy start signals, then the durable public boundary."""
        if verification_continuation:
            if self._timeline is not None:
                self._timeline.record_verification_continuation(
                    user_input,
                    root_turn_id=self._verify_root_turn_id,
                    verify_attempt=self._verify_attempt,
                )
            root_input = self._verify_root_user_input or user_input
            self._save_checkpoint(root_input, round_idx=0)
            return await self._admit_session_budget(user_input)
        if goal_continuation is not None:
            resumed_start = (
                int(getattr(self, "_session_generation", 1)) > 1
                and not self._public_session_started
            )
            if self._timeline is not None:
                from core.observability.session_timeline import SessionEventKind

                if resumed_start:
                    self._timeline.record_session_start(
                        model=self.model,
                        provider=self._provider,
                    )
                self._timeline.record_goal_state(
                    SessionEventKind.GOAL_CONTINUED,
                    goal_continuation,
                    trigger=goal_continuation_trigger,
                )
            if resumed_start:
                from core.llm.adapters.dispatch import begin_session_adapter_tracking

                begin_session_adapter_tracking()
                if self._hooks:
                    await self._hooks.trigger_async(
                        HookEvent.SESSION_STARTED,
                        {
                            "model": self.model,
                            "provider": self._provider,
                            "session_id": self._session_id,
                            "resumed": True,
                        },
                    )
            objective = str(getattr(goal_continuation, "objective", user_input))
            if self._save_checkpoint(objective, round_idx=0) and resumed_start:
                await _lifecycle.emit_public_session_start(self)
            return await self._admit_session_budget(user_input)
        intercepted = await self._emit_session_start_signals(user_input)
        if intercepted is not None:
            return intercepted
        if self._save_checkpoint(user_input, round_idx=0):
            await _lifecycle.emit_public_session_start(self)
        return await self._admit_session_budget(user_input)

    async def _finalize_blocked_turn(self, result: AgenticResult) -> AgenticResult:
        """Persist a rejected prompt attempt without storing its prompt body."""
        if self._timeline is not None:
            self._timeline.record_session_start(
                model=self.model,
                provider=self._provider,
            )
        return await self._afinalize_and_return(result, "", 0)

    async def _admit_session_budget(self, user_input: str) -> AgenticResult | None:
        """Stop an expired opt-in session before planner, model, or tool work."""
        self._maybe_start_session_budget()
        guard = self._check_session_budget_and_maybe_handoff()
        if guard is None:
            return None
        reason, text = self._guard_exit_result(guard, rounds=0)
        return await self._afinalize_and_return(
            self._terminal_result(reason, text, rounds=0),
            user_input,
            0,
        )

    # ------------------------------------------------------------------
    # Guard chain — the loop's transition guards, in priority order
    # ------------------------------------------------------------------
    # Call order in ``arun`` IS the priority order:
    #   post-response: cost_budget → overthinking → model_refusal
    #   post-tool:     convergence → repeated_success_no_progress
    # Each guard returns a terminal AgenticResult (born via
    # ``_terminal_result``) or None to proceed. Guard counters live on
    # ``self`` and are checkpointed via ``_lifecycle.collect_guard_state``
    # so a resumed session keeps its guard progress.

    def _guard_cost_budget(
        self,
        *,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult | None:
        """Cost budget guard (Karpathy P3 — resource budget).

        Warns once at 80% of budget; terminates with
        ``cost_budget_exceeded`` at 100%.
        """
        if self._cost_budget <= 0:
            return None
        try:
            from core.llm.token_tracker import get_tracker as _get_cost_tracker

            _cost_tracker = _get_cost_tracker()
            _session_cost = _cost_tracker.accumulator.total_cost_usd

            _warn_threshold = self._cost_budget * 0.8
            if (
                _session_cost >= _warn_threshold
                and _session_cost < self._cost_budget
                and not getattr(self, "_budget_warned", False)
            ):
                self._budget_warned = True
                if not self._quiet:
                    from core.ui.agentic_ui import emit_budget_warning

                    emit_budget_warning(
                        self._cost_budget,
                        _session_cost,
                        pct=_session_cost / self._cost_budget * 100,
                    )

            if _session_cost >= self._cost_budget:
                from core.ui.agentic_ui import emit_cost_budget_exceeded

                emit_cost_budget_exceeded(self._cost_budget, _session_cost)
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                text = (
                    f"Cost budget (${self._cost_budget:.2f}) exceeded. "
                    f"Session cost: ${_session_cost:.2f}"
                )
                log.warning(text)
                return self._terminal_result(
                    TerminationReason.COST_BUDGET_EXCEEDED,
                    text,
                    rounds=round_idx + 1,
                    error=True,
                    tool_calls=self._tool_processor.tool_log,
                )
        except Exception:
            log.debug("Cost budget check failed", exc_info=True)
        return None

    async def _guard_overthinking(
        self,
        response: Any,
        *,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult | None:
        """Overthinking guard — N consecutive long-text/no-tool rounds stop
        the loop with ``user_clarification_needed`` (threshold is
        context-proportional, 1% / floor 1024). Owns the counter reset on
        tool-use rounds.
        """
        if response.stop_reason != "tool_use":
            out_tok = getattr(response.usage, "output_tokens", 0) if response.usage else 0
            threshold = self._overthinking_token_threshold()
            if out_tok > threshold:
                self._consecutive_text_only_rounds += 1
            else:
                self._consecutive_text_only_rounds = 0
            if self._consecutive_text_only_rounds >= 2:
                # count this flagged round ONCE — adding the running
                # consec would inflate the total quadratically
                self._total_empty_rounds += 1
                log.warning(
                    "Overthinking detected: %d consecutive text-only rounds "
                    "(>%d tok each) — surfacing user_clarification_needed",
                    self._consecutive_text_only_rounds,
                    threshold,
                )
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                last_text = self._extract_text(response).strip()
                summary = last_text[:400] + ("…" if len(last_text) > 400 else "")
                clarification = (
                    f"~ I've spent {self._consecutive_text_only_rounds} consecutive "
                    f"rounds reasoning without taking any action "
                    f"(>{threshold} output tokens each). "
                    "Could you narrow the request — point at a specific file, "
                    "behaviour, or step you want me to focus on next?\n\n"
                    f"Most recent reasoning (truncated):\n{summary}"
                )
                await self._record_text_only_round(round_idx, text=last_text)
                return self._terminal_result(
                    TerminationReason.USER_CLARIFICATION_NEEDED,
                    clarification,
                    rounds=round_idx + 1,
                    tool_calls=self._tool_processor.tool_log,
                )
        else:
            self._consecutive_text_only_rounds = 0
        return None

    def _guard_model_refusal(
        self,
        response: Any,
        *,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult | None:
        """Fable 5 safety decline (HTTP 200, often empty) — surface it
        honestly instead of a silent empty turn.

        ref: https://platform.claude.com/docs/en/about-claude/models/migration-guide
        """
        if response.stop_reason != "refusal":
            return None
        self._op_logger.finalize()
        self._sync_messages_to_context(messages)
        stop_details = getattr(response, "stop_details", None)
        category = stop_details.get("category") if isinstance(stop_details, dict) else None
        refusal_text = self._extract_text(response).strip() or (
            "The model declined this request"
            + (f" (safety classifier category: {category})" if category else "")
            + ". Rephrase the request or retry on another model via /model."
        )
        return self._terminal_result(
            TerminationReason.MODEL_REFUSAL,
            refusal_text,
            rounds=round_idx + 1,
            tool_calls=self._tool_processor.tool_log,
        )

    def _guard_convergence(
        self,
        *,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult | None:
        """Convergence guard — 3 identical tool errors break the loop."""
        if not self._check_convergence_break():
            return None
        from core.ui.agentic_ui import emit_convergence_detected

        last_err = (
            self._convergence.recent_errors[-1] if self._convergence.recent_errors else "unknown"
        )
        emit_convergence_detected(last_err, round_idx + 1)
        self._op_logger.finalize()
        self._sync_messages_to_context(messages)
        return self._terminal_result(
            TerminationReason.CONVERGENCE_DETECTED,
            "Detected repeating failure pattern. Breaking loop to avoid infinite retry.",
            rounds=round_idx + 1,
            error=True,
            tool_calls=self._tool_processor.tool_log,
        )

    def _guard_repeated_success(
        self,
        *,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult | None:
        """Repeated-success guard — identical successful results without new
        progress stop the loop (polling the same state indefinitely).
        """
        if not self._check_repeated_success_no_progress():
            return None
        from core.ui.agentic_ui import emit_repeated_success_no_progress

        tool_name = self._convergence.last_success_tool or "unknown"
        streak = self._convergence.repeated_success_streak
        emit_repeated_success_no_progress(tool_name, streak, round_idx + 1)
        self._op_logger.finalize()
        self._sync_messages_to_context(messages)
        return self._terminal_result(
            TerminationReason.REPEATED_SUCCESS_NO_PROGRESS,
            "Detected repeated successful tool results without new progress. "
            "Breaking loop to avoid polling the same state indefinitely.",
            rounds=round_idx + 1,
            error=True,
            tool_calls=self._tool_processor.tool_log,
        )

    def _guard_exit_result(
        self,
        guard_reason: str | None,
        *,
        rounds: int,
    ) -> tuple[TerminationReason, str]:
        """Map a loop-entry guard reason to a terminal result.

        The guard helper returns precise internal reasons. Preserve that
        precision here so session-wide budget handoff/expiry does not leak as
        the unrelated legacy "max rounds" fallback.
        """
        if guard_reason == "time_budget":
            return (
                TerminationReason.TIME_BUDGET_EXPIRED,
                f"Time budget ({self._time_budget_s:.0f}s) expired after {rounds} rounds.",
            )
        if guard_reason in {"session_time_budget_handoff", "session_time_budget_expired"}:
            remaining = None
            total = None
            try:
                metrics = self._session_metrics
                remaining = metrics.time_budget_remaining_s()
                total = metrics.time_budget_total_s
            except Exception:
                log.debug("session budget summary unavailable for guard exit", exc_info=True)

            if guard_reason == "session_time_budget_handoff":
                if remaining is not None and total is not None and total > 0:
                    text = (
                        "Session time budget is in the handoff window "
                        f"({remaining:.0f}s remaining of {total:.0f}s). "
                        "Start a new GEODE session or restart GEODE to continue safely."
                    )
                else:
                    text = (
                        "Session time budget is in the handoff window. "
                        "Start a new GEODE session or restart GEODE to continue safely."
                    )
                return TerminationReason.SESSION_TIME_BUDGET_HANDOFF, text

            if remaining is not None and total is not None and total > 0:
                text = (
                    "Session time budget expired "
                    f"({abs(min(remaining, 0.0)):.0f}s over the {total:.0f}s budget). "
                    "Start a new GEODE session or restart GEODE to continue."
                )
            else:
                text = (
                    "Session time budget expired. "
                    "Start a new GEODE session or restart GEODE to continue."
                )
            return TerminationReason.SESSION_TIME_BUDGET_EXPIRED, text

        # Back-compat: an exhausted positive max_rounds cap keeps the legacy
        # result text/termination reason.
        return (
            TerminationReason.MAX_ROUNDS,
            "Max agentic rounds reached. Please try a more specific request.",
        )

    def _persist_handoff_request(self) -> None:
        """Flip the ``sessions`` row to ``handoff_state='pending'`` via the
        DB CAS helper (once per session at the T-threshold crossing).

        Failures NEVER raise. No-op when no session_id is bound or the row
        isn't upserted yet.
        """
        session_id = getattr(self, "_session_id", "")
        if not session_id:
            return
        mgr = None
        try:
            from core.agent.handoff import request_handoff
            from core.memory.session_manager import SessionManager

            mgr = SessionManager()
            request_handoff(mgr._conn, session_id=session_id, platform="agentic_loop")
        except Exception:
            log.debug("Handoff DB request skipped", exc_info=True)
        finally:
            # Close to avoid leaked SQLite handles.
            if mgr is not None:
                try:
                    mgr.close()
                except Exception:
                    log.debug("Handoff SessionManager close failed", exc_info=True)

    async def _maybe_replan_async(self, round_idx: int, *, failure_context: str = "") -> None:
        """Per-round Dynamic Replan trigger.

        Asks :func:`core.agent.plan.should_replan`; on a trigger calls
        :func:`replan_async` (planner LLM via the active loop model) and
        installs the new :class:`Plan` via ``set_active_plan``.

        Triggers: ``verify_fail`` (fires at the first round of the *next*
        ``arun``, since verify runs at finalization) and ``cadence``
        (every ``settings.replan_interval`` rounds). Failures NEVER raise;
        no-op when ``replan_enabled=False`` or no trigger fires.
        """
        try:
            from core.agent.plan import (
                _replan_max_attempts,
                replan_async,
                should_replan,
            )
            from core.observability.session_metrics import current_session_metrics

            metrics = current_session_metrics()
            # Low-confidence replan (edge-triggered; see constructor
            # comment on _low_confidence_replan_armed). Re-arm on
            # recovery, fire only on an armed drop below threshold.
            # getattr tolerates stub loops (same convention as
            # _check_round_guards' handoff check).
            raw_confidence = getattr(getattr(self, "cognitive_state", None), "confidence", None)
            confidence: float | None = (
                float(raw_confidence) if isinstance(raw_confidence, int | float) else None
            )
            if confidence is not None and confidence >= REPLAN_LOW_CONFIDENCE:
                self._low_confidence_replan_armed = True
            low_confidence = (
                getattr(self, "_low_confidence_replan_armed", True)
                and confidence is not None
                and confidence < REPLAN_LOW_CONFIDENCE
            )
            trigger = should_replan(
                round_idx=round_idx,
                plan=metrics.active_plan,
                verify_failed=not metrics.last_verify_passed,
                verify_should_retry=metrics.last_verify_should_retry,
                low_confidence=low_confidence,
            )
            if trigger is None:
                return
            if trigger == "low_confidence":
                # consume the edge — no refire until confidence recovers
                self._low_confidence_replan_armed = False
            # Abandon path: a verify_fail past replan_max_attempts on one
            # step advances the plan instead of calling the planner (step
            # is stuck). The cadence trigger isn't capped.
            if trigger == "verify_fail" and metrics.active_plan is not None:
                metrics.record_step_attempt()
                cap = _replan_max_attempts()
                if metrics.replan_attempts_on_current_step > cap:
                    abandoned_step = metrics.active_plan.current_step()
                    advanced = metrics.active_plan.abandon_and_advance()
                    # new step → reset the per-step counter
                    metrics.set_active_plan(advanced, reset_attempts=True)
                    timeline = getattr(self, "_timeline", None)
                    if timeline is not None:
                        from core.observability.session_timeline import SessionEventKind

                        timeline.record_plan_state(
                            SessionEventKind.PLAN_ABANDONED,
                            advanced,
                            trigger="retry_budget_exhausted",
                            changed_step_ids=(abandoned_step.id,)
                            if abandoned_step is not None
                            else (),
                        )
                    self._prompt_dirty = True
                    log.info(
                        "Replan abandon: step exceeded %d attempts; advancing plan",
                        cap,
                    )
                    return
            # Replan against the failed candidate and verifier instruction;
            # the per-turn tool log was reset before a verify continuation.
            from types import SimpleNamespace

            recent_parts: list[str] = []
            if trigger == "verify_fail":
                attempts = getattr(self, "_verify_attempt_results", ())
                if attempts:
                    recent_parts.append(str(getattr(attempts[-1], "text", "") or ""))
                if failure_context:
                    recent_parts.append(failure_context)
            if not recent_parts:
                try:
                    recent_parts.append(str(self._tool_processor.tool_log[-1].get("result", "")))
                except Exception:
                    log.debug("recent tool_log read for replanner failed", exc_info=True)
            recent_text = "\n\n".join(part for part in recent_parts if part)
            stub_result = SimpleNamespace(text=str(recent_text))
            new_plan = await replan_async(
                self, plan=metrics.active_plan, turn_result=stub_result, trigger=trigger
            )
            if new_plan is None:
                log.info("Replan trigger=%s: planner failed; keeping prior plan", trigger)
                return
            metrics.record_replan(trigger)
            metrics.set_active_plan(new_plan)
            timeline = getattr(self, "_timeline", None)
            if timeline is not None:
                from core.observability.session_timeline import SessionEventKind

                timeline.record_plan_state(
                    SessionEventKind.PLAN_REPLANNED,
                    new_plan,
                    trigger=trigger,
                )
            # next LLM call must see the new plan
            self._prompt_dirty = True
            # UI replan banner
            try:
                from core.ui.agentic_ui import emit_plan_step, emit_replan

                emit_replan(
                    trigger=trigger,
                    step_count=len(new_plan.steps),
                    revision=new_plan.revision,
                )
                first_step = new_plan.current_step()
                if first_step is not None:
                    emit_plan_step(
                        current=new_plan.current + 1,
                        total=len(new_plan.steps),
                        description=first_step.description,
                        revision=new_plan.revision,
                    )
            except Exception:
                log.debug("Replan UI emit failed", exc_info=True)
            log.info(
                "Replan trigger=%s: installed %d-step plan (revision %d)",
                trigger,
                len(new_plan.steps),
                new_plan.revision,
            )
        except Exception:
            log.warning("Replan dispatch crashed", exc_info=True)

    def _consume_plan_hint(self) -> str:
        """Render the active :class:`Plan` as a ``<plan>...</plan>`` block.

        Read-only (no clear) — the plan persists until a replan installs a
        new revision. Empty string when no plan is active. Failures NEVER raise.
        """
        try:
            from core.agent.plan import render_plan_for_prompt
            from core.observability.session_metrics import current_session_metrics

            plan = current_session_metrics().active_plan
            if plan is None:
                return ""
            return render_plan_for_prompt(plan)
        except Exception:
            log.warning("Plan hint consume failed", exc_info=True)
            return ""

    def _consume_reflection_hint(self) -> str:
        """Read+clear the failure-reflection hint left by the prior turn.

        Returns the ``<reflection>...</reflection>`` block from the prior
        turn's verify FAIL, else empty (verify passed / didn't run).
        Read+clear is asyncio-task safe (no ``await`` between); a threaded
        race only risks a duplicate prepend, not data loss. Failures NEVER
        raise.

        Contract: pre-finalize exits (BillingError / UserCancelledError)
        skip verify, so the next arun's hint slot is empty by design.
        """
        try:
            from core.observability.session_metrics import current_session_metrics

            metrics = current_session_metrics()
            hint = metrics.last_verify_reflection_hint
            if hint:
                metrics.last_verify_reflection_hint = ""
            return hint
        except Exception:
            log.warning("Reflection hint consume failed", exc_info=True)
            return ""

    def _consume_reflexion_hint(self) -> str:
        """Legacy alias for :meth:`_consume_reflection_hint`."""
        return AgenticLoop._consume_reflection_hint(self)

    def _maybe_start_session_budget(self) -> None:
        """Begin the session-wide wall-clock budget if not already started.

        Idempotent — no-op when a prior loop in the same SessionMetrics
        scope already started it (clock keeps running across nested loops).
        The cap is opt-in via ``GEODE_SESSION_TIME_BUDGET_S``; unset, invalid,
        and non-positive values leave durable sessions unbounded.
        Failures NEVER raise.
        """
        import math
        import os

        try:
            from core.agent.budget import (
                DEFAULT_HANDOFF_THRESHOLD_S,
                start_session_budget,
            )

            metrics = self._session_metrics
            if metrics.time_budget_total_s > 0.0:
                return  # Already started in this session.
            raw = os.environ.get("GEODE_SESSION_TIME_BUDGET_S")
            if raw is None:
                return
            try:
                total = float(raw)
            except ValueError:
                log.warning("Ignoring invalid GEODE_SESSION_TIME_BUDGET_S=%r", raw)
                return
            if not math.isfinite(total) or total <= 0.0:
                log.warning("Ignoring non-positive or non-finite session time budget: %r", raw)
                return  # Explicitly disabled.
            start_session_budget(
                total_seconds=total,
                handoff_threshold_seconds=min(DEFAULT_HANDOFF_THRESHOLD_S, total / 2.0),
                metrics=metrics,
            )
        except Exception:
            log.warning("Session budget start failed", exc_info=True)

    def _check_session_budget_and_maybe_handoff(self) -> str | None:
        """Check session-wide wall-clock budget. Returns a guard-string when
        the loop must break, ``None`` otherwise. Fires ``HANDOFF_TRIGGERED``
        on the first threshold crossing.

        Returns:
            * ``"session_time_budget_handoff"`` on first T-threshold crossing.
            * ``"session_time_budget_expired"`` when fully past the cap.
            * ``None`` when still within budget (or no budget set).
        """
        import time as _time

        try:
            from core.agent.budget import budget_summary, check_session_budget

            metrics = self._session_metrics
            check = check_session_budget(metrics=metrics)
            if check.expired:
                return "session_time_budget_expired"
            if check.handoff_due:
                payload: dict[str, Any] = {
                    "session_id": self._session_id,
                    "platform": "",  # adapter binding can override
                    "remaining_s": check.remaining_seconds,
                    "ts": _time.time(),
                    **budget_summary(metrics=metrics),
                }
                if self._hooks is not None:
                    try:
                        self._hooks.trigger(HookEvent.HANDOFF_TRIGGERED, payload)
                    except Exception:
                        log.warning("HANDOFF_TRIGGERED hook failed", exc_info=True)
                if self._timeline is not None:
                    try:
                        self._timeline.record_lifecycle_event(
                            event="handoff_triggered",
                            component="agentic_loop",
                            level="warning",
                            payload=payload,
                            action="agent.handoff_triggered",
                            entity_type="session",
                            entity_id=self._session_id,
                        )
                    except Exception:
                        log.warning("Timeline handoff_triggered record failed", exc_info=True)
                # flip the sessions row to handoff_state=PENDING (read-write
                # parity; no-op when no session row exists yet)
                self._persist_handoff_request()
                return "session_time_budget_handoff"
        except Exception:
            log.warning("Session budget check failed", exc_info=True)
        return None

    def _overthinking_token_threshold(self) -> int:
        """Per-round output-token threshold for the overthinking signal.

        Context-proportional (1% of context window, floor 1024). Falls
        back to 2000 when the token-tracker lookup fails (mocked module).
        """
        try:
            from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

            ctx_window = MODEL_CONTEXT_WINDOW.get(self.model, 200_000)
            return max(1024, int(ctx_window) // 100)
        except (TypeError, ValueError, AttributeError):
            return 2000

    def _build_model_action_result(
        self,
        *,
        error_type: str,
        severity: str,
        hint: str,
        rounds: int,
        detail: str | None = None,
    ) -> AgenticResult:
        """Build an ``AgenticResult`` carrying a user-facing diagnostic.

        Used when an LLM error survives the retry budget (or convergence
        breaks) — surfaces context for the user to pick a model via ``/model``.
        """
        from core.llm.errors import build_model_action_message, summarize_error_detail

        cost: float | None = None
        try:
            from core.llm.token_tracker import get_tracker

            cost = float(get_tracker().accumulator.total_cost_usd)
        except Exception:
            log.debug("total_cost_usd read for diagnostic failed", exc_info=True)
            cost = None
        # strip raw SDK JSON to the underlying message (no-op if unclear)
        clean_detail = summarize_error_detail(detail) if detail else None
        text = build_model_action_message(
            error_type=error_type,
            severity=severity,
            hint=hint,
            model=self.model,
            provider=self._provider,
            attempts=self._consecutive_llm_failures,
            cost_so_far_usd=cost,
            suggested_models=self._fallback_chain_suggestions() or None,
            detail=clean_detail,
        )
        return self._terminal_result(
            TerminationReason.MODEL_ACTION_REQUIRED,
            text,
            rounds=rounds,
            error=True,
            tool_calls=self._tool_processor.tool_log,
        )

    async def _afinalize_actionable_partial_on_empty(
        self,
        exc: EmptyModelOutputError,
        *,
        messages: list[dict[str, Any]],
        user_input: str,
        round_idx: int,
    ) -> AgenticResult | None:
        """Preserve prior tool work when an opted-in continuation is empty."""

        usable_tool_actions = any(
            not isinstance(entry.get("result"), dict) or not entry["result"].get("error")
            for entry in self._tool_processor.tool_log
        )
        if not self._allow_actionable_partial_on_empty or not usable_tool_actions:
            return None
        # The current continuation is empty, but an earlier round in this
        # same turn already emitted executable tool work. Preserve that work
        # and attest every exhausted empty attempt. Empty-before-action stays
        # a hard infrastructure failure.
        exc.mark_actionable()
        log.warning(
            "AgenticLoop: finalized actionable partial turn after empty "
            "continuation (rounds=%d tools=%d)",
            round_idx,
            len(self._tool_processor.tool_log),
        )
        self._op_logger.finalize()
        self._sync_messages_to_context(messages)
        result = self._terminal_result(
            TerminationReason.ACTIONABLE_PARTIAL,
            "",
            rounds=round_idx,
            tool_calls=list(self._tool_processor.tool_log),
        )
        return await self._afinalize_and_return(result, user_input, round_idx)

    async def _finalize_context_exhausted(
        self,
        user_input: str,
        messages: list[dict[str, Any]],
        round_idx: int,
    ) -> AgenticResult:
        """Build + finalize the terminal context-exhausted result.

        Shared recovery-failed tail (pre-call / post-call / 400-overflow):
        notify ``exhausted``, sync messages back to context, return the
        terminal ``context_exhausted`` result through finalize.
        """
        self._notify_context_event(
            "exhausted",
            original_count=len(messages),
            new_count=len(messages),
        )
        self._sync_messages_to_context(messages)
        result = self._terminal_result(
            TerminationReason.CONTEXT_EXHAUSTED,
            await _context_exhausted_message(user_input),
            rounds=round_idx + 1,
            error=True,
            tool_calls=self._tool_processor.tool_log,
        )
        return await self._afinalize_and_return(result, user_input, round_idx + 1)

    async def _afinalize_tool_round_yield(
        self,
        *,
        messages: list[dict[str, Any]],
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Yield one completed tool batch to an external turn orchestrator."""

        self._op_logger.finalize()
        self._sync_messages_to_context(messages)
        result = self._terminal_result(
            TerminationReason.TOOL_USE_YIELD,
            "",
            rounds=round_idx + 1,
            tool_calls=list(self._tool_processor.tool_log),
        )
        return await self._afinalize_and_return(result, user_input, round_idx + 1)

    def _tool_round_assistant_message(self, response: AgenticResponse) -> dict[str, Any]:
        """Serialize one tool-use response with provider replay sidecars."""

        message: dict[str, Any] = {
            "role": "assistant",
            "content": self._serialize_content(response.content),
        }
        reasoning_items = getattr(response, "codex_reasoning_items", None)
        output_items = getattr(response, "codex_output_items", None)
        phase = getattr(response, "assistant_phase", "")
        if reasoning_items:
            message["codex_reasoning_items"] = reasoning_items
        if output_items:
            message["codex_output_items"] = output_items
        if phase:
            message["phase"] = phase
        return message

    # ------------------------------------------------------------------
    # Tool list refresh — delegate to ``_response``
    # ------------------------------------------------------------------

    def refresh_tools(self) -> int:
        """Delegates to :func:`_response.refresh_tools`."""
        return _response.refresh_tools(self)

    def _transient_tool_names(
        self,
        mcp_tools: list[dict[str, Any]] | None,
    ) -> frozenset[str]:
        names = {tool["name"] for tool in (mcp_tools or ()) if isinstance(tool.get("name"), str)}
        if self._tool_registry is not None:
            names.update(
                tool["name"]
                for tool in self._tool_registry.to_anthropic_tools()
                if isinstance(tool.get("name"), str)
            )
        return frozenset(names)

    def _apply_bound_tool_plan(
        self,
        runtime_tools: list[dict[str, Any]],
        *,
        transient_tool_names: Set[str] = frozenset(),
    ) -> None:
        """Project plan-owned schemas plus explicit transient runtime overlays."""
        from core.tools.plan import thaw_tool_schema

        bound = self._bound_tool_plan
        if bound is None:
            self._tools = runtime_tools
            self._transient_tools = ()
            self._transient_deferred_tool_names = ()
            return
        from core.llm.tool_defer import default_deferred_tool_names

        plan_names = {item.spec.name for item in bound.plan.registrations}
        transient = tuple(
            tool
            for tool in runtime_tools
            if tool.get("name") in transient_tool_names and tool.get("name") not in plan_names
        )
        plan_tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": thaw_tool_schema(spec.input_schema),
            }
            for spec in bound.ordered_specs
        ]
        self._transient_tools = transient
        deferred = default_deferred_tool_names(
            tool["name"] for tool in transient if isinstance(tool.get("name"), str)
        )
        self._transient_deferred_tool_names = tuple(
            tool["name"] for tool in transient if tool.get("name") in deferred
        )
        self.executor._replace_bound_tool_scope(
            frozenset(tool["name"] for tool in transient if isinstance(tool.get("name"), str))
        )
        self._tools = [*plan_tools, *transient]

    def _reproject_bound_tool_plan(self) -> None:
        """Rebuild one effective Bound snapshot after a provider/source switch."""
        current = self._bound_tool_plan
        if current is None:
            return
        from core.agent.loop._tool_factory import project_bound_tool_plan

        projected = project_bound_tool_plan(
            current.base,
            provider=self._provider,
            source=self._source,
            policy_sources=self._policy_sources,
            force_include=(self._allowed_tool_names if self._force_include_allowed_tools else None),
        ).filtered(
            allowed_tool_names=(
                frozenset(self._allowed_tool_names)
                if self._allowed_tool_names is not None
                else None
            ),
            denied_tool_names=self.executor._denied_tools,
        )
        if projected.content_hash == current.content_hash:
            return
        projected = projected.at_generation(current.generation + 1)
        self.executor._replace_bound_tool_plan(projected)
        self._bound_tool_plan = projected

    def bound_tool_plan_snapshot(self) -> tuple[BoundToolPlan, Mapping[str, Any]]:
        """Return the current immutable catalog for an isolated child run."""
        if self._bound_tool_plan is None:
            raise RuntimeError("active AgenticLoop has no bound tool plan")
        transient_handlers = getattr(self.executor, "_transient_handlers", None)
        if not isinstance(transient_handlers, Mapping):
            raise RuntimeError("active ToolExecutor has no transient handler snapshot")
        return self._bound_tool_plan, transient_handlers

    # ------------------------------------------------------------------
    # Model switching / escalation — delegate to ``_model_switching``
    # ------------------------------------------------------------------

    async def _sync_model_from_settings_async(self) -> bool:
        """Async drift sync used by ``arun``."""
        return await _model_switching.sync_model_from_settings_async(self)

    def _drift_target_is_healthy(self, target_model: str) -> bool:
        """Health check: ``_resolve_provider`` → ``rotator.resolve`` lookup.

        Resolves ``target_model`` to its provider via ``_resolve_provider``
        and asks ``ProfileRotator.resolve`` whether any eligible profile
        could serve the next call. The query mirrors the actual selection
        path used by the LLM call so the answer matches what the next
        call would pick. Delegates to
        :func:`_model_switching.drift_target_is_healthy`.
        """
        return _model_switching.drift_target_is_healthy(self, target_model)

    async def update_model_async(
        self,
        model: str,
        provider: str | None = None,
        reason: str = "user_switch",
    ) -> None:
        """Delegates to :func:`_model_switching.update_model_async`."""
        return await _model_switching.update_model_async(self, model, provider, reason)

    def _purge_stale_model_switch_acks(self) -> int:
        """Delegates to :func:`_model_switching.purge_stale_model_switch_acks`.

        Returns the purged count, which the caller forwards to the
        MODEL_SWITCHED payload.
        """
        return _model_switching.purge_stale_model_switch_acks(self)

    def _adapt_context_for_model(self, target_model: str) -> None:
        """Delegates to :func:`_model_switching.adapt_context_for_model`."""
        return _model_switching.adapt_context_for_model(self, target_model)

    def _fallback_chain_suggestions(self) -> list[str]:
        """Remaining models in the current adapter's chain — for diagnostics."""
        return _model_switching.fallback_chain_suggestions(self)

    # ------------------------------------------------------------------
    # Run loop entry points
    # ------------------------------------------------------------------

    def _prepare_task_preflight(self, user_input: str) -> str:
        """Run capability-aware preflight and return a system-prompt hint."""
        try:
            from core.agent.capability_graph import graph_summary
            from core.agent.task_preflight import plan_task_preflight, render_preflight_hint

            capability_graph = self._capability_graph
            if capability_graph is None:
                raise RuntimeError("capability graph is unavailable")
            self._task_preflight = plan_task_preflight(user_input, capability_graph)
            preflight_hint = render_preflight_hint(self._task_preflight)
            if self._evidence_ledger is not None:
                self._evidence_ledger.append_preflight(
                    capability_graph=graph_summary(capability_graph),
                    preflight=self._task_preflight,
                )
            if self._timeline is not None:
                summary = graph_summary(capability_graph)
                digest = hashlib.sha256(
                    json.dumps(summary, sort_keys=True, ensure_ascii=False, default=str).encode()
                ).hexdigest()
                # The graph is invariant across a run while preflight varies per
                # turn, so re-serialising it every turn cost 43.4 MB across only
                # 19 distinct values. Emit it once, then reference the digest;
                # readers resolve a digest against the last full emission.
                payload: dict[str, Any] = {
                    "capability_graph_sha256": digest,
                    "preflight": self._task_preflight,
                }
                if self._bound_tool_plan is not None:
                    payload["tool_plan"] = {
                        "generation": self._bound_tool_plan.generation,
                        "content_hash": self._bound_tool_plan.content_hash,
                        "tool_count": len(self._bound_tool_plan.tool_names),
                        "eager_count": len(self._bound_tool_plan.eager_tool_names),
                        "deferred_count": len(self._bound_tool_plan.deferred_tool_names),
                    }
                if digest != self._capability_graph_digest:
                    payload["capability_graph"] = summary
                    self._capability_graph_digest = digest
                self._timeline.record_lifecycle_event(
                    event="task_preflight",
                    component="agentic_loop",
                    level="info",
                    payload=payload,
                    action="agent.preflight",
                    entity_type="session",
                    entity_id=self._session_id,
                )
            return preflight_hint
        except Exception:
            log.debug("Task preflight failed", exc_info=True)
            return ""

    async def arun(
        self,
        user_input: str,
        *,
        _verify_continuation: HookCorrelation | None = None,
    ) -> AgenticResult:
        """Run one user turn plus any explicitly activated goal continuations."""
        return await _goal.run(
            self,
            user_input,
            verify_continuation=_verify_continuation,
        )

    async def acontinue_goal(
        self,
        *,
        trigger: str = "serve_idle",
    ) -> AgenticResult | None:
        """Continue this session's active Goal through the normal turn loop."""
        return await _goal.continue_active(self, trigger=trigger)

    async def _arun_once(
        self,
        user_input: str,
        *,
        _verify_continuation: HookCorrelation | None = None,
        _goal_continuation: Any | None = None,
        _goal_continuation_trigger: str = "active_goal",
    ) -> AgenticResult:
        """Run one physical agent turn until the model emits a terminal."""
        user_input, blocked = await self._begin_turn(
            user_input,
            _verify_continuation,
            internal_continuation=_goal_continuation is not None,
        )
        if blocked is not None:
            return await self._finalize_blocked_turn(blocked)

        # Wire conversation context so /model command guard can check size
        from core.cli.commands import set_conversation_context

        set_conversation_context(self.context)

        # Lazy MCP tool refresh — load tools empty at init (startup timing
        # gap), and re-snapshot after any server recycle (epoch drift): a
        # reconnected server may advertise a different tool set (ADR-014 R5).
        self._refresh_mcp_tools_at_turn_start()

        # Open the durable turn before preflight/decomposition so every later
        # diagnostic row and early billing failure has a preceding
        # session.started + message.user anchor.
        intercept_result = await self._open_turn(
            user_input,
            verification_continuation=_verify_continuation is not None,
            goal_continuation=_goal_continuation,
            goal_continuation_trigger=_goal_continuation_trigger,
        )
        if intercept_result is not None:
            return intercept_result

        verification_continuation = _verify_continuation is not None
        task_input = (
            self._verify_root_user_input or user_input if verification_continuation else user_input
        )
        verification_hint = (
            _context.render_verification_continuation_hint(user_input)
            if verification_continuation
            else ""
        )
        goal_hint = (
            _context.render_goal_continuation_hint(_goal_continuation)
            if _goal_continuation is not None
            else ""
        )
        preflight_hint = self._prepare_task_preflight(task_input)
        # Retained on self so mid-arun prompt rebuilds re-apply it.
        self._preflight_hint = preflight_hint

        # Goal decomposition — break compound requests into sub-goal DAGs
        # (planner LLM call; the Plan is installed on SessionMetrics and
        # rendered via ``_consume_plan_hint`` — the hint return was removed
        # as dead plumbing, it had been None-only since the Plan migration).
        try:
            await self._try_decompose(
                user_input,
                enabled=not verification_continuation and _goal_continuation is None,
            )
        except BillingError as exc:
            self._emit_quota_panel(exc)
            return await self._afinalize_and_return(
                self._terminal_result(
                    TerminationReason.BILLING_ERROR,
                    exc.user_message(),
                    rounds=0,
                ),
                user_input,
                0,
            )

        messages = self.context.get_messages()
        # Codex Goal uses a hidden contextual-user fragment for idle-turn
        # steering. Keep this request-local so the continuation is visible to
        # the model without masquerading as a persisted human message.
        messages.extend(_context.goal_continuation_messages(goal_hint))

        # Unified runtime-hint grammar: every per-turn injection is an XML
        # block INSIDE <dynamic_context> — preflight, prior-turn reflection
        # (consume semantics), and the current-step <plan>.
        from core.agent.loop._context import inject_runtime_hints

        reflection_hint = self._consume_reflection_hint()
        plan_hint = self._consume_plan_hint()
        self._last_plan_hint = plan_hint
        system_prompt = inject_runtime_hints(
            self._build_system_prompt(),
            preflight_hint,
            reflection_hint,
            verification_hint,
            plan_hint,
        )

        # Prune old messages to stay within context budget (Karpathy P6)
        self._maybe_prune_messages(messages)

        import time as _time

        self._loop_start_time = _time.monotonic()
        # tracker snapshot at entry → finalize computes a per-arun usage
        # delta without double-counting sibling loops on the shared tracker
        from core.llm.token_tracker import get_tracker as _get_tracker

        self._usage_snapshot = _get_tracker().snapshot()
        round_idx = 0
        guard_reason: str | None = None
        while True:
            guard_reason = self._check_round_guards(round_idx)
            if guard_reason is not None:
                break

            is_last_round = (self.max_rounds > 0) and (round_idx == self.max_rounds - 1)
            self._op_logger.begin_round("AgenticLoop")

            # Dynamic Replan trigger (verify-FAIL / cadence); the rebuild
            # below picks up the new plan via _consume_plan_hint.
            await self._maybe_replan_async(
                round_idx,
                failure_context=user_input if verification_continuation else "",
            )

            system_prompt = await self._sync_model_and_rebuild_prompt(
                system_prompt,
                reflection_hint=reflection_hint,
                verification_hint=verification_hint,
            )

            # Admit durable child messages before their mailbox acknowledgement.
            self._admit_collaboration_messages(
                messages,
                user_input=user_input,
                round_idx=round_idx,
            )

            # Pre-call context check — proactive compress/prune (prevents 400)
            try:
                await self._check_context_overflow(system_prompt, messages)
            except _ContextExhaustedError:
                log.warning("Pre-call context exhausted — attempting aggressive recovery")
                recovered = await self._aggressive_context_recovery(system_prompt, messages)
                if recovered:
                    self._notify_context_event(
                        "prune",
                        original_count=len(messages) + recovered,
                        new_count=len(messages),
                    )
                    log.info("Pre-call recovery succeeded — proceeding with pruned context")
                else:
                    return await self._finalize_context_exhausted(user_input, messages, round_idx)

            # Pre-LLM-call PLAN event. See ``_emit_cognitive``.
            await self._emit_cognitive(
                HookEvent.COGNITIVE_PLAN,
                round=round_idx + 1,
                model=self.model,
            )

            # spinner while waiting for the LLM (IPC event or TextSpinner);
            # a reflection round (verify-FAIL hint injected) is disclosed as such
            from core.ui.agentic_ui import _ipc_writer_local

            _ipc_writer = getattr(_ipc_writer_local, "writer", None)
            if _ipc_writer is not None and not self._quiet:
                _ipc_writer.send_event(
                    "thinking_start",
                    model=self.model,
                    round=round_idx + 1,
                    reflection=bool(reflection_hint),
                )
                _spinner = TextSpinner("", quiet=True)  # no-op spinner
            else:
                verb = "Reflecting..." if reflection_hint else "Thinking..."
                label = verb if round_idx == 0 else f"{verb} (round {round_idx + 1})"
                _spinner = TextSpinner(label, quiet=self._quiet)
            _spinner.start()
            try:
                _llm_outcome = await self._dispatch_llm_call(
                    system_prompt, messages, round_idx, _spinner
                )
                if isinstance(_llm_outcome, AgenticResult):
                    return await self._afinalize_and_return(
                        _llm_outcome,
                        user_input,
                        round_idx + 1,
                    )
                response = _llm_outcome
            except EmptyModelOutputError as exc:
                partial = await self._afinalize_actionable_partial_on_empty(
                    exc,
                    messages=messages,
                    user_input=user_input,
                    round_idx=round_idx,
                )
                if partial is None:
                    raise
                return partial
            except _ContextExhaustedError as exc:
                _spinner.stop()
                log.warning("Context exhausted: %s — attempting aggressive recovery", exc)

                # Aggressive recovery: prune harder + summarize tool results
                recovered = await self._aggressive_context_recovery(system_prompt, messages)
                if recovered:
                    self._notify_context_event(
                        "prune",
                        original_count=len(messages) + recovered,
                        new_count=len(messages),
                    )
                    log.info("Aggressive recovery succeeded — continuing loop")
                    continue  # retry LLM call with pruned context

                # Recovery failed — finalize the terminal result.
                return await self._finalize_context_exhausted(user_input, messages, round_idx)
            finally:
                _spinner.stop()
                if _ipc_writer is not None and not self._quiet:
                    _ipc_writer.send_event("thinking_end")

            if response is None:
                # Classify error for type-specific retry; defaults cover an
                # adapter that swallowed the exception (None, no _last_error).
                adapter_exc = getattr(self._new_adapter, "_last_error", None)
                from core.llm.errors import _ERROR_CLASSIFICATION

                _et, _sev, _hint = _ERROR_CLASSIFICATION["unknown"]
                if adapter_exc is not None:
                    from core.llm.errors import classify_llm_error

                    _et, _sev, _hint = classify_llm_error(adapter_exc)

                    # context overflow from 400 → recovery + retry
                    if _et == "context_overflow":
                        log.warning("Context overflow detected from 400 — attempting recovery")
                        recovered = await self._aggressive_context_recovery(system_prompt, messages)
                        if recovered:
                            self._notify_context_event(
                                "prune",
                                original_count=len(messages) + recovered,
                                new_count=len(messages),
                            )
                            log.info("Context overflow recovery succeeded — retrying LLM call")
                            continue  # retry with pruned context
                        # recovery failed — context unrecoverably large
                        return await self._finalize_context_exhausted(
                            user_input, messages, round_idx
                        )

                    # Auth errors surface to the user (credentials are
                    # user-owned — refresh keys or pick a provider via /model).
                    if _et == "auth":
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        # LLM-readable credential breadcrumb for the next round
                        self._inject_credential_breadcrumb()
                        result = self._build_model_action_result(
                            error_type=_et,
                            severity=_sev,
                            hint=_hint,
                            rounds=round_idx + 1,
                            detail=self._last_llm_error or str(adapter_exc),
                        )
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)

                    # Non-retryable → immediate exit via the structured
                    # builder (raw SDK JSON must not leak into session history).
                    if _et == "bad_request":
                        if not self._quiet:
                            from core.ui.agentic_ui import emit_llm_error

                            emit_llm_error(_et, _sev, _hint, self.model, self._provider)
                        result = self._build_model_action_result(
                            error_type=_et,
                            severity=_sev,
                            hint=_hint,
                            rounds=round_idx + 1,
                            detail=self._last_llm_error or str(adapter_exc),
                        )
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)

                    if not self._quiet:
                        from core.ui.agentic_ui import emit_llm_error

                        emit_llm_error(
                            _et,
                            _sev,
                            _hint,
                            self.model,
                            self._provider,
                            attempt=self._consecutive_llm_failures + 1,
                        )

                    if self._hooks:
                        await self._hooks.trigger_async(
                            HookEvent.LLM_CALL_FAILED,
                            {
                                "model": self.model,
                                "provider": self._provider,
                                "error_type": _et,
                                "severity": _sev,
                                "attempt": self._consecutive_llm_failures + 1,
                            },
                        )

                self._consecutive_llm_failures += 1

                # auto-checkpoint before retry (resume after a model switch)
                # — after the increment so the persisted guard state carries
                # the failure just observed (crash-recovery parity).
                self._sync_messages_to_context(messages)
                self._save_checkpoint(user_input, round_idx=round_idx)

                # rate_limit → surface to user (no auto-swap; the diagnostic
                # carries the suggested fallback chain)
                if _et == "rate_limit":
                    result = self._build_model_action_result(
                        error_type=_et,
                        severity=_sev,
                        hint=_hint,
                        rounds=round_idx + 1,
                        detail=self._last_llm_error or str(adapter_exc),
                    )
                    return await self._afinalize_and_return(result, user_input, round_idx + 1)

                # Non-rate-limit: try context recovery before retrying the
                # same model; on success reset the failure counter.
                if self._consecutive_llm_failures >= 2:
                    recovered = await self._aggressive_context_recovery(system_prompt, messages)
                    if recovered:
                        self._notify_context_event(
                            "prune",
                            original_count=len(messages) + recovered,
                            new_count=len(messages),
                        )
                        log.info(
                            "Context compacted after %d failures — retrying same model (%s)",
                            self._consecutive_llm_failures,
                            self.model,
                        )
                        self._consecutive_llm_failures = 0
                        continue

                # Below retry cap: backoff and retry (don't break the loop)
                if self._consecutive_llm_failures < self._LLM_RETRY_CAP:
                    import asyncio as _asyncio

                    delay = min(2**self._consecutive_llm_failures, 30)
                    log.info(
                        "LLM call failed (%s) — retrying in %ds (attempt %d/%d)",
                        _et,
                        delay,
                        self._consecutive_llm_failures,
                        self._LLM_RETRY_CAP,
                    )
                    if not self._quiet:
                        from core.ui.agentic_ui import emit_llm_retry

                        emit_llm_retry(
                            delay,
                            self._consecutive_llm_failures,
                            self._LLM_RETRY_CAP,
                        )
                    if self._hooks:
                        await self._hooks.trigger_async(
                            HookEvent.LLM_CALL_RETRIED,
                            {
                                "model": self.model,
                                "provider": self._provider,
                                "error_type": _et,
                                "delay_s": delay,
                                "attempt": self._consecutive_llm_failures,
                                "max_attempts": self._LLM_RETRY_CAP,
                            },
                        )
                    await _asyncio.sleep(delay)
                    continue  # retry without incrementing round_idx

                # all retries exhausted → model_action_required diagnostic
                detail = self._last_llm_error or "unknown error"
                result = self._build_model_action_result(
                    error_type=_et,
                    severity=_sev,
                    hint=_hint,
                    rounds=round_idx + 1,
                    detail=detail,
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            # Successful LLM response — reset failure counter
            self._consecutive_llm_failures = 0

            # Track usage + Claude Code-style token display
            await self._track_usage_async(response)

            # --- Post-response guard chain — priority order IS this call
            # order; the first terminal outcome wins. Guard bodies live in
            # the "guard chain" section next to ``_terminal_result``.
            _terminal = self._guard_cost_budget(messages=messages, round_idx=round_idx)
            if _terminal is None:
                _terminal = await self._guard_overthinking(
                    response, messages=messages, round_idx=round_idx
                )
            if _terminal is None:
                _terminal = self._guard_model_refusal(
                    response,
                    messages=messages,
                    round_idx=round_idx,
                )
            if _terminal is not None:
                return await self._afinalize_and_return(_terminal, user_input, round_idx + 1)

            if response.stop_reason != "tool_use":
                # end_turn or max_tokens → extract text, done
                self._op_logger.finalize()
                text = self._extract_text(response)
                # Sync all intermediate tool-use messages + final response to context
                assistant_content = self._serialize_content(response.content)
                _assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_content,
                }
                # Codex encrypted-reasoning passthrough — echoed back into
                # the next-turn input array (other adapters ignore the field)
                if getattr(response, "codex_reasoning_items", None):
                    _assistant_msg["codex_reasoning_items"] = response.codex_reasoning_items
                if getattr(response, "codex_output_items", None):
                    _assistant_msg["codex_output_items"] = response.codex_output_items
                # Codex phase for the next-turn replay (other adapters ignore)
                _phase = getattr(response, "assistant_phase", "")
                if _phase:
                    _assistant_msg["phase"] = _phase
                messages.append(_assistant_msg)
                self._sync_messages_to_context(messages)
                await self._record_text_only_round(round_idx, text=text)
                reason = (
                    TerminationReason.FORCED_TEXT if is_last_round else TerminationReason.NATURAL
                )
                result = self._terminal_result(
                    reason,
                    text,
                    rounds=round_idx + 1,
                    tool_calls=self._tool_processor.tool_log,
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            tool_results = await self._run_cognitive_act_observe_cycle(response, round_idx)

            # External half-duplex orchestrators must receive every proposed
            # call before convergence guards can replace it with terminal text.
            # The authoritative result arrives on the next participant turn.
            if self._yield_after_tool_round:
                messages.append(self._tool_round_assistant_message(response))
                messages.append({"role": "user", "content": tool_results})
                return await self._afinalize_tool_round_yield(
                    messages=messages,
                    user_input=user_input,
                    round_idx=round_idx,
                )

            # backpressure on consecutive tool failures + convergence detection
            self._update_tool_error_tracking(tool_results)

            # --- Post-tool guard chain — same first-terminal-wins contract.
            _terminal = self._guard_convergence(messages=messages, round_idx=round_idx)
            if _terminal is None:
                _terminal = self._guard_repeated_success(
                    messages=messages,
                    round_idx=round_idx,
                )
            if _terminal is not None:
                return await self._afinalize_and_return(_terminal, user_input, round_idx + 1)

            if self._convergence.total_consecutive_tool_errors >= 3:
                # backpressure cooldown hint
                from core.ui.agentic_ui import emit_tool_backpressure

                emit_tool_backpressure(self._convergence.total_consecutive_tool_errors)
                await asyncio.sleep(1.0)
                backpressure_hint = {
                    "type": "text",
                    "text": (
                        "[system] Multiple tools are failing consecutively. "
                        "Consider a different approach. "
                        "If you cannot verify the answer through tools, "
                        "tell the user what failed and what remains unverified. "
                        "CANNOT silently answer from training data."
                    ),
                }
                tool_results.append(backpressure_hint)

            # Diversity forcing — fire only on a genuine no-progress loop: the
            # SAME tool called with IDENTICAL arguments N times in a row. Folding
            # args into the identity means five grep_files with five different
            # patterns (healthy fan-out research) never trip it, so no exempt
            # list of "naturally repetitive" tools is needed. Distinct calls
            # inside a single response are deduped so one parallel batch of N
            # distinct calls adds N distinct signatures (never trips), while an
            # identical call repeated across turns does.
            _DIVERSITY_N = 5
            _this_response: list[tuple[str, str]] = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    _sig = (
                        getattr(block, "name", ""),
                        _tool_args_signature(getattr(block, "input", None)),
                    )
                    if _sig not in _this_response:
                        _this_response.append(_sig)
            self._consecutive_tool_tracker.extend(_this_response)
            if len(self._consecutive_tool_tracker) > 10:
                self._consecutive_tool_tracker = self._consecutive_tool_tracker[-10:]
            if len(self._consecutive_tool_tracker) >= _DIVERSITY_N:
                _last_n = self._consecutive_tool_tracker[-_DIVERSITY_N:]
                if len(set(_last_n)) == 1:
                    _repeated_tool = _last_n[0][0]
                    diversity_hint = {
                        "type": "text",
                        "text": (
                            f"[system] The tool '{_repeated_tool}' has been called "
                            f"{_DIVERSITY_N} times with identical arguments — repeating this "
                            "exact call is unlikely to add new evidence. Try a different "
                            "approach or tool to make progress."
                        ),
                    }
                    tool_results.append(diversity_hint)
                    self._consecutive_tool_tracker.clear()

                    from core.ui.agentic_ui import emit_tool_diversity_forced

                    emit_tool_diversity_forced(_repeated_tool, _DIVERSITY_N)
                    log.warning(
                        "Diversity forcing: %s called %dx with identical args — injecting hint",
                        _repeated_tool,
                        _DIVERSITY_N,
                    )

            # accumulate serialized messages for the next round
            messages.append(self._tool_round_assistant_message(response))
            messages.append({"role": "user", "content": tool_results})
            round_idx += 1

        # Loop exited via guard — determine reason
        self._op_logger.finalize()
        elapsed = _time.monotonic() - self._loop_start_time
        if guard_reason == "time_budget":
            from core.ui.agentic_ui import emit_time_budget_expired

            emit_time_budget_expired(self._time_budget_s, elapsed, round_idx)
        reason, text = self._guard_exit_result(
            guard_reason,
            rounds=round_idx,
        )
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._sync_messages_to_context(messages)
        result = self._terminal_result(
            reason,
            text,
            rounds=round_idx,
            error=True,
            tool_calls=self._tool_processor.tool_log,
        )
        return await self._afinalize_and_return(result, user_input, round_idx)

    # ------------------------------------------------------------------
    # Context window — delegate to ``_context``
    # ------------------------------------------------------------------

    def _sync_messages_to_context(self, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.sync_messages_to_context`."""
        return _context.sync_messages_to_context(self, messages)

    def _notify_context_event(
        self, event_type: str, *, original_count: int, new_count: int
    ) -> None:
        """Delegates to :func:`_context.notify_context_event`."""
        return _context.notify_context_event(
            self, event_type, original_count=original_count, new_count=new_count
        )

    def _maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.maybe_prune_messages`."""
        return _context.maybe_prune_messages(self, messages)

    async def _check_context_overflow(self, system: str, messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.check_context_overflow`."""
        return await _context.check_context_overflow(self, system, messages)

    async def _aggressive_context_recovery(
        self, system: str, messages: list[dict[str, Any]]
    ) -> int:
        """Delegates to :func:`_context.aggressive_context_recovery`."""
        return await _context.aggressive_context_recovery(self, system, messages)

    @staticmethod
    def _repair_messages(messages: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_context.repair_messages`."""
        return _context.repair_messages(messages)

    def _build_system_prompt(self) -> str:
        """Delegates to :func:`_context.build_system_prompt`."""
        return _context.build_system_prompt(self)

    # ------------------------------------------------------------------
    # Goal decomposition — delegate to ``_planner_dispatch``
    # ------------------------------------------------------------------

    async def _try_decompose(self, user_input: str, *, enabled: bool = True) -> str | None:
        """Delegates to :func:`_planner_dispatch.try_decompose`.

        Async because the planner path awaits ``loop._call_llm`` — single
        async LLM dispatch, no thread-pool hop.
        """
        if not enabled:
            return None
        return await _planner_dispatch.try_decompose(self, user_input)

    # ------------------------------------------------------------------
    # Durable child mailbox — delegate to ``_collaboration_mailbox``
    # ------------------------------------------------------------------

    def _admit_collaboration_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        user_input: str = "",
        round_idx: int = 0,
    ) -> int:
        """Delegates to :func:`_collaboration_mailbox.admit_collaboration_messages`."""
        return _collaboration_mailbox.admit_collaboration_messages(
            self,
            messages,
            user_input=user_input,
            round_idx=round_idx,
        )

    # ------------------------------------------------------------------
    # LLM call (stays in this file — tightly coupled to ``arun`` body)
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        round_idx: int = 0,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        allow_tools: bool = True,
    ) -> AgenticResponse | None:
        """Multi-provider LLM call via :class:`LLMAdapter` (P1 Gateway pattern).

        Delegates to ``self._new_adapter.acomplete()`` (provider-specific
        conversion, retry, failover). Returns a normalized
        ``AgenticResponse`` or None on failure. Raises ``UserCancelledError``
        on Ctrl+C (caught by ``arun()``). Optional ``model`` overrides the
        request model for one call without mutating ``self.model``. Optional
        ``response_schema`` overrides the loop-level schema for this call only.
        ``allow_tools=False`` keeps auxiliary planner / judge calls on their
        structured text contract instead of inheriting the action tool surface.

        The context-overflow check mutates the shared messages list in place,
        so it must run before the adapter request is assembled.
        """
        effective_model = model or self.model
        # Shared list — in-place pruning must persist into later rounds.
        await self._check_context_overflow(system, messages)

        # WRAP_UP: force text-only when approaching limits
        wrap_up = False
        if self.max_rounds > 0:
            remaining = self.max_rounds - round_idx
            wrap_up = remaining <= self.WRAP_UP_HEADROOM
        if not wrap_up and self._time_budget_s > 0:
            import time as _time

            remaining_time = self._time_budget_s - (_time.monotonic() - self._loop_start_time)
            wrap_up = remaining_time <= self._WRAP_UP_TIME_HEADROOM_S
        tool_choice: dict[str, str] = (
            {"type": "none"} if wrap_up or not allow_tools else {"type": "auto"}
        )

        # Adaptive compute — context-proportional caps; the only adaptive
        # case left is wrap-up (overthinking exits the loop instead).
        from core.config import settings as _settings
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        ctx_window = MODEL_CONTEXT_WINDOW.get(effective_model, 200_000)

        adaptive_max_tokens = self.max_tokens
        adaptive_thinking = self._thinking_budget
        adaptive_effort = self._effort
        if wrap_up:
            # wrap-up: minimal budget (0.5% of window, floor 4096)
            adaptive_max_tokens = max(4096, min(self.max_tokens, ctx_window // 200))
            adaptive_thinking = 0
            adaptive_effort = "low"

        # config-driven temperature (1.0 default)
        loop_temperature = _settings.temperature_agent_loop

        # build the adapter-neutral request, then translate back to
        # AgenticResponse so the rest of the loop is unchanged
        from core.llm.adapters.translation import (
            agentic_response_from_adapter_result,
            build_adapter_request,
        )

        # prior session_id → adapter ``--resume <id>`` (claude-cli reuses the
        # cached prefix); empty on first turn (behaviour unchanged)
        prior_session_id = _load_prior_session_id(self._session_id)
        session_allowed_tools = (
            frozenset(self._allowed_tool_names) if self._allowed_tool_names is not None else None
        )

        request_tools: list[dict[str, Any]] | BoundToolPlan
        if not allow_tools:
            request_tools = []
        elif self._bound_tool_plan is not None:
            request_tools = self._bound_tool_plan
        else:
            request_tools = self._tools
        raw_denied_tools: Any = getattr(self.executor, "_denied_tools", frozenset())
        executor_denied_tools = (
            frozenset(raw_denied_tools) if isinstance(raw_denied_tools, Set) else frozenset()
        )
        raw_executable_tools: Any = ()
        if allow_tools:
            if self._bound_tool_plan is not None:
                raw_executable_tools = getattr(
                    self.executor,
                    "_bound_allowed_tools",
                    (),
                )
            else:
                raw_executable_tools = getattr(self.executor, "_handlers", ())
        executor_executable_tools = (
            frozenset(raw_executable_tools)
            if isinstance(raw_executable_tools, (Mapping, Set))
            else frozenset()
        )
        req = build_adapter_request(
            model=effective_model,
            system=system,
            messages=messages,
            tools=request_tools,
            transient_tools=(
                list(self._transient_tools)
                if allow_tools and self._bound_tool_plan is not None
                else None
            ),
            transient_deferred_tool_names=(
                self._transient_deferred_tool_names
                if allow_tools and self._bound_tool_plan is not None
                else ()
            ),
            tool_choice=tool_choice,
            max_tokens=adaptive_max_tokens,
            temperature=loop_temperature,
            thinking_budget=adaptive_thinking,
            effort=adaptive_effort,
            allowed_tool_names=session_allowed_tools,
            denied_tool_names=executor_denied_tools,
            executable_tool_names=executor_executable_tools,
            resume_session_id=prior_session_id,
            # per-loop schema → claude-cli --json-schema / codex --output-schema
            response_schema=(
                response_schema if response_schema is not None else self._response_schema
            ),
        )
        import uuid as _uuid

        llm_call_id = f"llm-{self._turn_id}-{round_idx + 1}-{_uuid.uuid4().hex[:8]}"
        correlation = {
            "session_id": self._session_id,
            "turn_id": self._turn_id,
            "llm_call_id": llm_call_id,
            "llm_attempt_id": "",
        }
        bound_request = req
        original_adapter = self._new_adapter
        llm_request = await self._middleware_registry.llm_request(
            LlmCallRequest(
                adapter=original_adapter,
                request=req,
                correlation=correlation,
            )
        )
        if self._bound_tool_plan is not None and llm_request.adapter is not original_adapter:
            raise ValueError("LLM middleware cannot change a bound request adapter")
        call_adapter = llm_request.adapter
        req = llm_request.request
        if self._bound_tool_plan is not None:
            _validate_bound_request_rewrite(bound_request, req)
        if session_allowed_tools is not None and self._bound_tool_plan is None:
            from dataclasses import replace

            effective_allowed = session_allowed_tools
            if req.allowed_tool_names is not None:
                effective_allowed &= req.allowed_tool_names
            req = replace(
                req,
                allowed_tool_names=effective_allowed,
                tools=tuple(tool for tool in req.tools if tool.name in effective_allowed),
                deferred_tool_names=tuple(
                    name for name in req.deferred_tool_names if name in effective_allowed
                ),
            )
        elif session_allowed_tools is not None and (
            req.allowed_tool_names != session_allowed_tools
            or any(tool.name not in session_allowed_tools for tool in req.tools)
        ):
            raise ValueError("bound tool request escaped its pre-filtered allowlist")
        effective_model = req.model
        adapter_name = getattr(call_adapter, "name", "<unknown>")
        effective_provider = getattr(call_adapter, "provider", self._provider)
        llm_attempt_number = 0

        async def _complete_attempt(adapter: Any, request: Any) -> Any:
            nonlocal llm_attempt_number
            llm_attempt_number += 1
            attempt_correlation = {
                **correlation,
                "llm_attempt_id": f"{llm_call_id}:attempt-{llm_attempt_number}",
            }
            current = LlmCallRequest(
                adapter=adapter,
                request=request,
                correlation=attempt_correlation,
            )

            async def terminal(effective: LlmCallRequest) -> Any:
                import time as _llm_call_time

                from core.hooks.dispatch import fire_hook_async

                started_at = _llm_call_time.monotonic()
                active_adapter = effective.adapter
                active_request = effective.request
                active_name = getattr(active_adapter, "name", "<unknown>")
                active_provider = getattr(active_adapter, "provider", effective_provider)
                await fire_hook_async(
                    self._hooks,
                    HookEvent.LLM_CALL_STARTED,
                    {
                        **attempt_correlation,
                        "model": active_request.model,
                        "provider": active_provider,
                        "adapter": active_name,
                    },
                )
                try:
                    attempt_result = await active_adapter.acomplete(active_request)
                except BaseException as exc:
                    await fire_hook_async(
                        self._hooks,
                        HookEvent.LLM_CALL_ENDED,
                        {
                            **attempt_correlation,
                            "model": active_request.model,
                            "provider": active_provider,
                            "adapter": active_name,
                            "latency_ms": (_llm_call_time.monotonic() - started_at) * 1_000,
                            "error": str(exc) or type(exc).__name__,
                        },
                    )
                    raise

                usage = getattr(attempt_result, "usage", None)
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                cached_input_tokens = int(getattr(usage, "cached_input_tokens", 0) or 0)
                reasoning_tokens = int(getattr(usage, "reasoning_tokens", 0) or 0)
                cache_write_tokens = int(getattr(usage, "cache_write_tokens", 0) or 0)
                try:
                    from core.llm.token_tracker import calculate_cost

                    cost_usd = float(
                        calculate_cost(
                            active_request.model,
                            input_tokens,
                            output_tokens,
                            cache_creation_tokens=cache_write_tokens,
                            cache_read_tokens=cached_input_tokens,
                        )
                    )
                except Exception:
                    log.warning(
                        "calculate_cost failed for model=%s — recording cost_usd=0.0 "
                        "(cost limiter will under-count this call)",
                        active_request.model,
                        exc_info=True,
                    )
                    cost_usd = 0.0
                await fire_hook_async(
                    self._hooks,
                    HookEvent.LLM_CALL_ENDED,
                    {
                        **attempt_correlation,
                        "model": active_request.model,
                        "provider": active_provider,
                        "adapter": active_name,
                        "latency_ms": (_llm_call_time.monotonic() - started_at) * 1_000,
                        "error": None,
                        "usage": {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cached_input_tokens": cached_input_tokens,
                            "reasoning_tokens": reasoning_tokens,
                            "cache_write_tokens": cache_write_tokens,
                        },
                        "cost_usd": cost_usd,
                    },
                )
                return attempt_result

            return await self._middleware_registry.llm_execution(current, terminal)

        async def _on_fail_fast_pre_execution_retry(
            exc: Exception,
            attempt: int,
            max_attempts: int,
        ) -> None:
            self._pre_execution_retry_errors.append(type(exc).__name__)
            if self._hooks:
                try:
                    await self._hooks.trigger_async(
                        HookEvent.LLM_CALL_RETRIED,
                        {
                            "session_id": self._session_id,
                            "turn_id": self._turn_id,
                            "llm_call_id": llm_call_id,
                            "llm_attempt_id": f"{llm_call_id}:attempt-{attempt}",
                            "model": effective_model,
                            "provider": effective_provider,
                            "adapter": adapter_name,
                            "error_type": type(exc).__name__,
                            "delay_s": _FAIL_FAST_RETRY_DELAY_S,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                        },
                    )
                except Exception:
                    log.debug("LLM_CALL_RETRIED hook trigger failed", exc_info=True)

        try:
            result = await _acomplete_with_fail_fast_pre_execution_retry(
                call_adapter,
                req,
                on_retry=_on_fail_fast_pre_execution_retry,
                complete=_complete_attempt,
            )
        except Exception as exc:
            error_detail = str(exc) or type(exc).__name__
            self._last_llm_error = error_detail
            log.warning(
                "AgenticLoop: adapter.acomplete failed (adapter=%s): %s",
                adapter_name,
                error_detail,
            )
            if _fail_fast_adapter_errors_enabled():
                raise
            response = None
        else:
            response = agentic_response_from_adapter_result(result)
            # persist the emitted session_id for the next turn's resume
            # (no-op for non-claude-cli adapters)
            emitted_sid = getattr(result, "session_id", "")
            _persist_session_id(self._session_id, emitted_sid)
            # cache for the SESSION_ENDED claude_cli_session_id write
            if emitted_sid:
                self._last_emitted_session_id = emitted_sid

        if response is None:
            adapter_err = getattr(call_adapter, "_last_error", None)
            if adapter_err:
                self._last_llm_error = str(adapter_err)
            elif not self._last_llm_error:
                self._last_llm_error = f"All {self._provider} models exhausted"

        # surface reasoning summaries to AgenticUI per finished item
        if response is not None and not self._quiet:
            summaries = getattr(response, "reasoning_summaries", None) or []
            for summary in summaries:
                if not summary:
                    continue
                from core.ui.agentic_ui import emit_reasoning_summary

                emit_reasoning_summary(self._provider, self.model, summary)

        return response

    # ------------------------------------------------------------------
    # Response handling — delegate to ``_response``
    # ------------------------------------------------------------------

    def _extract_text(self, response: Any) -> str:
        """Delegates to :func:`_response.extract_text`."""
        return _response.extract_text(self, response)

    def _serialize_content(self, content: list[Any]) -> list[dict[str, Any]]:
        """Delegates to :func:`_response.serialize_content`."""
        return _response.serialize_content(self, content)

    def _track_usage(self, response: Any) -> None:
        """Delegates to :func:`_response.track_usage`."""
        return _response.track_usage(self, response)

    async def _track_usage_async(self, response: Any) -> None:
        """Delegates to :func:`_response.track_usage_async`."""
        return await _response.track_usage_async(self, response)

    def _update_tool_error_tracking(self, tool_results: list[dict[str, Any]]) -> None:
        """Delegates to :func:`_response.update_tool_error_tracking`."""
        return _response.update_tool_error_tracking(self, tool_results)

    def _check_convergence_break(self) -> bool:
        """Delegates to :func:`_response.check_convergence_break`."""
        return _response.check_convergence_break(self)

    def _check_repeated_success_no_progress(self) -> bool:
        """Delegates to :func:`_response.check_repeated_success_no_progress`."""
        return _response.check_repeated_success_no_progress(self)


# ---------------------------------------------------------------------------
# Re-exports for direct ``core.agent.loop.agent_loop`` imports.
# ---------------------------------------------------------------------------

__all__ = [
    "AGENTIC_TOOLS",
    "MAX_TOOL_RESULT_TOKENS",
    "TOOL_LAZY_LOAD_THRESHOLD",
    "AgenticLoop",
    "AgenticResult",
    "_ContextExhaustedError",
    "_context_exhausted_message",
    "get_agentic_tools",
]

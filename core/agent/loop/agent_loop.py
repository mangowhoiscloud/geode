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
import logging
from typing import TYPE_CHECKING, Any

from core.agent.conversation import ConversationContext
from core.agent.error_recovery import ErrorRecoveryStrategy
from core.agent.tool_executor import (
    ToolCallProcessor,
    ToolExecutor,
)
from core.hooks import HookEvent, HookSystem
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError
from core.ui.agentic_ui import OperationLogger
from core.ui.status import TextSpinner

from . import (
    _context,
    _lifecycle,
    _model_switching,
    _planner_dispatch,
    _response,
    _sub_agent_announce,
)

# Re-exported for backward-compat module-attribute access
# (some tests/utilities reach into ``core.agent.loop.MAX_TOOL_RESULT_TOKENS``)
from ._tool_factory import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,
    TOOL_LAZY_LOAD_THRESHOLD,
    get_agentic_tools,
)
from .models import AgenticResult, _context_exhausted_message, _ContextExhaustedError

if TYPE_CHECKING:
    from core.agent.capability_graph import CapabilityGraph
    from core.agent.task_preflight import TaskPreflight
    from core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


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
        cost_budget: float = 0.0,  # 0 = no cost limit (Karpathy P3)
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
        source: str = "",
        session_id: str = "",
        response_schema: dict[str, Any] | None = None,
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
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self._thinking_budget = thinking_budget
        self._effort = effort
        self._time_budget_s = time_budget_s
        # Adaptive compute: track consecutive text-only rounds for overthinking detection
        self._consecutive_text_only_rounds = 0
        self._total_empty_rounds = 0
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
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._hooks = hooks
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
        # merge native + MCP tools; allowlist as force_include so the global
        # tool_policy can't strip a tool the sub-agent's toolkit granted
        mcp_tool_list = mcp_manager.get_all_tools() if mcp_manager is not None else None
        self._tools = get_agentic_tools(
            tool_registry,
            mcp_tools=mcp_tool_list,
            force_include=allowed_tool_names,
            provider=self._provider,
            source=self._source,
        )
        if allowed_tool_names is not None:
            self._tools = [t for t in self._tools if t.get("name") in allowed_tool_names]
        self._capability_graph: CapabilityGraph | None = None
        self._task_preflight: TaskPreflight | None = None
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

        # Tier 1 transcript: append-only JSONL event stream
        self._transcript: Any | None = None
        self._session_id: str = ""
        try:
            import uuid as _uuid

            from core.observability.transcript import SessionTranscript

            # caller-provided session_id wins (keeps the worker's artifacts
            # under one sub_agents/<task_id>/ dir); else ephemeral s-<uuid>
            if session_id:
                self._session_id = session_id
            else:
                self._session_id = f"s-{_uuid.uuid4().hex[:12]}"
            self._transcript = SessionTranscript(self._session_id)
        except Exception:
            log.warning("Transcript init failed", exc_info=True)
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
            self._evidence_ledger: Any | None = EvidenceLedger.for_session(self._session_id)
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
            transcript=self._transcript,
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

        from core.agent.context_manager import ContextWindowManager

        self._ctx_mgr = ContextWindowManager(hooks=hooks, quiet=quiet)

        # Convergence detection — 3 identical errors break the loop.
        from core.agent.convergence import ConvergenceDetector

        self._convergence = ConvergenceDetector()

        # Diversity forcing — prevent same tool 5x consecutively
        self._consecutive_tool_tracker: list[str] = []

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

    def _save_checkpoint(self, user_input: str, round_idx: int = 0) -> None:
        """Delegates to :func:`_lifecycle.save_checkpoint`."""
        return _lifecycle.save_checkpoint(self, user_input, round_idx)

    def mark_session_completed(self) -> None:
        """Delegates to :func:`_lifecycle.mark_session_completed`."""
        return _lifecycle.mark_session_completed(self)

    def _record_transcript_end(self, result: Any) -> None:
        """Delegates to :func:`_lifecycle.record_transcript_end`."""
        return _lifecycle.record_transcript_end(self, result)

    def _finalize_and_return(
        self,
        result: AgenticResult,
        user_input: str,
        round_idx: int,
    ) -> AgenticResult:
        """Delegates to :func:`_lifecycle.finalize_and_return`."""
        return _lifecycle.finalize_and_return(self, result, user_input, round_idx)

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

        await reflect_async(
            self.cognitive_state,
            tool_results,
            model=reflection_model,
            max_tokens=settings.cognitive_reflection_max_tokens,
            provider=reflection_provider,
            source=reflection_source,
        )

    async def _emit_session_start_signals(self, user_input: str) -> AgenticResult | None:
        """Emit the session-start signals. Owns the USER_INPUT_RECEIVED
        interceptor, cognitive-state goal init + ContextVar bind,
        COGNITIVE_PERCEIVE emit, conversation-context append, transcript
        ``record_session_start`` / ``record_user_message``, and the
        SESSION_STARTED hook.

        Returns ``None`` on the happy path. Returns an
        :class:`AgenticResult` (with ``termination_reason="input_blocked"``)
        when the USER_INPUT_RECEIVED interceptor blocks the input —
        ``arun`` surfaces that result back to the caller verbatim.
        """
        # Hook: USER_INPUT_RECEIVED (interceptor — can block input)
        if self._hooks:
            intercept = await self._hooks.trigger_interceptor_async(
                HookEvent.USER_INPUT_RECEIVED,
                {"user_input": user_input, "session_id": self._session_id},
            )
            if intercept.blocked:
                return AgenticResult(
                    text=intercept.reason,
                    rounds=0,
                    termination_reason="input_blocked",
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
        )

        set_cognitive_state(self.cognitive_state)
        set_session_id(self._session_id)
        # Sub-agent lineage → Episode rows (empty for top-level loops)
        set_parent_session_key(self._parent_session_key)
        set_parent_session_id(self._parent_session_id)
        await self._emit_cognitive(
            HookEvent.COGNITIVE_PERCEIVE,
            user_input=user_input,
        )

        # Add user message to conversation context
        self.context.add_user_message(user_input)

        # Transcript: session start + user message
        if self._transcript is not None:
            self._transcript.record_session_start(model=self.model, provider=self._provider)
            self._transcript.record_user_message(user_input)

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
            return AgenticResult(
                text=exc.user_message(),
                rounds=round_idx + 1,
                termination_reason="billing_error",
            )
        except UserCancelledError:
            spinner.stop()
            log.info("LLM call interrupted by user")
            return AgenticResult(
                text="Interrupted.",
                rounds=round_idx + 1,
                termination_reason="user_cancelled",
            )

    async def _sync_model_and_rebuild_prompt(
        self,
        system_prompt: str,
        decomposition_hint: str | None,
        reflection_hint: str | None = None,
    ) -> str:
        """Sync model drift + rebuild the system prompt.

        Rebuilds when the model drifted (``settings.model`` changed) or
        ``_prompt_dirty`` is set (direct ``update_model_async``). On
        rebuild, re-applies the decomposition / reflection / plan hints so
        a mid-arun drift doesn't drop them. Returns the (possibly-rebuilt)
        prompt; clears ``_prompt_dirty``.
        """
        drift_detected = await self._sync_model_from_settings_async()
        prompt_dirty = self._prompt_dirty
        if drift_detected or prompt_dirty:
            system_prompt = self._build_system_prompt()
            if decomposition_hint:
                system_prompt += "\n\n" + decomposition_hint
            if reflection_hint:
                system_prompt += "\n\n" + reflection_hint
            # re-apply the active plan on rebuild (getattr tolerates stub loops)
            _plan_consume = getattr(self, "_consume_plan_hint", None)
            plan_hint = _plan_consume() if callable(_plan_consume) else ""
            if isinstance(plan_hint, str) and plan_hint:
                system_prompt += "\n\n" + plan_hint
            self._prompt_dirty = False
            # Fire PROMPT_ASSEMBLED on each per-round rebuild (no-op if no hooks)
            hooks = getattr(self, "_hooks", None)
            if hooks:
                from core.hooks import HookEvent

                reason = "model_drift" if drift_detected else "prompt_dirty"
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

    async def _maybe_replan_async(self, round_idx: int) -> None:
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
            trigger = should_replan(
                round_idx=round_idx,
                plan=metrics.active_plan,
                verify_failed=not metrics.last_verify_passed,
                verify_should_retry=metrics.last_verify_should_retry,
            )
            if trigger is None:
                return
            # Abandon path: a verify_fail past replan_max_attempts on one
            # step advances the plan instead of calling the planner (step
            # is stuck). The cadence trigger isn't capped.
            if trigger == "verify_fail" and metrics.active_plan is not None:
                metrics.record_step_attempt()
                cap = _replan_max_attempts()
                if metrics.replan_attempts_on_current_step > cap:
                    advanced = metrics.active_plan.advance(completed=False)
                    # new step → reset the per-step counter
                    metrics.set_active_plan(advanced, reset_attempts=True)
                    self._prompt_dirty = True
                    log.info(
                        "Replan abandon: step exceeded %d attempts; advancing plan",
                        cap,
                    )
                    return
            # synthetic turn_result — replan_async only reads ``.text``
            from types import SimpleNamespace

            recent_text = ""
            try:
                recent_text = self._tool_processor.tool_log[-1].get("result", "")
            except Exception:
                log.debug("recent tool_log read for replanner failed", exc_info=True)
                recent_text = ""
            stub_result = SimpleNamespace(text=str(recent_text))
            new_plan = await replan_async(
                self, plan=metrics.active_plan, turn_result=stub_result, trigger=trigger
            )
            if new_plan is None:
                log.info("Replan trigger=%s: planner failed; keeping prior plan", trigger)
                return
            metrics.record_replan(trigger)
            metrics.set_active_plan(new_plan)
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
        ``GEODE_SESSION_TIME_BUDGET_S`` overrides the default (0 disables).
        Failures NEVER raise.
        """
        import os

        try:
            from core.agent.budget import (
                DEFAULT_HANDOFF_THRESHOLD_S,
                DEFAULT_TIME_BUDGET_S,
                start_session_budget,
            )
            from core.observability.session_metrics import current_session_metrics

            metrics = current_session_metrics()
            if metrics.time_budget_total_s > 0.0:
                return  # Already started in this session.
            raw = os.environ.get("GEODE_SESSION_TIME_BUDGET_S")
            if raw is not None:
                try:
                    total = float(raw)
                except ValueError:
                    total = DEFAULT_TIME_BUDGET_S
            else:
                total = DEFAULT_TIME_BUDGET_S
            if total <= 0.0:
                return  # Explicitly disabled.
            start_session_budget(
                total_seconds=total,
                handoff_threshold_seconds=DEFAULT_HANDOFF_THRESHOLD_S,
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
            from core.observability.session_metrics import current_session_metrics

            check = check_session_budget()
            if check.handoff_due:
                metrics = current_session_metrics()
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
                if self._transcript is not None:
                    try:
                        self._transcript.record_lifecycle_event(
                            event="handoff_triggered",
                            component="agentic_loop",
                            level="warning",
                            payload=payload,
                            action="agent.handoff_triggered",
                            entity_type="session",
                            entity_id=self._session_id,
                        )
                    except Exception:
                        log.warning("Transcript handoff_triggered record failed", exc_info=True)
                # flip the sessions row to handoff_state=PENDING (read-write
                # parity; no-op when no session row exists yet)
                self._persist_handoff_request()
                return "session_time_budget_handoff"
            if check.expired:
                return "session_time_budget_expired"
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
        return AgenticResult(
            text=text,
            tool_calls=self._tool_processor.tool_log,
            rounds=rounds,
            error="model_action_required",
            termination_reason="model_action_required",
        )

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
        result = AgenticResult(
            text=await _context_exhausted_message(user_input),
            tool_calls=self._tool_processor.tool_log,
            rounds=round_idx + 1,
            error="context_exhausted",
            termination_reason="context_exhausted",
        )
        return await self._afinalize_and_return(result, user_input, round_idx + 1)

    # ------------------------------------------------------------------
    # Tool list refresh — delegate to ``_response``
    # ------------------------------------------------------------------

    def refresh_tools(self) -> int:
        """Delegates to :func:`_response.refresh_tools`."""
        return _response.refresh_tools(self)

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
            if self._transcript is not None:
                self._transcript.record_lifecycle_event(
                    event="task_preflight",
                    component="agentic_loop",
                    level="info",
                    payload={
                        "capability_graph": graph_summary(capability_graph),
                        "preflight": self._task_preflight,
                    },
                    action="agent.preflight",
                    entity_type="session",
                    entity_id=self._session_id,
                )
            return preflight_hint
        except Exception:
            log.debug("Task preflight failed", exc_info=True)
            return ""

    async def arun(self, user_input: str) -> AgenticResult:
        """Run the agentic loop until LLM emits end_turn or max rounds."""
        self._tool_processor.reset()
        self._op_logger.reset()

        # Wire conversation context so /model command guard can check size
        from core.cli.commands import set_conversation_context

        set_conversation_context(self.context)

        # Lazy MCP tool refresh — load tools empty at init (startup timing gap)
        if self._mcp_manager is not None and len(self._tools) < TOOL_LAZY_LOAD_THRESHOLD:
            added = self.refresh_tools()
            if added > 0:
                log.info("MCP tools lazy-loaded: +%d tools (total %d)", added, len(self._tools))

        preflight_hint = self._prepare_task_preflight(user_input)

        # Goal decomposition — break compound requests into sub-goal DAGs
        # (planner LLM call; the Plan is installed on SessionMetrics).
        try:
            decomposition_hint = await self._try_decompose(user_input)
        except BillingError as exc:
            self._emit_quota_panel(exc)
            return AgenticResult(
                text=exc.user_message(),
                rounds=0,
                termination_reason="billing_error",
            )

        intercept_result = await self._emit_session_start_signals(user_input)
        if intercept_result is not None:
            return intercept_result

        messages = self.context.get_messages()

        system_prompt = self._build_system_prompt()
        if decomposition_hint:
            system_prompt += "\n\n" + decomposition_hint
        if preflight_hint:
            system_prompt += "\n\n" + preflight_hint

        # Failure reflection injection — prepend the prior turn's verify-FAIL
        # analysis (consume semantics; cleared after read).
        reflection_hint = self._consume_reflection_hint()
        if reflection_hint:
            system_prompt += "\n\n" + reflection_hint

        # Plan injection — render the current-step ``<plan>`` block
        # (read-only consume; plan persists until advance / replan).
        plan_hint = self._consume_plan_hint()
        if plan_hint:
            system_prompt += "\n\n" + plan_hint

        # Prune old messages to stay within context budget (Karpathy P6)
        self._maybe_prune_messages(messages)

        import time as _time

        self._loop_start_time = _time.monotonic()
        # session-wide budget (separate from per-loop _time_budget_s; either
        # may fire first)
        self._maybe_start_session_budget()
        # tracker snapshot at entry → finalize computes a per-arun usage
        # delta without double-counting sibling loops on the shared tracker
        from core.llm.token_tracker import get_tracker as _get_tracker

        self._usage_snapshot = _get_tracker().snapshot()
        round_idx = 0
        while True:
            if self._check_round_guards(round_idx) is not None:
                break

            is_last_round = (self.max_rounds > 0) and (round_idx == self.max_rounds - 1)
            self._op_logger.begin_round("AgenticLoop")

            # Dynamic Replan trigger (verify-FAIL / cadence); the rebuild
            # below picks up the new plan via _consume_plan_hint.
            await self._maybe_replan_async(round_idx)

            system_prompt = await self._sync_model_and_rebuild_prompt(
                system_prompt, decomposition_hint, reflection_hint=reflection_hint
            )

            # Poll for sub-agent announced results (OpenClaw Spawn+Announce)
            self._check_announced_results(messages)

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

            # spinner while waiting for the LLM (IPC event or TextSpinner)
            from core.ui.agentic_ui import _ipc_writer_local

            _ipc_writer = getattr(_ipc_writer_local, "writer", None)
            if _ipc_writer is not None and not self._quiet:
                _ipc_writer.send_event("thinking_start", model=self.model, round=round_idx + 1)
                _spinner = TextSpinner("", quiet=True)  # no-op spinner
            else:
                label = "Thinking..." if round_idx == 0 else f"Thinking... (round {round_idx + 1})"
                _spinner = TextSpinner(label, quiet=self._quiet)
            _spinner.start()
            try:
                _llm_outcome = await self._dispatch_llm_call(
                    system_prompt, messages, round_idx, _spinner
                )
                if isinstance(_llm_outcome, AgenticResult):
                    return _llm_outcome
                response = _llm_outcome
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
                    # builder (raw SDK JSON must not leak into the transcript).
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

                # auto-checkpoint before retry (resume after a model switch)
                self._sync_messages_to_context(messages)
                self._save_checkpoint(user_input, round_idx=round_idx)

                self._consecutive_llm_failures += 1

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

            # Guard 3: Cost budget (Karpathy P3 — resource budget)
            if self._cost_budget > 0:
                try:
                    from core.llm.token_tracker import get_tracker as _get_cost_tracker

                    _cost_tracker = _get_cost_tracker()
                    _session_cost = _cost_tracker.accumulator.total_cost_usd

                    # Proactive warning at 80% of budget (once per session)
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
                        result = AgenticResult(
                            text=text,
                            tool_calls=self._tool_processor.tool_log,
                            rounds=round_idx + 1,
                            error="cost_budget_exceeded",
                            termination_reason="cost_budget_exceeded",
                        )
                        return await self._afinalize_and_return(result, user_input, round_idx + 1)
                except Exception:
                    log.debug("Cost budget check failed", exc_info=True)

            # Overthinking detection — N consecutive long-text/no-tool
            # rounds stop the loop with user_clarification_needed (threshold
            # is context-proportional, 1% / floor 1024).
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
                    result = AgenticResult(
                        text=clarification,
                        tool_calls=self._tool_processor.tool_log,
                        rounds=round_idx + 1,
                        termination_reason="user_clarification_needed",
                    )
                    return await self._afinalize_and_return(result, user_input, round_idx + 1)
            else:
                self._consecutive_text_only_rounds = 0

            if response.stop_reason == "refusal":
                # Fable 5 safety decline (HTTP 200, often empty) — surface it
                # honestly instead of a silent empty turn.
                # ref: https://platform.claude.com/docs/en/about-claude/models/migration-guide
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                stop_details = getattr(response, "stop_details", None)
                category = stop_details.get("category") if isinstance(stop_details, dict) else None
                refusal_text = self._extract_text(response).strip() or (
                    "The model declined this request"
                    + (f" (safety classifier category: {category})" if category else "")
                    + ". Rephrase the request or retry on another model via /model."
                )
                result = AgenticResult(
                    text=refusal_text,
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    termination_reason="model_refusal",
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

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
                # Codex phase for the next-turn replay (other adapters ignore)
                _phase = getattr(response, "assistant_phase", "")
                if _phase:
                    _assistant_msg["phase"] = _phase
                messages.append(_assistant_msg)
                self._sync_messages_to_context(messages)
                await self._record_text_only_round(round_idx, text=text)
                reason = "forced_text" if is_last_round else "natural"
                result = AgenticResult(
                    text=text,
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    termination_reason=reason,
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            tool_results = await self._run_cognitive_act_observe_cycle(response, round_idx)

            # backpressure on consecutive tool failures + convergence detection
            self._update_tool_error_tracking(tool_results)

            if self._check_convergence_break():
                from core.ui.agentic_ui import emit_convergence_detected

                last_err = (
                    self._convergence.recent_errors[-1]
                    if self._convergence.recent_errors
                    else "unknown"
                )
                emit_convergence_detected(last_err, round_idx + 1)
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text=(
                        "Detected repeating failure pattern. Breaking loop to avoid infinite retry."
                    ),
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    error="convergence_detected",
                    termination_reason="convergence_detected",
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

            if self._check_repeated_success_no_progress():
                from core.ui.agentic_ui import emit_repeated_success_no_progress

                tool_name = self._convergence.last_success_tool or "unknown"
                streak = self._convergence.repeated_success_streak
                emit_repeated_success_no_progress(tool_name, streak, round_idx + 1)
                self._op_logger.finalize()
                self._sync_messages_to_context(messages)
                result = AgenticResult(
                    text=(
                        "Detected repeated successful tool results without new progress. "
                        "Breaking loop to avoid polling the same state indefinitely."
                    ),
                    tool_calls=self._tool_processor.tool_log,
                    rounds=round_idx + 1,
                    error="repeated_success_no_progress",
                    termination_reason="repeated_success_no_progress",
                )
                return await self._afinalize_and_return(result, user_input, round_idx + 1)

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
                        "Do NOT silently answer from training data."
                    ),
                }
                tool_results.append(backpressure_hint)

            # Diversity forcing — prevent same tool 5x consecutively
            # (read/search tools are naturally repetitive → exempt)
            _DIVERSITY_EXEMPT: frozenset[str] = frozenset(
                {
                    "read_file",
                    "read_text_file",
                    "search_files",
                    "list_directory",
                    "memory_search",
                    "note_read",
                    "web_search",
                    "general_web_search",
                    "sequentialthinking",
                }
            )
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    self._consecutive_tool_tracker.append(getattr(block, "name", ""))
            if len(self._consecutive_tool_tracker) > 10:
                self._consecutive_tool_tracker = self._consecutive_tool_tracker[-10:]
            if len(self._consecutive_tool_tracker) >= 5:
                _last_5 = self._consecutive_tool_tracker[-5:]
                if len(set(_last_5)) == 1:
                    _repeated_tool = _last_5[0]
                    if _repeated_tool in _DIVERSITY_EXEMPT:
                        self._consecutive_tool_tracker.clear()
                    else:
                        diversity_hint = {
                            "type": "text",
                            "text": (
                                f"[system] The tool '{_repeated_tool}' has been called 5 times "
                                "consecutively with similar results. "
                                "Try a different approach or tool to make progress."
                            ),
                        }
                        tool_results.append(diversity_hint)
                        self._consecutive_tool_tracker.clear()

                        from core.ui.agentic_ui import emit_tool_diversity_forced

                        emit_tool_diversity_forced(_repeated_tool, 5)
                        log.warning(
                            "Diversity forcing: %s called 5x — injecting hint",
                            _repeated_tool,
                        )

            # accumulate serialized messages for the next round
            assistant_content = self._serialize_content(response.content)
            _assistant_msg = {"role": "assistant", "content": assistant_content}
            # Codex reasoning passthrough (same as the end_turn branch)
            if getattr(response, "codex_reasoning_items", None):
                _assistant_msg["codex_reasoning_items"] = response.codex_reasoning_items
            # Codex phase on tool-use rounds
            _phase = getattr(response, "assistant_phase", "")
            if _phase:
                _assistant_msg["phase"] = _phase
            messages.append(_assistant_msg)
            messages.append({"role": "user", "content": tool_results})
            round_idx += 1

        # Loop exited via guard — determine reason
        self._op_logger.finalize()
        elapsed = _time.monotonic() - self._loop_start_time
        if self._time_budget_s > 0 and elapsed >= self._time_budget_s:
            from core.ui.agentic_ui import emit_time_budget_expired

            emit_time_budget_expired(self._time_budget_s, elapsed, round_idx)
            reason = "time_budget_expired"
            text = f"Time budget ({self._time_budget_s:.0f}s) expired after {round_idx} rounds."
        else:
            reason = "max_rounds"
            text = "Max agentic rounds reached. Please try a more specific request."
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._sync_messages_to_context(messages)
        result = AgenticResult(
            text=text,
            tool_calls=self._tool_processor.tool_log,
            rounds=round_idx,
            error=reason,
            termination_reason=reason,
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

    async def _try_decompose(self, user_input: str) -> str | None:
        """Delegates to :func:`_planner_dispatch.try_decompose`.

        Async because the planner path awaits ``loop._call_llm`` — single
        async LLM dispatch, no thread-pool hop.
        """
        return await _planner_dispatch.try_decompose(self, user_input)

    # ------------------------------------------------------------------
    # Sub-agent announce queue — delegate to ``_sub_agent_announce``
    # ------------------------------------------------------------------

    def _check_announced_results(self, messages: list[dict[str, Any]]) -> int:
        """Delegates to :func:`_sub_agent_announce.check_announced_results`."""
        return _sub_agent_announce.check_announced_results(self, messages)

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
    ) -> AgenticResponse | None:
        """Multi-provider LLM call via :class:`LLMAdapter` (P1 Gateway pattern).

        Delegates to ``self._new_adapter.acomplete()`` (provider-specific
        conversion, retry, failover). Returns a normalized
        ``AgenticResponse`` or None on failure. Raises ``UserCancelledError``
        on Ctrl+C (caught by ``arun()``). Optional ``model`` overrides the
        request model for one call without mutating ``self.model``.

        Invariants:
          * the context-overflow check mutates the SHARED messages list in
            place (must precede the per-request reminder copy, or the
            in-place prune evaporates and re-triggers every round);
          * the system reminder is appended LAST on a per-request COPY —
            the history prefix must stay byte-stable across rounds or the
            rolling message cache breakpoints never hit.
        """
        effective_model = model or self.model
        # shared list — in-place prune must persist (precede the reminder copy)
        await self._check_context_overflow(system, messages)

        # reminder appended LAST on a per-request copy — byte-stable history
        # prefix is load-bearing for prompt-cache breakpoints
        from core.agent.system_injection import append_system_reminder

        messages = append_system_reminder(messages, model=effective_model, round_idx=round_idx)

        # WRAP_UP: force text-only when approaching limits
        force_text = False
        if self.max_rounds > 0:
            remaining = self.max_rounds - round_idx
            force_text = remaining <= self.WRAP_UP_HEADROOM
        if not force_text and self._time_budget_s > 0:
            import time as _time

            remaining_time = self._time_budget_s - (_time.monotonic() - self._loop_start_time)
            force_text = remaining_time <= self._WRAP_UP_TIME_HEADROOM_S
        tool_choice: dict[str, str] = {"type": "none"} if force_text else {"type": "auto"}

        # Adaptive compute — context-proportional caps; the only adaptive
        # case left is wrap-up (overthinking exits the loop instead).
        from core.config import settings as _settings
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        ctx_window = MODEL_CONTEXT_WINDOW.get(effective_model, 200_000)

        adaptive_max_tokens = self.max_tokens
        adaptive_thinking = self._thinking_budget
        adaptive_effort = self._effort
        if force_text:
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

        req = build_adapter_request(
            model=effective_model,
            system=system,
            messages=messages,
            tools=self._tools,
            tool_choice=tool_choice,
            max_tokens=adaptive_max_tokens,
            temperature=loop_temperature,
            thinking_budget=adaptive_thinking,
            effort=adaptive_effort,
            resume_session_id=prior_session_id,
            # per-loop schema → claude-cli --json-schema / codex --output-schema
            response_schema=self._response_schema,
        )
        # Fire LLM_CALL_STARTED/ENDED with usage+cost for the SQLite
        # token/cost accumulator.
        import time as _llm_call_time

        _llm_t0 = _llm_call_time.monotonic()
        adapter_name = getattr(self._new_adapter, "name", "<unknown>")
        if self._hooks:
            try:
                await self._hooks.trigger_async(
                    HookEvent.LLM_CALL_STARTED,
                    {
                        "session_id": self._session_id,
                        "model": effective_model,
                        "provider": self._provider,
                        "adapter": adapter_name,
                    },
                )
            except Exception:
                log.debug("LLM_CALL_STARTED hook trigger failed", exc_info=True)

        try:
            result = await self._new_adapter.acomplete(req)
        except Exception as exc:
            self._last_llm_error = str(exc)
            log.warning(
                "AgenticLoop: adapter.acomplete failed (adapter=%s): %s",
                adapter_name,
                exc,
            )
            response = None
            if self._hooks:
                try:
                    await self._hooks.trigger_async(
                        HookEvent.LLM_CALL_ENDED,
                        {
                            "session_id": self._session_id,
                            "model": effective_model,
                            "provider": self._provider,
                            "adapter": adapter_name,
                            "latency_ms": (_llm_call_time.monotonic() - _llm_t0) * 1000,
                            "error": str(exc),
                        },
                    )
                except Exception:
                    log.debug("LLM_CALL_ENDED (error) hook trigger failed", exc_info=True)
        else:
            response = agentic_response_from_adapter_result(result)
            # persist the emitted session_id for the next turn's resume
            # (no-op for non-claude-cli adapters)
            emitted_sid = getattr(result, "session_id", "")
            _persist_session_id(self._session_id, emitted_sid)
            # cache for the SESSION_ENDED claude_cli_session_id write
            if emitted_sid:
                self._last_emitted_session_id = emitted_sid
            # LLM_CALL_ENDED with usage + locally-computed cost (no
            # double-count — the accumulator already records)
            if self._hooks:
                usage = getattr(result, "usage", None)
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                cached_input_tokens = int(getattr(usage, "cached_input_tokens", 0) or 0)
                try:
                    from core.llm.token_tracker import calculate_cost

                    cost_usd = float(
                        calculate_cost(
                            effective_model,
                            input_tokens,
                            output_tokens,
                            cache_read_tokens=cached_input_tokens,
                        )
                    )
                except Exception:
                    # graceful 0.0, but logged — an unpriced model would
                    # otherwise be FREE to the cost limiter (under-count)
                    log.warning(
                        "calculate_cost failed for model=%s — recording cost_usd=0.0 "
                        "(cost limiter will under-count this call)",
                        effective_model,
                        exc_info=True,
                    )
                    cost_usd = 0.0
                try:
                    await self._hooks.trigger_async(
                        HookEvent.LLM_CALL_ENDED,
                        {
                            "session_id": self._session_id,
                            "model": effective_model,
                            "provider": self._provider,
                            "adapter": adapter_name,
                            "latency_ms": (_llm_call_time.monotonic() - _llm_t0) * 1000,
                            "error": None,
                            "usage": {
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "cached_input_tokens": cached_input_tokens,
                            },
                            "cost_usd": cost_usd,
                        },
                    )
                except Exception:
                    log.debug("LLM_CALL_ENDED (success) hook trigger failed", exc_info=True)

        if response is None:
            adapter_err = getattr(self._new_adapter, "_last_error", None)
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

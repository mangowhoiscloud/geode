"""Bootstrap wiring — hooks, memory, session, config_watcher, task, plugin registry.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only references — kept out of cold-start via PEP 563 string
    # annotations (``from __future__ import annotations``).  Each class
    # is imported lazily inside its build_* function below; this block
    # exists solely so mypy / IDEs can resolve the annotations.
    from core.memory.context import ContextAssembler
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.port import SessionStorePort
    from core.memory.project import ProjectMemory
    from core.memory.user_profile import FileBasedUserProfile
    from core.observability.event_store import HookEventStore
    from core.orchestration.hot_reload import ConfigWatcher
    from core.orchestration.task_system import TaskGraph

from core.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default configuration (re-exported from runtime.py constants)
# ---------------------------------------------------------------------------
CONFIG_WATCHER_DEBOUNCE_MS = 300.0  # Avoid thrashing on rapid file changes


def _build_hook_event_store(log_dir: Path | str | None) -> HookEventStore:
    """Build the canonical event store, preserving explicit test isolation."""
    from core.observability.event_store import HookEventStore

    db_path = Path(log_dir) / "events.db" if log_dir is not None else None
    return HookEventStore(db_path=db_path)


# ---------------------------------------------------------------------------
# Episodic recorder hook handler — TOOL_EXEC_ENDED -> Episode row
# ---------------------------------------------------------------------------


def make_episodic_recorder_handler() -> tuple[str, Any]:
    """Create the TOOL_EXEC_ENDED handler that records Episode rows.

    Extracted from ``build_hooks``'s ``_reg_episodic_memory`` closure
    (trajectory audit 2026-07-03) so the subprocess worker's minimal hook
    bundle (:func:`build_worker_hooks`) can reuse the SAME recorder instead
    of duplicating the Episode-building logic. Session / lineage ids come
    from the ``core.agent.cognitive_state_ctx`` ContextVars that
    ``AgenticLoop.arun`` binds per turn — valid in both the full runtime
    and the worker subprocess.
    """
    import time

    from core.agent.cognitive_state_ctx import (
        get_cognitive_state,
        get_parent_session_id,
        get_parent_session_key,
        get_session_id,
    )
    from core.memory.episodic import Episode, _summarise_tool_input, get_episodic_store

    store = get_episodic_store()

    def _on_tool_end(_event: HookEvent, data: dict[str, Any]) -> None:
        tool_name = str(data.get("tool_name", "?"))
        tool_input = data.get("tool_input")
        has_error = bool(data.get("has_error"))
        result = data.get("result")
        error: str | None = None
        if has_error and isinstance(result, dict):
            error_val = result.get("error")
            if isinstance(error_val, str):
                error = error_val[:200]
        state = get_cognitive_state()
        snapshot = state.to_snapshot() if state is not None else {}
        session_id = get_session_id()
        # Sub-agent lineage — two complementary fields. Both empty
        # for top-level loops; non-empty when the active loop was
        # spawned via the OpenClaw spawn pattern (in-process or
        # subprocess via SubAgentManager → WorkerRequest).
        #   parent_session_key — OpenClaw routing key (group-by).
        #   parent_session_id  — parent's _session_id uuid (link-to).
        # The PR-E confidence-trajectory aggregator can group child
        # Episodes by routing key while still attributing each row
        # back to a concrete parent run via the uuid.
        parent_session_key = get_parent_session_key()
        parent_session_id = get_parent_session_id()
        round_raw = snapshot.get("round_count", 0)
        round_count = round_raw if isinstance(round_raw, int) else 0
        input_head_arg = tool_input if isinstance(tool_input, dict | str) else None
        episode = Episode(
            timestamp_ns=time.time_ns(),
            session_id=session_id,
            round=round_count,
            tool_name=tool_name,
            tool_input_head=_summarise_tool_input(input_head_arg),
            success=not has_error,
            error=error,
            duration_ms=float(data.get("duration_ms", 0.0)),
            cognitive_state=snapshot,
            parent_session_key=parent_session_key,
            parent_session_id=parent_session_id,
        )
        try:
            store.append(episode)
        except OSError:
            log.warning("episodic store append failed; skipping", exc_info=True)

    return "episodic_memory_recorder", _on_tool_end


def build_worker_hooks(
    *,
    session_key: str,
    run_id: str,
    log_dir: Path | str | None = None,
) -> HookSystem:
    """Minimal hook bundle for the subprocess sub-agent worker.

    Trajectory audit 2026-07-03 — ``core.agent.worker._run_agentic`` built
    its AgenticLoop with ``hooks=None``, so every subprocess sub-agent ran
    with ZERO hook consumers: no Episode rows and no operational events.

    Deliberately NOT :func:`build_hooks` — the worker is a short-lived
    subprocess and only needs the two trajectory rails:

    * bounded SQLite event sink — same canonical envelope as full bootstrap;
    * episodic TOOL_EXEC_ENDED recorder (priority 70) — shared factory
      :func:`make_episodic_recorder_handler`.

    The full bundle (journal, auto-learn, dreaming, notification, plugin
    discovery, agent_runtime_state SQLite writers) would re-run per spawn
    and double-write session-scoped stores the parent already owns.
    """
    from core.observability.hook_persistence import HookPersistenceSink

    hooks: HookSystem = HookSystem()
    event_store = _build_hook_event_store(log_dir)
    hooks.register_sink(
        HookPersistenceSink(
            event_store,
            session_key=session_key,
            run_id=run_id,
        ),
        name="hook_persistence",
    )
    episodic_name, episodic_fn = make_episodic_recorder_handler()
    hooks.register(
        HookEvent.TOOL_EXEC_ENDED,
        episodic_fn,
        name=episodic_name,
        priority=70,
    )
    return hooks


# ---------------------------------------------------------------------------
# Plugin registration helper (DRY: replaces 8 bare except blocks)
# ---------------------------------------------------------------------------

_plugin_status: dict[str, str] = {}


def _register_plugin(name: str, fn: Any, *args: Any, **kwargs: Any) -> bool:
    """Call *fn* and record plugin status. Returns True on success.

    Replaces repeated try/except Exception patterns with structured logging:
    - ImportError  -> warning (module not installed)
    - ValueError   -> warning (config invalid)
    - Other        -> error with traceback
    """
    try:
        fn(*args, **kwargs)
        _plugin_status[name] = "enabled"
        log.info("Plugin %s: enabled", name)
        return True
    except ImportError as exc:
        _plugin_status[name] = "unavailable"
        log.warning("Plugin %s: module not available (%s)", name, exc)
    except ValueError as exc:
        _plugin_status[name] = "config_error"
        log.warning("Plugin %s: config invalid (%s)", name, exc)
    except Exception as exc:
        _plugin_status[name] = "error"
        log.error("Plugin %s: failed (%s)", name, exc, exc_info=True)
    return False


def get_plugin_status() -> dict[str, str]:
    """Return plugin registration status dict for CLI reporting."""
    return _plugin_status.copy()


# ---------------------------------------------------------------------------
# Sub-builders
# ---------------------------------------------------------------------------


def build_hooks(
    *,
    session_key: str,
    run_id: str,
    log_dir: Path | str | None,
) -> tuple[HookSystem, HookEventStore, Any]:
    """Build HookSystem with bounded SQLite persistence and metrics."""
    from core.observability.hook_persistence import HookPersistenceSink

    hooks: HookSystem = HookSystem()

    event_store = _build_hook_event_store(log_dir)
    hooks.register_sink(
        HookPersistenceSink(
            event_store,
            session_key=session_key,
            run_id=run_id,
        ),
        name="hook_persistence",
    )

    # PR-COMM-3b (2026-05-24) — wire the SQLite ``agent_runtime_state``
    # writers landed by PR-COMM-3 into the now-augmented SESSION_ENDED
    # and SUBAGENT_COMPLETED payloads (this PR added the required
    # ``agent_kind`` / ``component`` / ``adapter_type`` /
    # ``claude_cli_session_id`` / ``status`` fields at the emit sites).
    # The ``LLM_CALL_ENDED`` cumulative-tokens handler is deferred to a
    # follow-up because AgenticLoop's main path does NOT yet emit
    # LLM_CALL_ENDED — that's a separate emit-augmentation PR
    # (router/calls/* fires it only for one-off LLM calls).
    def _reg_agent_runtime_state() -> None:
        from core.observability.agent_runtime_state import (
            accumulate_tokens_and_cost,
            record_agent_session_end,
            record_subagent_completed,
        )

        def _on_session_ended(_event: HookEvent, data: dict[str, Any]) -> None:
            agent_id = str(data.get("session_id") or data.get("agent_id") or "")
            if not agent_id:
                return
            # PR-SESSION-RESUME-PARAMS (2026-05-25) — capture the
            # per-task cwd alongside the claude-cli session_id so
            # the next reader can verify the saved session belongs
            # to the current cwd-pool (paperclip
            # ``execute.ts:592`` ``claudeSessionCwdMatchesExecutionTarget``).
            # Empty when no per-task isolation is in scope (REPL /
            # gateway) — the reader's gate skips on empty
            # stored_cwd, preserving legacy behaviour.
            from core.agent.task_isolation import get_task_isolated_cwd

            task_cwd = get_task_isolated_cwd() or ""
            resume_params: dict[str, Any] = {"cwd": task_cwd} if task_cwd else {}
            record_agent_session_end(
                agent_id=agent_id,
                agent_kind=str(data.get("agent_kind", "repl")),
                component=str(data.get("component", "agentic_loop")),
                adapter_type=str(data.get("adapter_type", "")),
                claude_cli_session_id=str(data.get("claude_cli_session_id", "")),
                session_resume_params=resume_params,
            )

        def _on_subagent_completed(_event: HookEvent, data: dict[str, Any]) -> None:
            agent_id = str(data.get("task_id") or data.get("agent_id") or "")
            if not agent_id:
                return
            record_subagent_completed(
                agent_id=agent_id,
                component=str(data.get("component", "agentic_loop")),
                last_run_id=str(data.get("run_id", "")),
                last_run_status=str(data.get("status", "completed")),
                last_error=str(data.get("error", "")),
            )

        # PR-COMM-3d (2026-05-24) — accumulate per-call token + cost
        # into the agent_runtime_state row. Payload shape comes from
        # AgenticLoop's main ``_call_llm`` emit site (this PR added
        # the augmentation); zero-token / empty-payload triggers are
        # silently skipped so router/calls/* one-off LLM calls (which
        # don't yet carry usage) don't create placeholder rows.
        def _on_llm_call_ended(_event: HookEvent, data: dict[str, Any]) -> None:
            agent_id = str(data.get("session_id") or data.get("agent_id") or "")
            if not agent_id:
                return
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                return
            try:
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                cached = int(usage.get("cached_input_tokens", 0) or 0)
                cost_usd = float(data.get("cost_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                return
            if input_tokens == 0 and output_tokens == 0 and cached == 0 and cost_usd == 0:
                return
            accumulate_tokens_and_cost(
                agent_id=agent_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached,
                cost_usd=cost_usd,
            )

        hooks.register(
            HookEvent.SESSION_ENDED,
            _on_session_ended,
            name="agent_runtime_session_end",
            priority=55,
        )
        hooks.register(
            HookEvent.SUBAGENT_COMPLETED,
            _on_subagent_completed,
            name="agent_runtime_subagent_completed",
            priority=55,
        )
        hooks.register(
            HookEvent.LLM_CALL_ENDED,
            _on_llm_call_ended,
            name="agent_runtime_llm_call_ended",
            priority=55,
        )

    _register_plugin("agent_runtime_state", _reg_agent_runtime_state)

    def _reg_cognitive_state_store() -> None:
        from core.memory.cognitive_state_store import CognitiveStateStore

        store = CognitiveStateStore()

        def _on_cognitive_event(event: HookEvent, data: dict[str, Any]) -> None:
            session_id = str(data.get("session_id") or "")
            snapshot = data.get("cognitive_state")
            if not session_id or not isinstance(snapshot, dict):
                return
            try:
                store.append_event(session_id, event.value, snapshot)
            except Exception:
                log.warning("cognitive state store append failed; skipping", exc_info=True)

        hooks.register_prefix(
            "COGNITIVE",
            _on_cognitive_event,
            name="cognitive_state_store_recorder",
            priority=65,
        )
        hooks.add_cleanup("cognitive_state_store", store.close)

    _register_plugin("cognitive_state_store", _reg_cognitive_state_store)

    # Context overflow action handler (CONTEXT_OVERFLOW_ACTION -> strategy recommendation)
    def _reg_context_action() -> None:
        from core.hooks.context_action import make_context_action_handler

        handler_name, handler_fn = make_context_action_handler()
        hooks.register(
            HookEvent.CONTEXT_OVERFLOW_ACTION,
            handler_fn,
            name=handler_name,
            priority=50,
        )

    _register_plugin("context_action_hook", _reg_context_action)

    # Notification hook plugin (events -> external messaging)
    def _reg_notification() -> None:
        from core.config import settings
        from core.hooks.plugins.notification_hook.hook import (
            register_notification_hooks,
        )

        register_notification_hooks(
            hooks,
            channel=settings.notification_channel,
            recipient=settings.notification_recipient,
        )

    _register_plugin("notification_hook", _reg_notification)

    # C2: Journal auto-record hooks (subagent lifecycle -> runs.jsonl)
    def _reg_journal() -> None:
        from core.memory.journal_hooks import make_journal_handlers
        from core.memory.project_journal import get_project_journal

        journal = get_project_journal()
        for handler_name, handler_fn in make_journal_handlers(journal):
            target_events = {
                "journal_subagent": [HookEvent.SUBAGENT_COMPLETED],
                # P1c — close defect #18 (STARTED + FAILED had no consumer).
                "journal_subagent_started": [HookEvent.SUBAGENT_STARTED],
                "journal_subagent_failed": [HookEvent.SUBAGENT_FAILED],
            }
            for evt in target_events.get(handler_name, []):
                hooks.register(evt, handler_fn, name=handler_name, priority=60)

    _register_plugin("journal_hook", _reg_journal)

    # C3: Auto-memory on turn complete (OpenClaw command:new pattern)
    def _reg_turn_memory() -> None:
        from core.tools import memory_tools

        def _on_turn_complete(event: HookEvent, data: dict[str, Any]) -> None:
            pm = memory_tools._project_memory_ctx.get()
            if pm is None:
                return
            text = data.get("text", "")
            user_input = data.get("user_input", "")
            tools = data.get("tool_calls", [])
            if not text or len(text) < 20:
                return  # too short to be useful
            # Build concise insight from turn
            tool_str = ", ".join(t for t in tools[:5] if t) or "none"
            insight = f"[turn] {user_input[:80]} → tools=[{tool_str}]"
            pm.add_insight(insight)

        hooks.register(
            HookEvent.TURN_COMPLETED,
            _on_turn_complete,
            name="turn_auto_memory",
            priority=85,
        )

    _register_plugin("turn_memory_hook", _reg_turn_memory)

    # C3b: Auto-learn user patterns on turn complete (Tier 0.5 cross-session memory)
    def _reg_auto_learn() -> None:
        from core.hooks.auto_learn import make_auto_learn_handler
        from core.tools.profile_tools import get_user_profile

        name, handler = make_auto_learn_handler(profile_provider=get_user_profile)
        hooks.register(
            HookEvent.TURN_COMPLETED,
            handler,
            name=name,
            priority=84,
        )

    _register_plugin("turn_auto_learn", _reg_auto_learn)

    # C3c: LLM-based learning extraction (Claude Code extractMemories pattern)
    def _reg_llm_extract() -> None:
        from core.hooks.llm_extract_learning import make_llm_extract_handler

        name, handler = make_llm_extract_handler()
        hooks.register(
            HookEvent.TURN_COMPLETED,
            handler,
            name=name,
            priority=82,  # lower priority than auto_learn (84)
        )

    _register_plugin("turn_llm_extract", _reg_llm_extract)

    # C3d: SQLite long-context dreaming (Hermes curator-style idle synthesis)
    def _reg_turn_dreaming() -> None:
        from core.memory.dreaming import make_dreaming_handler

        name, handler = make_dreaming_handler()
        hooks.register(
            HookEvent.TURN_COMPLETED,
            handler,
            name=name,
            priority=80,
        )

    _register_plugin("turn_dreaming", _reg_turn_dreaming)

    # C4: Session lifecycle hooks (OpenClaw agent:bootstrap pattern)
    def _reg_session_lifecycle() -> None:
        def _on_session_start(event: HookEvent, data: dict[str, Any]) -> None:
            log.info(
                "Session started: model=%s resumed=%s",
                data.get("model"),
                data.get("resumed"),
            )

        def _on_session_end(event: HookEvent, data: dict[str, Any]) -> None:
            log.info("Session ended: model=%s", data.get("model"))

        hooks.register(
            HookEvent.SESSION_STARTED,
            _on_session_start,
            name="session_start_logger",
            priority=90,
        )
        hooks.register(
            HookEvent.SESSION_ENDED,
            _on_session_end,
            name="session_end_logger",
            priority=90,
        )

    _register_plugin("session_lifecycle_hook", _reg_session_lifecycle)

    # C4b: Model switch logging (L1 Observe)
    hooks.register(
        HookEvent.MODEL_SWITCHED,
        lambda e, d: log.info("Model switched: %s → %s", d.get("from_model"), d.get("to_model")),
        name="model_switch_logger",
        priority=90,
    )

    # C5: LLM call lifecycle hooks (LLM_CALL_START/END -> slow call logging + journal cost)
    def _reg_llm_lifecycle() -> None:
        from core.llm.router import clear_router_hooks, set_router_hooks

        def _on_llm_end(event: HookEvent, data: dict[str, Any]) -> None:
            latency = data.get("latency_ms", 0.0)
            model = data.get("model", "?")
            error = data.get("error")

            # Slow call / error logging
            if error:
                log.warning(
                    "LLM call failed: model=%s error=%s latency=%dms",
                    model,
                    error,
                    int(latency),
                )
            elif latency > 10_000:  # > 10s
                log.warning(
                    "LLM call slow: model=%s latency=%dms",
                    model,
                    int(latency),
                )

        hooks.register(
            HookEvent.LLM_CALL_ENDED,
            _on_llm_end,
            name="llm_slow_logger",
            priority=55,
        )

        # Wire hooks into the LLM router module
        set_router_hooks(hooks)
        hooks.add_owner_cleanup("llm_router_hooks", clear_router_hooks)

    _register_plugin("llm_lifecycle_hook", _reg_llm_lifecycle)

    # PR-MUTATION-EMIT-WIRE (2026-05-27) — wire HookSystem into the
    # self-improving-loop emit sites. The runner's ``append_audit_log``
    # + train.py's ``BASELINE_PATH.write_text`` + the SoT-revert paths
    # call :func:`_fire_hook` with the payload schema documented on
    # the ``HookEvent.MUTATION_*`` / ``BASELINE_PROMOTED`` enum.
    def _reg_self_improving_loop_hooks() -> None:
        from core.self_improving.loop._hooks import (
            clear_self_improving_loop_hooks,
            set_self_improving_loop_hooks,
        )

        set_self_improving_loop_hooks(hooks)
        hooks.add_owner_cleanup(
            "self_improving_loop_hooks",
            clear_self_improving_loop_hooks,
        )

    _register_plugin("self_improving_loop_hooks", _reg_self_improving_loop_hooks)

    # PR-4 C-3 — episodic action-outcome ledger. TOOL_EXEC_ENDED carries
    # (tool_name, tool_input, has_error, result, duration_ms); we record
    # an Episode row + the COGNITIVE_UPDATE_MEMORY hook (PR-2) snapshot
    # so PR-5 can compute "tool X succeeded in situation Y at rate Z"
    # deltas. Hook is registered at priority 70 — observer, runs after
    # the TOOL_EXEC_ENDED interceptors but before audit loggers.
    #
    # Threading note: the EpisodicStore.append path is synchronous file
    # I/O. It fires inside the asyncio hook flow (the agent loop awaits
    # ``trigger_with_result_async``) so it briefly blocks the event
    # loop. Per-write cost is one ``write()`` + occasional rotation
    # (capped at max_rows * 1.25 ≈ 1250 rows, with an atomic temp-file
    # rewrite). Bounded enough that async-to-thread offload would add
    # more overhead than it saves; revisit if hot-path profiling shows
    # the recorder is a tail-latency contributor.
    def _reg_episodic_memory() -> None:
        handler_name, handler_fn = make_episodic_recorder_handler()
        hooks.register(
            HookEvent.TOOL_EXEC_ENDED,
            handler_fn,
            name=handler_name,
            priority=70,
        )

    _register_plugin("episodic_memory_hook", _reg_episodic_memory)

    # C8: Filesystem hook plugin auto-discovery (.geode/hooks/ only).
    # Built-ins are wired explicitly above; rediscovering their hook.yaml
    # manifests registered the same notification handler twice.
    def _reg_filesystem_plugins() -> None:
        from core.hooks.discovery import HookPluginLoader
        from core.paths import PROJECT_HOOKS_DIR

        loader = HookPluginLoader()
        loader.load_from_dirs([PROJECT_HOOKS_DIR])
        loader.register_all(hooks)
        hooks.add_owner_cleanup("filesystem_hook_plugins", loader.unregister_all)

    _register_plugin("filesystem_hook_plugins", _reg_filesystem_plugins)

    # C9: Audit loggers — handler-less events that had triggers but no dedicated handler.
    # Table-driven registration (automation.py pattern) for observability.
    _E = HookEvent
    _AL: list[tuple[HookEvent, str, str, list[str]]] = [
        (
            _E.CONTEXT_CRITICAL,
            "ctx_critical",
            "Context critical: %.0f%% (%s)",
            ["usage_pct", "model"],
        ),
        (_E.SUBAGENT_STARTED, "sa_started", "SubAgent started: %s (%s)", ["task_id", "task_type"]),
        (_E.LLM_CALL_STARTED, "llm_start", "LLM call: %s (%s)", ["model", "function"]),
        # PR-CL-A3 (2026-05-23) — per-turn verify telemetry: structured
        # row per turn outcome for the journal / downstream subscriber.
        (
            _E.TURN_VERIFY_FAILED,
            "turn_verify_fail",
            "Per-turn verify failed (%s): %s",
            ["mode", "rubric_misses"],
        ),
        (
            _E.TURN_VERIFY_PASSED,
            "turn_verify_pass",
            "Per-turn verify passed (%s, score=%s)",
            ["mode", "score"],
        ),
        (_E.TOOL_RECOVERY_ATTEMPTED, "recovery_try", "Tool recovery attempted: %s", ["tool_name"]),
        (
            _E.TOOL_RECOVERY_FAILED,
            "recovery_fail",
            "Tool recovery failed: %s — %s",
            ["tool_name", "error"],
        ),
        (_E.POST_ANALYSIS, "post_analysis", "Post-analysis: %s", ["trigger_type"]),
        (_E.SHUTDOWN_STARTED, "shutdown", "Shutdown: %s active sessions", ["active_sessions"]),
        (_E.CONFIG_RELOADED, "config_reload", "Config reloaded: %s", ["config_path"]),
        (_E.MCP_SERVER_FAILED, "mcp_fail", "MCP server failed: %s — %s", ["server_name", "error"]),
        # P0 production hooks
        (_E.USER_INPUT_RECEIVED, "user_input", "User input received: session=%s", ["session_id"]),
        (_E.TOOL_EXEC_STARTED, "tool_start", "Tool exec start: %s", ["tool_name"]),
        (
            _E.TOOL_EXEC_ENDED,
            "tool_end",
            "Tool exec end: %s (%.0fms)",
            ["tool_name", "duration_ms"],
        ),
        (
            _E.TOOL_EXEC_FAILED,
            "tool_failed",
            "Tool exec FAILED: %s — %s (%s)",
            ["tool_name", "error", "error_type"],
        ),
        (
            _E.TOOL_RESULT_TRANSFORM,
            "tool_transform",
            "Tool result transform: %s",
            ["tool_name"],
        ),
        (
            _E.COST_WARNING,
            "cost_warn",
            "Cost warning: $%.4f / $%.2f",
            ["total_cost_usd", "limit_usd"],
        ),
        (
            _E.COST_LIMIT_EXCEEDED,
            "cost_exceeded",
            "Cost EXCEEDED: $%.4f / $%.2f",
            ["total_cost_usd", "limit_usd"],
        ),
        (_E.EXECUTION_CANCELLED, "exec_cancel", "Execution cancelled: %s", ["session_id"]),
        # Asymmetry fixes — events that had triggers but no audit logger
        (_E.LLM_CALL_FAILED, "llm_failed", "LLM call FAILED: %s — %s", ["model", "error_type"]),
        (_E.LLM_CALL_RETRIED, "llm_retry", "LLM call retry: %s (attempt %s)", ["model", "attempt"]),
        (
            _E.TOOL_RECOVERY_SUCCEEDED,
            "recovery_ok",
            "Tool recovery OK: %s",
            ["tool_name"],
        ),
        (_E.MCP_SERVER_CONNECTED, "mcp_ok", "MCP server connected: %s", ["server_name"]),
        (_E.TOOL_RESULT_OFFLOADED, "tool_offload", "Tool result offloaded: %s", ["tool_name"]),
        (_E.TOOL_APPROVAL_REQUESTED, "approval_req", "Tool approval requested: %s", ["tool_name"]),
        (_E.MEMORY_SAVED, "memory_saved", "Memory saved: %s", ["key"]),
        (
            _E.REASONING_METRICS,
            "reasoning_metrics",
            "Reasoning: %s rounds, %s tools",
            ["total_rounds", "tool_calls_total"],
        ),
    ]

    def _reg_audit_loggers() -> None:
        for event, name, tmpl, keys in _AL:

            def _make(t: str, ks: list[str]) -> Any:
                def _handler(_e: HookEvent, d: dict[str, Any]) -> None:
                    vals = tuple(d.get(k, "") for k in ks)
                    log.info(t, *vals)

                return _handler

            hooks.register(event, _make(tmpl, keys), name=name, priority=90)

    _register_plugin("audit_loggers", _reg_audit_loggers)

    # C10: Structured metrics — p50/p95 latency, success rates
    from core.orchestration.metrics import LatencyMetrics, make_metrics_hook_handler

    session_metrics = LatencyMetrics()

    def _reg_metrics() -> None:
        for event_name, handler_name, handler_fn in make_metrics_hook_handler(session_metrics):
            hooks.register(HookEvent(event_name), handler_fn, name=handler_name, priority=45)

    _register_plugin("session_metrics", _reg_metrics)

    return hooks, event_store, session_metrics


def build_memory(
    *,
    session_store: SessionStorePort,
    hooks: Any = None,
    event_store: HookEventStore | None = None,
) -> tuple[ProjectMemory, MonoLakeOrganizationMemory, ContextAssembler, FileBasedUserProfile]:
    """Build L2 memory components: project, org, context assembler, user profile."""
    from core.config import settings
    from core.memory.context import ContextAssembler
    from core.memory.organization import MonoLakeOrganizationMemory
    from core.memory.project import ProjectMemory
    from core.memory.user_profile import FileBasedUserProfile
    from core.paths import ensure_directories

    ensure_directories()

    project_memory = ProjectMemory()

    org_dir = settings.organization_fixture_dir
    fixture_dir = Path(org_dir) if org_dir else None
    organization_memory = MonoLakeOrganizationMemory(fixture_dir=fixture_dir)

    # Tier 0.5: User Profile
    from core.paths import PROJECT_USER_PROFILE_DIR

    global_profile_dir = Path(settings.user_profile_dir) if settings.user_profile_dir else None
    project_profile_dir = PROJECT_USER_PROFILE_DIR
    user_profile = FileBasedUserProfile(
        global_dir=global_profile_dir,
        project_dir=project_profile_dir,
    )

    # C2: Project Journal — append-only execution history
    from core.memory.project_journal import ProjectJournal

    project_journal = ProjectJournal()
    project_journal.ensure_structure()

    # V0: Vault — purpose-routed artifact storage
    from core.memory.vault import Vault

    vault = Vault()
    vault.ensure_structure()

    from core.memory.session_manager import SessionManager

    context_artifact_store = SessionManager()

    context_assembler = ContextAssembler(
        organization_memory=organization_memory,
        project_memory=project_memory,
        session_store=session_store,
        user_profile=user_profile,
        event_store=event_store,
        project_journal=project_journal,
        vault=vault,
        project_root=Path("."),
        session_manager=context_artifact_store,
    )
    if isinstance(hooks, HookSystem):
        hooks.add_cleanup("context_artifact_store", context_artifact_store.close)

    # Wire memory into memory tools via contextvars (P1 memory autonomy).
    # PR-AUDIT-AB (2026-06-10) — set_default_session_store was the one
    # sibling setter never called here: every memory_save with
    # persistent=False wrote into a fresh throwaway InMemorySessionStore
    # and still returned saved=True (fake success). The session_store
    # built at bootstrap is the same instance ContextAssembler reads.
    from core.tools.memory_tools import (
        clear_memory_hooks,
        set_default_session_store,
        set_memory_hooks,
        set_org_memory,
        set_project_memory,
    )

    set_default_session_store(session_store)
    set_project_memory(project_memory)
    set_org_memory(organization_memory)
    set_memory_hooks(hooks)
    if isinstance(hooks, HookSystem):
        hooks.add_owner_cleanup("memory_tool_hooks", clear_memory_hooks)

    # Shared tool-handler HookSystem injection (PR-PRE10-ROUND2) — lets
    # cross-layer tool handlers (e.g. HITL feedback in core.cli) persist events
    # without bootstrap importing the CLI layer (Server-never-CLI contract).
    from core.hooks.tool_hooks import clear_tool_hooks, set_tool_hooks

    set_tool_hooks(hooks)
    if isinstance(hooks, HookSystem):
        hooks.add_owner_cleanup("shared_tool_hooks", clear_tool_hooks)

    # Wire user profile into profile tools via contextvars
    from core.tools.profile_tools import set_user_profile

    set_user_profile(user_profile)

    return project_memory, organization_memory, context_assembler, user_profile


def build_session_store(*, session_ttl: float) -> SessionStorePort:
    """Build the ephemeral in-memory session store (optionally file-backed)."""
    from core.config import settings
    from core.memory.session import InMemorySessionStore

    session_storage_dir: Path | None = None
    if settings.session_storage_dir:
        session_storage_dir = Path(settings.session_storage_dir)
    return InMemorySessionStore(ttl=session_ttl, storage_dir=session_storage_dir)


def build_config_watcher(*, hooks: HookSystem | None = None) -> ConfigWatcher:
    """Build ConfigWatcher and register .env hot-reload handler if .env exists."""
    from core.orchestration.hot_reload import ConfigWatcher

    config_watcher = ConfigWatcher(debounce_ms=CONFIG_WATCHER_DEBOUNCE_MS)
    env_path = Path(".env")
    if not env_path.exists():
        return config_watcher

    def _on_config_change(path: Path, mtime: float) -> None:
        log.info("Config file changed: %s — reloading settings", path)
        from core.config import Settings, settings

        new_settings = Settings()

        # Validate constraints before applying
        if new_settings.session_ttl_hours <= 0:
            log.warning("Invalid session_ttl_hours; skipping reload")
            return
        if new_settings.trigger_scheduler_interval_s <= 0:
            log.warning("Invalid trigger_scheduler_interval_s; skipping reload")
            return

        # Core settings
        # NOTE: settings.model is intentionally NOT reloaded here.
        # Model switching is user-facing state managed by /model command
        # and switch_model tool. Hot-reloading it from .env would revert
        # user's in-session model choice (os.environ stale vs .env fresh).
        settings.verbose = new_settings.verbose
        # Trigger Manager
        settings.trigger_scheduler_interval_s = new_settings.trigger_scheduler_interval_s
        # L2 Memory
        settings.session_ttl_hours = new_settings.session_ttl_hours
        log.info("Settings hot-reload complete (3 fields updated)")
        if hooks is not None:
            try:
                hooks.trigger(
                    HookEvent.CONFIG_RELOADED,
                    {"config_path": str(path), "fields_updated": 3},
                )
            except Exception:
                log.debug("CONFIG_RELOADED hook failed", exc_info=True)

    config_watcher.watch(env_path, _on_config_change, name="dotenv")
    config_watcher.start()
    return config_watcher


def build_task_graph() -> TaskGraph:
    """Build an empty TaskGraph for L4 task tracking."""
    from core.orchestration.task_system import TaskGraph

    return TaskGraph()


# ---------------------------------------------------------------------------
# Unified bootstrap: MCP, Skills, Readiness (moved from cli/bootstrap.py)
# ---------------------------------------------------------------------------


def build_mcp_manager() -> Any:
    """Load MCP server config (lazy — no subprocess connections yet)."""
    from core.mcp.manager import get_mcp_manager

    mgr = get_mcp_manager()
    mgr.load_config()
    return mgr


def build_skill_registry() -> Any:
    """Load all skill definitions from 4-tier priority directories."""
    from core.skills.skills import SkillLoader, SkillRegistry

    registry = SkillRegistry()
    try:
        SkillLoader().load_all(registry=registry)
    except Exception:
        log.debug("Skill loading skipped", exc_info=True)
    return registry


def build_readiness() -> Any:
    """Check API key availability for all configured providers."""
    from core.wiring.startup import check_readiness

    return check_readiness()


def build_tool_offload(
    *,
    session_id: str,
    hooks: HookSystem | None = None,
) -> Any:
    """Build P0 tool result offload store and wire cleanup on SESSION_END."""
    from core.config import settings
    from core.orchestration.tool_offload import ToolResultOffloadStore, set_offload_store

    if settings.tool_offload_threshold <= 0:
        return None

    store = ToolResultOffloadStore(
        session_id=session_id,
        threshold=settings.tool_offload_threshold,
        ttl_hours=settings.tool_offload_ttl_hours,
    )
    set_offload_store(store)

    if hooks:

        def _cleanup_offload(_event: Any, _data: Any) -> None:
            store.cleanup_session()

        hooks.register(
            HookEvent.SESSION_ENDED,
            _cleanup_offload,
            name="tool_offload_cleanup",
            priority=95,
        )
    log.info(
        "Tool offload enabled: threshold=%d tokens, ttl=%.1fh",
        store.threshold,
        settings.tool_offload_ttl_hours,
    )
    return store

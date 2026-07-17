"""Typer ``geode serve`` command implementation.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split). Hosts
the headless gateway-mode entry point plus the small
``_build_runtime_for_serve`` helper. The Typer ``app`` registers this
function from the package ``__init__``; no decorator here to keep the
import edge clean.
"""

from __future__ import annotations

import logging
from typing import Any

import typer

from core.cli.session_state import _scheduler_service_ctx, _set_readiness
from core.ui.console import console
from core.wiring.startup import check_readiness

log = logging.getLogger(__name__)


def _gateway_checkpoint_session_id(session_key: str) -> str:
    """Stable machine-instance id for a gateway thread.

    One messaging thread (channel/thread/sender ``session_key``) maps to
    ONE session-checkpoint instance across turns, so guard counters and
    cognitive state persist per thread and per-turn checkpoints stop
    accumulating (docs/architecture/session-state-machine.md).
    """
    import hashlib

    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:12]
    return f"s-gw-{digest}"


def _gateway_checkpoint_is_resumable(state: Any) -> bool:
    """Only ACTIVE/PAUSED gateway machines may accept implicit continuation."""
    return str(getattr(state, "status", "")) in {"active", "paused"}


def _gateway_resume_messages(
    stored_session: dict[str, Any] | None,
    checkpoint_state: Any,
) -> list[dict[str, Any]]:
    """Load conversation history from L2, then the durable CLI checkpoint."""
    if stored_session and isinstance(stored_session.get("messages"), list):
        return list(stored_session["messages"])
    messages = getattr(checkpoint_state, "messages", None)
    if _gateway_checkpoint_is_resumable(checkpoint_state) and isinstance(messages, list):
        return list(messages)
    return []


def _gateway_session_can_resume(session_key: str, session_store: Any, checkpoint: Any) -> bool:
    """Check durable machine state before falling back to the L2 session store."""
    state = checkpoint.load(_gateway_checkpoint_session_id(session_key))
    if state is not None:
        return _gateway_checkpoint_is_resumable(state)
    return bool(session_store.exists(session_key))


def _gateway_session_is_terminal(session_key: str, checkpoint: Any) -> bool:
    """A durable checkpoint exists and its machine ended (not active/paused)."""
    state = checkpoint.load(_gateway_checkpoint_session_id(session_key))
    return state is not None and not _gateway_checkpoint_is_resumable(state)


async def _restore_gateway_loop(loop: Any, state: Any) -> None:
    """Apply the same machine and model restore contract as CLI resume."""
    loop.restore_from_checkpoint(state)
    if state.model and state.model != loop.model:
        await loop.update_model_async(state.model)


def serve(
    poll_interval: float = typer.Option(
        3.0, "--poll", "-p", help="Gateway poll interval (seconds)"
    ),
) -> None:
    """Run GEODE Gateway in headless mode (no REPL, Slack/Discord/Telegram only)."""
    import asyncio
    import signal
    import time as _time

    # PR-DISPATCH-OBS-EXT (2026-05-28) / S-6 (2026-06-11) — serve.log file
    # handler via the unified entry-point switchboard. The lifecycle
    # status command depends on SERVE_LOG_PATH existing (``commands/lifecycle.py``);
    # configure_logging("serve") preserves that path + 10MB x5 rotation.
    from core.observability.logging_config import configure_logging

    configure_logging("serve")

    # ContextVars only (memory, profile, env) — no resource creation
    from core.cli.bootstrap import setup_contextvars

    setup_contextvars(load_env=True)

    from core.config import settings

    if not settings.gateway_enabled:
        console.print("  [warning]Gateway is disabled.[/warning]")
        console.print("  [dim]Set [gateway] enabled = true in ~/.geode/config.toml[/dim]")
        raise typer.Exit(1)

    console.print()
    console.print("  [header]GEODE Gateway — headless mode[/header]")
    console.print(f"  [dim]Poll interval: {poll_interval}s[/dim]")
    console.print("  [dim]Press Ctrl+C to stop[/dim]")
    console.print()

    # Readiness check — needed by /analyze, /run, /status via IPC
    readiness = check_readiness()
    _set_readiness(readiness)

    # Build runtime (wires env, notifications, gateway + MCP startup)
    # MCP startup is now inside _build_gateway() via mcp.startup()
    runtime = _build_runtime_for_serve()
    if runtime is None:
        console.print("  [warning]Runtime initialization failed.[/warning]")
        raise typer.Exit(1)

    # Wire AgenticLoop as gateway processor
    from core.agent.conversation import ConversationContext
    from core.messaging.binding import get_gateway

    gateway = get_gateway()
    if gateway is None:
        console.print("  [warning]No gateway available after runtime init.[/warning]")
        raise typer.Exit(1)

    # Thread-aware adapters may receive a continuation without another
    # explicit mention after a daemon restart. Reuse the same durable
    # checkpoint substrate as CLI resume; the L2 store is the fast path while
    # the checkpoint preserves history and machine state across restarts.
    from core.memory.session_checkpoint import SessionCheckpoint

    _gw_checkpoint = SessionCheckpoint()
    gateway.set_session_exists_checker(
        lambda session_key: _gateway_session_can_resume(
            session_key,
            runtime.session_store,
            _gw_checkpoint,
        )
    )
    gateway.set_session_terminal_checker(
        lambda session_key: _gateway_session_is_terminal(session_key, _gw_checkpoint)
    )

    _GATEWAY_SUFFIX = (
        "## Gateway mode\n"
        "Surface: external messaging channel (Slack/Discord/Telegram).\n"
        "- Do NOT echo or quote the user's message. Respond directly.\n"
        "- Use tools aggressively to answer thoroughly. Do not give up early.\n"
        "- For complex questions, break them down and use multiple tool calls.\n"
        "- You have access to prior messages in this thread as conversation history.\n"
        "- Format responses for messaging: use short paragraphs, avoid excessive markdown."
    )

    # Build SharedServices for serve mode (same factory as REPL)
    from core.server.supervised.services import SessionMode, build_shared_services

    # PR-CL-BUDGET — turn hard-cap removed; ``0`` means unlimited rounds. The
    # session-wide 2-hour wall-clock budget (``core.agent.budget``) is the new
    # global safety net. Fallback ``0`` for legacy ``gateway`` objects without
    # the attribute matches the new default in :class:`GatewayManager`.
    _gw_max_turns = gateway.gateway_max_turns if hasattr(gateway, "gateway_max_turns") else 0
    _gw_time_budget = (
        gateway.gateway_time_budget_s if hasattr(gateway, "gateway_time_budget_s") else 120.0
    )
    _gw_services = build_shared_services(
        mcp_manager=runtime.mcp_manager,
        skill_registry=runtime.skill_registry,
        hook_system=runtime.hooks,
        lane_queue=runtime.lane_queue,
    )

    # Wire module-level hooks so _fire_hook() works in serve mode
    import core.cli as _cli_pkg

    _cli_pkg._hooks_ctx = _gw_services.hook_system

    # --- Scheduler daemon (same SchedulerService as REPL, drain in main loop) ---
    import queue as _queue_mod

    _sched_queue: _queue_mod.Queue[tuple[str, str, bool, str]] = _queue_mod.Queue()
    _sched_svc = None
    try:
        from core.scheduler import create_scheduler

        _sched_svc = create_scheduler(
            on_job_fired=lambda jid, act, iso, aid: _sched_queue.put((jid, act, iso, aid)),
            hooks=_gw_services.hook_system,
            enable_jitter=True,
        )
        _sched_svc.load()
        _recovered = _sched_svc.recover_missed_tasks()
        if _recovered:
            console.print(f"  [info]Recovered {len(_recovered)} missed scheduled jobs[/info]")
        _sched_svc.start()
        _scheduler_service_ctx.set(_sched_svc)
        _n_jobs = _sched_svc.job_count
        console.print(f"  [success]Scheduler started ({_n_jobs} jobs loaded)[/success]")
    except Exception:
        log.warning("SchedulerService init failed in serve", exc_info=True)
        console.print("  [warning]Scheduler init failed — running without scheduler[/warning]")

    _serve_session_lane = _gw_services.lane_queue.session_lane
    _serve_global_lane = _gw_services.lane_queue.get_lane("global")

    async def _arun_ask_continuation(state: Any, answer: str) -> str:
        """Resume a checkpointed session with the operator's ask answer."""
        _ask_ctx = ConversationContext(max_turns=_gw_max_turns)
        _ask_ctx.messages = list(state.messages)
        _ask_executor, _ask_loop = _gw_services.create_session(
            SessionMode.DAEMON,
            conversation=_ask_ctx,
            system_suffix=_GATEWAY_SUFFIX,
            time_budget_override=_gw_time_budget,
            propagate_context=True,
        )
        # Checkpoint continuity — the single shared resume surgery (same
        # path as the IPC resume handler); arun() re-binds the ContextVars
        # from the restored objects.
        await _restore_gateway_loop(_ask_loop, state)
        _res = await _ask_loop.arun(answer)
        # Close the one-shot lifecycle (finalize re-wrote status "active"):
        # a fresh clarification re-parks the checkpoint behind a NEW ask;
        # any other terminal completes it.
        try:
            if _res is not None and _res.termination_reason == "user_clarification_needed":
                from core.memory.pending_ask import apublish_clarification_ask

                await apublish_clarification_ask(
                    _res.text,
                    session_id=state.session_id,
                    source=f"ask-continuation:{state.session_id}",
                )
                _ask_loop.mark_session_paused()
            else:
                _ask_loop.mark_session_completed()
        except Exception:
            log.warning("Ask continuation lifecycle close failed", exc_info=True)
        return _res.text if _res else ""

    async def _gateway_processor(content: str, metadata: dict[str, Any]) -> str:
        """Process a gateway message with multi-turn context.

        Uses SharedServices.create_session(DAEMON) — same shared resources
        as REPL, only mode-specific behavior differs.
        """
        session_key = metadata.get("session_key", "")

        # Pending-ask replies ("ask <id> <answer>") short-circuit normal
        # routing: the answer resumes the checkpointed session that raised
        # the question. Trust inherits from binding exact-match — only
        # bound channels reach this processor.
        from core.memory.pending_ask import ahandle_ask_reply

        _ask_response = await ahandle_ask_reply(
            content,
            answered_by=(f"{metadata.get('channel', '')}:{metadata.get('sender_id', '')}"),
            run_continuation=_arun_ask_continuation,
        )
        if _ask_response is not None:
            return _ask_response

        # --- Load prior conversation from L2 or the durable checkpoint ---
        ctx = ConversationContext(max_turns=_gw_max_turns)
        _gw_session_id = _gateway_checkpoint_session_id(session_key) if session_key else ""
        _prior_state = _gw_checkpoint.load(_gw_session_id) if _gw_session_id else None
        prior = runtime.session_store.get(session_key) if session_key else None
        ctx.messages = _gateway_resume_messages(prior, _prior_state)
        if ctx.messages:
            log.info(
                "Gateway multi-turn: loaded %d messages for %s",
                len(ctx.messages),
                session_key,
            )

        # Single factory — DAEMON mode (hitl=0, quiet, time-based).
        # A messaging thread is ONE machine instance: the stable derived
        # session id makes every turn share one checkpoint chain instead of
        # leaving an immortal per-turn ``s-<uuid>`` checkpoint behind
        # (docs/architecture/session-state-machine.md).
        _executor, loop = _gw_services.create_session(
            SessionMode.DAEMON,
            conversation=ctx,
            system_suffix=_GATEWAY_SUFFIX,
            time_budget_override=_gw_time_budget,
            propagate_context=True,
            session_id=_gw_session_id,
        )
        if _gw_session_id:
            # Machine continuity across turns — cognitive state + guard
            # counters come from the thread's checkpoint; the conversation
            # itself stays session_store-owned (restored above). A TERMINAL
            # prior state (context exhaustion completed the instance) means
            # the thread starts a FRESH machine under the same id: reopen
            # the edge explicitly and skip the restore so the old goal and
            # guard counters do not leak into the new topic.
            from core.memory.session_checkpoint import SessionStatus

            if _prior_state is not None:
                if _prior_state.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
                    await _restore_gateway_loop(loop, _prior_state)
                else:
                    _gw_checkpoint.reopen(_gw_session_id)
        try:
            result = await loop.arun(content)

            # --- Persist conversation for next turn ---
            if session_key:
                if result and result.termination_reason == "context_exhausted":
                    # Context exhausted → clear session so next message starts fresh
                    runtime.session_store.delete(session_key)
                    # Terminal edge the gateway DOES own: the thread's
                    # machine instance is finished.
                    loop.mark_session_completed()
                    log.info("Session cleared after context exhaustion: %s", session_key)
                else:
                    runtime.session_store.set(
                        session_key,
                        {
                            "messages": ctx.messages,
                            "thread_id": metadata.get("thread_id", ""),
                            "channel": metadata.get("channel", ""),
                        },
                    )

            return result.text if result else ""
        except Exception as exc:
            log.warning("Gateway processor error: %s", exc, exc_info=True)
            return f"Error: {exc}"

    gateway.set_async_processor(_gateway_processor)

    # PR-GATEWAY-BRIDGE-FRONTIER (2026-06-12) — set by ``_serve_loop`` on
    # startup so thread-side bridges can marshal coroutines into the
    # long-lived main loop instead of spawning a throwaway loop per call.
    _main_loop: asyncio.AbstractEventLoop | None = None

    def _gateway_processor_sync(content: str, metadata: dict[str, Any]) -> str:
        """Thread → main-loop bridge for the stdlib HTTP webhook server.

        PR-GATEWAY-BRIDGE-FRONTIER (2026-06-12) — frontier convergence
        (hermes ``gateway/run.py`` cron ticker, openclaw single-loop lane
        dispatch): a worker thread submits the coroutine to the daemon's
        ONE long-lived serve loop via ``run_coroutine_threadsafe`` and
        blocks on the future. The previous ``run_process_coroutine`` shape
        built a throwaway ``asyncio.Runner`` loop per webhook request —
        the same loop-per-call residue PR-LOOP-POLLUTION-FIX removed from
        the tool path (clients are loop-affine now, so it was safe but
        still one disposable loop per request).
        """
        loop = _main_loop
        if loop is None or loop.is_closed():
            log.warning("Webhook received before the serve loop is up — rejecting")
            return "Error: serve loop not running yet; retry shortly"
        future = asyncio.run_coroutine_threadsafe(_gateway_processor(content, metadata), loop)
        try:
            return future.result(timeout=float(_gw_time_budget) + 30.0)
        except TimeoutError:
            future.cancel()
            log.error("Webhook gateway turn exceeded %.0fs — cancelled", _gw_time_budget + 30.0)
            return "Error: gateway turn timed out"

    # L4 Gateway Hooks: optional webhook endpoint
    _webhook_server = None
    if settings.webhook_enabled:
        try:
            from core.server.supervised.webhook_handler import start_webhook_server

            _webhook_server = start_webhook_server(
                _gateway_processor_sync,
                port=settings.webhook_port,
            )
            console.print(
                f"  [success]Webhook endpoint started on port {settings.webhook_port}[/success]"
            )
        except Exception as _wh_exc:
            log.warning("Webhook server failed to start: %s", _wh_exc)

    # CLI Channel — Unix socket for thin CLI client IPC.
    # Start this before external gateway pollers: some gateway adapters run a
    # blocking poll loop from start(), but thin CLI clients still need a socket.
    _cli_poller = None
    try:
        from core.server.ipc_server.poller import CLIPoller

        _cli_poller = CLIPoller(_gw_services, scheduler_service=_sched_svc)
        _cli_poller.start()
        console.print(f"  [success]CLI channel: {_cli_poller.socket_path}[/success]")
    except Exception:
        log.warning("CLI channel init failed", exc_info=True)

    # Start gateway pollers
    gateway.start()
    console.print("  [success]Gateway started. Listening...[/success]")

    console.print()

    # Block until Ctrl+C
    stop = False

    def _on_signal(sig: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    async def _serve_loop() -> None:
        """Async serve loop driving scheduler drain + idle cleanup.

        PR-Async-Phase-C step 4a (2026-05-22) — was a sync ``while not
        stop: _drain(...); _time.sleep(1.0)``. The drain is now async-
        native (fire-and-forget jobs are scheduled via
        ``asyncio.create_task`` on this loop), so the entire tick body
        has to run inside ``asyncio.run`` for the dispatched tasks to
        survive past the drain call.
        """
        from core.cli.interactive_loop import _drain_scheduler_queue

        # Expose this loop to thread-side bridges (webhook handler).
        nonlocal _main_loop
        _main_loop = asyncio.get_running_loop()

        while not stop:
            await _drain_scheduler_queue(
                action_queue=_sched_queue,
                services=_gw_services,
                session_lane=_serve_session_lane,
                global_lane=_serve_global_lane,
                force_isolated=True,
                on_complete=lambda result, *, job_id: log.info("scheduled:%s completed", job_id),
                on_dispatch=lambda jid: log.info("scheduled:%s dispatched", jid),
                on_skip=lambda jid: log.warning("scheduled:%s skipped (slots full)", jid),
            )
            if _serve_session_lane:
                _serve_session_lane.cleanup_idle()
            await asyncio.sleep(1.0)

    try:
        asyncio.run(_serve_loop())
    finally:
        # --- Phase 0: notify shutdown hook ---
        try:
            if _gw_services and _gw_services.hook_system:
                from core.hooks import HookEvent

                _active_count = _serve_session_lane.active_count if _serve_session_lane else 0
                _gw_services.hook_system.trigger(
                    HookEvent.SHUTDOWN_STARTED,
                    {"active_sessions": _active_count},
                )
        except Exception:
            log.debug("SHUTDOWN_STARTED hook failed", exc_info=True)

        # --- Phase 1: stop accepting new connections ---
        # Close the server socket so no new CLI clients connect during drain.
        # Active client handler threads continue running.
        if _cli_poller is not None:
            _cli_poller.stop_accepting()
        # Stop channel ingress (Slack Socket Mode / pollers) before draining —
        # otherwise new inbound events keep starting sessions during drain.
        gateway.stop()

        # --- Phase 2: drain active sessions ---
        _drain_timeout_s = 30  # max seconds to wait for active sessions
        _drain_poll_s = 0.5
        _active = 0
        if _serve_session_lane:
            _active = _serve_session_lane.active_count
        if _active > 0:
            console.print()
            console.print(
                f"  [dim]Draining {_active} active session(s) "
                f"(timeout {_drain_timeout_s}s)...[/dim]"
            )
            _deadline = _time.monotonic() + _drain_timeout_s
            while _time.monotonic() < _deadline:
                _active = _serve_session_lane.active_count if _serve_session_lane else 0
                if _active == 0:
                    break
                _time.sleep(_drain_poll_s)
            _remaining = _serve_session_lane.active_count if _serve_session_lane else 0
            if _remaining > 0:
                console.print(
                    f"  [warning]Drain timeout: {_remaining} session(s) still active "
                    f"— forcing shutdown[/warning]"
                )
                log.warning(
                    "Drain timeout: %d sessions still active after %ds",
                    _remaining,
                    _drain_timeout_s,
                )
            else:
                console.print("  [dim]All sessions drained.[/dim]")
                log.info("Graceful drain completed")

        # --- Phase 3: component shutdown ---
        # Scheduler graceful shutdown (save state before stopping)
        if _sched_svc is not None:
            _sched_svc.save()
            _sched_svc.stop()
            log.info("Scheduler stopped, state saved")
        if _cli_poller is not None:
            _cli_poller.stop()
        if _webhook_server is not None:
            _webhook_server.shutdown()
        if runtime is not None:
            try:
                runtime.shutdown()
            except Exception:
                log.debug("Runtime shutdown error", exc_info=True)
        console.print()
        console.print("  [dim]Gateway stopped.[/dim]")


def _build_runtime_for_serve() -> Any:
    """Minimal runtime init for serve mode without REPL."""
    try:
        from core.runtime import GeodeRuntime

        runtime = GeodeRuntime.create("gateway")
        return runtime
    except Exception as exc:
        log.error("Failed to build runtime for serve: %s", exc, exc_info=True)
        return None

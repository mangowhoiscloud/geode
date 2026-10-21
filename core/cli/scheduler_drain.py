"""Scheduler queue drain — extracted from cli/__init__.py for SRP.

Drains pending scheduled jobs from the action queue, shared by REPL and serve modes.

PR-Async-Phase-C step 4a (2026-05-22) — fully async-native drain. The old
sync helper that dispatched isolated jobs through ``IsolatedRunner.run_async``
is replaced by ``asyncio.create_task`` fire-and-forget on the calling loop.
Active tasks are tracked in a module-level set so the GC cannot reap them
mid-flight (see ``asyncio.create_task`` docs — "Save a reference to the result
of this function").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.agent.conversation import ConversationContext
from core.agent.loop.models import is_successful_task_termination
from core.agent.session_mode import SessionMode

log = logging.getLogger(__name__)


# Module-level strong refs for fire-and-forget tasks. Required because
# ``asyncio.create_task`` only holds a weak reference; without this the
# task could be GC'd before completion and the event loop would log
# "Task was destroyed but it is pending!".
_INFLIGHT_SCHEDULED_TASKS: set[asyncio.Task[str]] = set()

_PAUSED_TERMINATIONS = frozenset({"user_clarification_needed", "external_verification_required"})


class ScheduledRunUnresolvedError(RuntimeError):
    """A scheduled run ended, but its required terminal state was not persisted.

    The scheduler claim is left in place: no second run can overlap and stuck
    detection reports it. The isolated task's result is then ``"unresolved"``.
    """


def _report_outcome(on_settle: Any, job_id: str, run_id: str, status: str, error: str = "") -> bool:
    """Persist one run outcome through the scheduler owner.

    True: accepted for this run (or no fenced owner to report to). False: stale
    — a newer run or a deleted job — so this is not this run's settlement.
    A persistence failure raises unchanged and leaves the run claimed.
    """
    if on_settle is None or not run_id:
        return True
    return on_settle(job_id, run_id, status, error) is not False


def _report_or_log(on_settle: Any, job_id: str, run_id: str, status: str, error: str) -> None:
    """Report a disposition decided before any turn ran (skip, dispatch failure).

    Nothing is announced on this path, so a persistence failure is logged and
    the run stays claimed instead of aborting the rest of the queue.
    """
    try:
        _report_outcome(on_settle, job_id, run_id, status, error)
    except Exception:
        log.error(
            "Scheduler job %s outcome %r was not persisted; run %s stays claimed",
            job_id,
            status,
            run_id[:8],
            exc_info=True,
        )


def _log_task_failure(task: asyncio.Task[str]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("Scheduled task %s ended unresolved: %s", task.get_name(), exc, exc_info=exc)


async def _run_isolated(
    loop: Any,
    prompt: str,
    *,
    job_id: str,
    run_id: str,
    services: Any,
    on_settle: Any,
    on_complete: Any,
) -> str:
    """Run one isolated scheduled turn and settle it from its real outcome.

    The session terminal state (paused/completed/error) is persisted first;
    only then is the scheduler outcome reported, and only an accepted
    settlement is announced through ``on_complete``. If the required session
    write fails the run is not settled: :class:`ScheduledRunUnresolvedError`
    (chained to the primary failure) or the store error propagates. Returns
    ``"settled"`` or ``"stale"``.
    """
    try:
        r = await asyncio.wait_for(loop.arun(prompt), timeout=300.0)
    except asyncio.CancelledError:
        # The awaited turn has unwound in this task; it is cancelled, not done.
        log.warning("Scheduler job %s cancelled", job_id)
        try:
            await loop.amark_session_error()
            _report_outcome(
                on_settle, job_id, run_id, "cancelled", "scheduled run cancelled before completion"
            )
        except Exception:
            log.error(
                "Scheduler job %s cancelled but its terminal state was not persisted; "
                "run %s stays claimed",
                job_id,
                run_id[:8],
                exc_info=True,
            )
        raise
    except Exception as exc:
        timed_out = isinstance(exc, TimeoutError)
        log.warning(
            "Scheduler job %s %s",
            job_id,
            "timed out after 300s" if timed_out else "failed",
            exc_info=not timed_out,
        )
        try:
            await loop.amark_session_error()
        except Exception as write_exc:
            raise ScheduledRunUnresolvedError(
                f"scheduled run {run_id[:8]} of {job_id} failed and its session error "
                f"state was not persisted ({write_exc}); the run stays claimed"
            ) from exc
        if not _report_outcome(
            on_settle, job_id, run_id, "error", "timeout" if timed_out else str(exc)
        ):
            log.warning("Scheduler job %s outcome was stale for run %s", job_id, run_id[:8])
            return "stale"
        return "settled"

    # One-shot surface owns the session lifecycle: a clarification question or
    # external verification gate parks the checkpoint as PAUSED; a deliverable
    # terminal marks it COMPLETED; any other terminal (max_rounds, exhausted,
    # refusal, ...) is a failed run.
    termination = str(getattr(r, "termination_reason", "") or "") if r is not None else ""
    if termination in _PAUSED_TERMINATIONS:
        status, error = "paused", termination
    elif is_successful_task_termination(termination):
        status, error = "ok", ""
    else:
        detail = getattr(r, "error", "") or ""
        status = "error"
        error = f"turn ended with {termination or 'no result'}" + (f": {detail}" if detail else "")
    try:
        if status == "paused":
            if termination == "user_clarification_needed":
                from core.memory.pending_ask import apublish_clarification_ask

                await apublish_clarification_ask(
                    r.text,
                    session_id=getattr(loop, "_session_id", ""),
                    source=f"scheduled:{job_id}",
                    notification=getattr(services, "notification", None),
                )
            mark_paused_async = getattr(loop, "amark_session_paused", None)
            if callable(mark_paused_async):
                await mark_paused_async()
            elif callable(mark_paused := getattr(loop, "mark_session_paused", None)):
                mark_paused()
        elif status == "ok":
            await loop.amark_session_completed()
        else:
            await loop.amark_session_error()
    except Exception as write_exc:
        raise ScheduledRunUnresolvedError(
            f"scheduled run {run_id[:8]} of {job_id} ended {status} but its session "
            "terminal state was not persisted; the run stays claimed"
        ) from write_exc
    if not _report_outcome(on_settle, job_id, run_id, status, error):
        log.warning(
            "Scheduler job %s outcome was stale for run %s; not announced", job_id, run_id[:8]
        )
        return "stale"
    if on_complete:
        try:
            on_complete(r, job_id=job_id)
        except Exception:
            # The run is already settled; a failing announcement must not
            # make the caller report it as unresolved.
            log.error(
                "Scheduler job %s run %s settled but its completion callback failed",
                job_id,
                run_id[:8],
                exc_info=True,
            )
    return "settled"


async def drain_scheduler_queue(
    *,
    action_queue: Any,
    services: Any,
    session_lane: Any,
    global_lane: Any,
    force_isolated: bool = False,
    main_loop: Any | None = None,
    on_complete: Any | None = None,
    on_dispatch: Any | None = None,
    on_skip: Any | None = None,
    on_main_run: Any | None = None,
    on_settle: Any | None = None,
) -> int:
    """Drain pending scheduled jobs from the action queue.

    Shared by both REPL and serve modes. In serve mode ``force_isolated``
    is True because there is no interactive main session to inject into.

    Uses SessionLane (per-key serial) + Global Lane (capacity) for
    concurrency control through the unified LaneQueue.

    Returns the number of jobs drained. Isolated dispatch is fire-and-
    forget: the function returns once tasks are scheduled, not once
    they complete.

    ``on_settle(job_id, run_id, status, error)`` reports each dispatched
    run's real outcome once: ``ok``/``paused``/``error`` after the matching
    session terminal state is persisted, ``cancelled`` when the turn was
    cancelled, ``skipped`` when no Lane slot was available. ``on_complete``
    fires only after the scheduler accepted that settlement (not for a stale
    or failed one). A required write that fails leaves the run claimed: the
    isolated task logs it at ERROR and returns ``"unresolved"``; a main-session
    run propagates the error.
    """
    import queue as _q

    count = 0
    try:
        while True:
            _item = action_queue.get_nowait()
            # 3-tuple (legacy), 4-tuple (+agent_id), 5-tuple (+run_id fence)
            job_id, fired_action, isolated = _item[:3]
            run_id = _item[4] if len(_item) >= 5 else ""

            if not fired_action:
                _report_or_log(on_settle, job_id, run_id, "error", "empty action")
                continue
            count += 1
            prompt = f"[scheduled-job:{job_id}] {fired_action}"

            if isolated or force_isolated:
                lane_key = f"sched:{job_id}"

                # Dual acquire: session (per-key serial) + global (capacity)
                if not session_lane.try_acquire(lane_key):
                    log.warning("Session key busy, skipping job %s", job_id)
                    if on_skip:
                        on_skip(job_id)
                    _report_or_log(on_settle, job_id, run_id, "skipped", "session lane busy")
                    continue

                if not global_lane.try_acquire(lane_key):
                    session_lane.manual_release(lane_key)
                    log.warning("Global lane full, skipping job %s", job_id)
                    if on_skip:
                        on_skip(job_id)
                    _report_or_log(on_settle, job_id, run_id, "skipped", "global lane full")
                    continue

                _lanes_acquired = True
                try:
                    _iso_conv = ConversationContext()
                    _, _iso_loop = services.create_session(
                        SessionMode.SCHEDULER,
                        conversation=_iso_conv,
                    )

                    async def _arun_isolated(
                        *,
                        _loop: Any = _iso_loop,
                        _p: str = prompt,
                        _jid: str = job_id,
                        _rid: str = run_id,
                        _sess: Any = session_lane,
                        _glob: Any = global_lane,
                        _key: str = lane_key,
                    ) -> str:
                        try:
                            return await _run_isolated(
                                _loop,
                                _p,
                                job_id=_jid,
                                run_id=_rid,
                                services=services,
                                on_settle=on_settle,
                                on_complete=on_complete,
                            )
                        except Exception as exc:
                            # Unresolved (required terminal write or settlement
                            # failed): the claim stays; report it as the result.
                            log.error(
                                "Scheduler job %s run %s is unresolved: %s",
                                _jid,
                                _rid[:8],
                                exc,
                                exc_info=True,
                            )
                            return "unresolved"
                        finally:
                            _glob.manual_release(_key)
                            _sess.manual_release(_key)

                    task = asyncio.create_task(_arun_isolated(), name=f"scheduled:{job_id}")
                    _lanes_acquired = False  # ownership transferred to the task
                except Exception:
                    if _lanes_acquired:
                        global_lane.manual_release(lane_key)
                        session_lane.manual_release(lane_key)
                    log.warning("Scheduler job %s dispatch failed", job_id, exc_info=True)
                    _report_or_log(on_settle, job_id, run_id, "error", "dispatch failed")
                    continue
                # The task now owns this run's outcome: nothing after this point
                # may settle (and so release the claim of) a turn that is running.
                _INFLIGHT_SCHEDULED_TASKS.add(task)
                task.add_done_callback(_INFLIGHT_SCHEDULED_TASKS.discard)
                task.add_done_callback(_log_task_failure)
                if on_dispatch:
                    try:
                        on_dispatch(job_id)
                    except Exception:
                        log.error(
                            "Scheduler job %s run %s dispatched but its dispatch callback failed",
                            job_id,
                            run_id[:8],
                            exc_info=True,
                        )
            # Non-isolated: inject into main session (REPL only)
            elif main_loop is not None:
                if on_main_run:
                    on_main_run(job_id)
                # The main session's lifecycle belongs to the REPL; the drain
                # owns only this run's scheduler outcome. Persistence failures
                # propagate to the caller with the run still claimed.
                try:
                    result = await main_loop.arun(prompt)
                except asyncio.CancelledError:
                    log.warning("Scheduler job %s main-session turn cancelled", job_id)
                    _report_or_log(
                        on_settle, job_id, run_id, "cancelled", "main-session turn cancelled"
                    )
                    raise
                except Exception as exc:
                    log.warning("Scheduler job %s main-loop failed", job_id, exc_info=True)
                    _report_outcome(on_settle, job_id, run_id, "error", str(exc))
                else:
                    termination = str(getattr(result, "termination_reason", "") or "")
                    if is_successful_task_termination(termination):
                        _report_outcome(on_settle, job_id, run_id, "ok")
                    else:
                        _report_outcome(
                            on_settle,
                            job_id,
                            run_id,
                            "error",
                            f"turn ended with {termination or 'no result'}",
                        )
            else:
                _report_or_log(
                    on_settle, job_id, run_id, "skipped", "no main session for a non-isolated job"
                )
    except _q.Empty:
        pass
    return count

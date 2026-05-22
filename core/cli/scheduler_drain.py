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

log = logging.getLogger(__name__)


# Module-level strong refs for fire-and-forget tasks. Required because
# ``asyncio.create_task`` only holds a weak reference; without this the
# task could be GC'd before completion and the event loop would log
# "Task was destroyed but it is pending!".
_INFLIGHT_SCHEDULED_TASKS: set[asyncio.Task[None]] = set()


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
) -> int:
    """Drain pending scheduled jobs from the action queue.

    Shared by both REPL and serve modes. In serve mode ``force_isolated``
    is True because there is no interactive main session to inject into.

    Uses SessionLane (per-key serial) + Global Lane (capacity) for
    concurrency control through the unified LaneQueue.

    Returns the number of jobs drained. Isolated dispatch is fire-and-
    forget: the function returns once tasks are scheduled, not once
    they complete.
    """
    import queue as _q

    count = 0
    try:
        while True:
            _item = action_queue.get_nowait()
            # Support both 3-tuple (legacy) and 4-tuple (with agent_id)
            if len(_item) == 4:
                job_id, fired_action, isolated, _agent_id = _item
            else:
                job_id, fired_action, isolated = _item
                _agent_id = ""
            if not fired_action:
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
                    continue

                if not global_lane.try_acquire(lane_key):
                    session_lane.manual_release(lane_key)
                    log.warning("Global lane full, skipping job %s", job_id)
                    if on_skip:
                        on_skip(job_id)
                    continue

                _lanes_acquired = True
                try:
                    _iso_conv = ConversationContext()
                    from core.server.supervised.services import SessionMode

                    _, _iso_loop = services.create_session(
                        SessionMode.SCHEDULER,
                        conversation=_iso_conv,
                        propagate_context=True,
                    )

                    async def _arun_isolated(
                        *,
                        _loop: Any = _iso_loop,
                        _p: str = prompt,
                        _jid: str = job_id,
                        _sess: Any = session_lane,
                        _glob: Any = global_lane,
                        _key: str = lane_key,
                        _cb: Any = on_complete,
                    ) -> None:
                        try:
                            r = await asyncio.wait_for(_loop.arun(_p), timeout=300.0)
                            if _cb:
                                _cb(r, job_id=_jid)
                        except TimeoutError:
                            log.warning("Scheduler job %s timed out after 300s", _jid)
                        except Exception:
                            log.warning("Scheduler job %s execution failed", _jid, exc_info=True)
                        finally:
                            _glob.manual_release(_key)
                            _sess.manual_release(_key)

                    task = asyncio.create_task(_arun_isolated(), name=f"scheduled:{job_id}")
                    _INFLIGHT_SCHEDULED_TASKS.add(task)
                    task.add_done_callback(_INFLIGHT_SCHEDULED_TASKS.discard)
                    _lanes_acquired = False  # ownership transferred to the task
                    if on_dispatch:
                        on_dispatch(job_id)
                except Exception:
                    if _lanes_acquired:
                        global_lane.manual_release(lane_key)
                        session_lane.manual_release(lane_key)
                    log.warning("Scheduler job %s dispatch failed", job_id, exc_info=True)
            # Non-isolated: inject into main session (REPL only)
            elif main_loop is not None:
                if on_main_run:
                    on_main_run(job_id)
                try:
                    await main_loop.arun(prompt)
                except Exception:
                    log.warning("Scheduler job %s main-loop failed", job_id, exc_info=True)
    except _q.Empty:
        pass
    return count

"""Scheduler queue drain — extracted from cli/__init__.py for SRP.

Drains pending scheduled jobs from the action queue, shared by REPL and serve modes.
"""

from __future__ import annotations

import logging
from typing import Any

from core.agent.conversation import ConversationContext

log = logging.getLogger(__name__)


def drain_scheduler_queue(
    *,
    action_queue: Any,
    services: Any,
    runner: Any,
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

    Shared by both REPL and serve modes.  In serve mode ``force_isolated``
    is True because there is no interactive main session to inject into.

    Uses SessionLane (per-key serial) + Global Lane (capacity) for
    concurrency control through the unified LaneQueue.

    Returns the number of jobs drained.
    """
    import queue as _q

    from core.orchestration.isolated_execution import IsolationConfig

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
                    from core.gateway.shared_services import SessionMode

                    _, _iso_loop = services.create_session(
                        SessionMode.SCHEDULER,
                        conversation=_iso_conv,
                        propagate_context=True,
                    )
                    _cap_loop = _iso_loop
                    _cap_prompt = prompt
                    _cap_jid = job_id
                    _cap_sess = session_lane
                    _cap_glob = global_lane
                    _cap_key = lane_key
                    _cap_cb = on_complete

                    def _run_isolated(
                        *,
                        _loop: Any = _cap_loop,
                        _p: str = _cap_prompt,
                        _jid: str = _cap_jid,
                        _sess: Any = _cap_sess,
                        _glob: Any = _cap_glob,
                        _key: str = _cap_key,
                        _cb: Any = _cap_cb,
                    ) -> str:
                        try:
                            r = _loop.run(_p)
                            if _cb:
                                _cb(r, job_id=_jid)
                            return r.text if r and r.text else ""
                        finally:
                            _glob.manual_release(_key)
                            _sess.manual_release(_key)

                    runner.run_async(
                        _run_isolated,
                        config=IsolationConfig(
                            prefix=f"scheduled:{job_id}",
                            post_to_main=False,
                            timeout_s=300.0,
                        ),
                    )
                    _lanes_acquired = False  # ownership transferred to _run_isolated
                    if on_dispatch:
                        on_dispatch(job_id)
                except Exception:
                    if _lanes_acquired:
                        global_lane.manual_release(lane_key)
                        session_lane.manual_release(lane_key)
                    log.warning("Scheduler job %s dispatch failed", job_id, exc_info=True)
            else:
                # Non-isolated: inject into main session (REPL only)
                if main_loop is not None:
                    if on_main_run:
                        on_main_run(job_id)
                    try:
                        main_loop.run(prompt)
                    except Exception:
                        log.warning("Scheduler job %s main-loop failed", job_id, exc_info=True)
    except _q.Empty:
        pass
    return count

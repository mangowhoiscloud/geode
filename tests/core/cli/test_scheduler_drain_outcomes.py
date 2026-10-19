"""Scheduler drain settles dispatched runs from the real turn outcome (S5 review 2)."""

from __future__ import annotations

import asyncio
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.cli.scheduler_drain import _INFLIGHT_SCHEDULED_TASKS, drain_scheduler_queue
from core.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService


class _Lane:
    def try_acquire(self, _key: str) -> bool:
        return True

    def manual_release(self, _key: str) -> None:
        return None


class _Loop:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.marks: list[str] = []
        self._session_id = "s-sched"

    async def arun(self, _prompt: str) -> Any:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome == "hang":
            await asyncio.sleep(60)
        return self.outcome

    async def amark_session_completed(self) -> None:
        self.marks.append("completed")

    async def amark_session_error(self) -> None:
        self.marks.append("error")

    async def amark_session_paused(self) -> None:
        self.marks.append("paused")


class _Services:
    def __init__(self, outcome: Any) -> None:
        self.loop = _Loop(outcome)

    def create_session(self, _mode: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return None, self.loop


def _svc_with_dispatched_run(tmp_path: Path) -> tuple[SchedulerService, queue.Queue[Any], str]:
    action_queue: queue.Queue[Any] = queue.Queue()
    svc = SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        log_dir=tmp_path / "logs",
        on_job_fired=lambda jid, act, iso, aid, rid: action_queue.put((jid, act, iso, aid, rid)),
        enable_jitter=False,
    )
    svc.create_job(
        ScheduledJob(
            job_id="job",
            name="job",
            schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000),
            action="do it",
        )
    )
    run = svc.run_now("job")
    assert run["status"] == "dispatched"
    return svc, action_queue, run["run_id"]


async def _drain(action_queue: Any, services: Any, svc: SchedulerService, **kw: Any) -> None:
    await drain_scheduler_queue(
        action_queue=action_queue,
        services=services,
        session_lane=_Lane(),
        global_lane=_Lane(),
        on_settle=lambda jid, rid, status, error: svc.record_run_outcome(
            jid, rid, status, error=error
        ),
        **kw,
    )
    if _INFLIGHT_SCHEDULED_TASKS:
        await asyncio.gather(*list(_INFLIGHT_SCHEDULED_TASKS), return_exceptions=True)


async def _drain_collect(
    action_queue: Any, services: Any, svc: SchedulerService, **kw: Any
) -> tuple[list[BaseException | None], list[str]]:
    """Drain isolated runs; return each task's real result and announced completions."""
    completed: list[str] = []
    await drain_scheduler_queue(
        action_queue=action_queue,
        services=services,
        session_lane=_Lane(),
        global_lane=_Lane(),
        force_isolated=True,
        on_complete=lambda _r, *, job_id: completed.append(job_id),
        on_settle=kw.pop(
            "on_settle",
            lambda jid, rid, status, error: svc.record_run_outcome(jid, rid, status, error=error),
        ),
        **kw,
    )
    tasks = list(_INFLIGHT_SCHEDULED_TASKS)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return list(results), completed


def _persisted(tmp_path: Path) -> ScheduledJob:
    reader = SchedulerService(store_path=tmp_path / "scheduled_tasks.json", log_dir=tmp_path / "r")
    reader.load()
    job = reader.get_job("job")
    assert job is not None
    return job


@pytest.mark.parametrize("termination", ["max_rounds", "context_exhausted", "model_refusal"])
def test_failed_isolated_turn_settles_error_not_completed(tmp_path: Path, termination: str) -> None:
    svc, action_queue, _run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(
        SimpleNamespace(termination_reason=termination, error="exhausted", text="")
    )
    asyncio.run(_drain(action_queue, services, svc, force_isolated=True))
    assert services.loop.marks == ["error"]
    job = _persisted(tmp_path)
    assert job.last_status == "error" and job.run_id == "" and job.running_since_ms is None


def test_successful_isolated_turn_settles_ok_after_completion_persisted(tmp_path: Path) -> None:
    svc, action_queue, _run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(SimpleNamespace(termination_reason="natural", error=None, text="done"))
    asyncio.run(_drain(action_queue, services, svc, force_isolated=True))
    assert services.loop.marks == ["completed"]
    assert _persisted(tmp_path).last_status == "ok"


def test_completion_persistence_failure_leaves_the_run_unresolved(tmp_path: Path) -> None:
    svc, action_queue, run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(SimpleNamespace(termination_reason="natural", error=None, text="done"))

    async def broken_completion() -> None:
        raise OSError("checkpoint write failed")

    services.loop.amark_session_completed = broken_completion  # type: ignore[method-assign]
    outcomes, completed = asyncio.run(_drain_collect(action_queue, services, svc))
    assert outcomes == ["unresolved"]
    assert completed == []
    job = _persisted(tmp_path)
    assert job.run_id == run_id and job.running_since_ms is not None
    assert job.last_status != "ok"


def test_main_session_failed_turn_settles_error(tmp_path: Path) -> None:
    svc, raw_queue, _run_id = _svc_with_dispatched_run(tmp_path)
    jid, act, _iso, aid, rid = raw_queue.get_nowait()
    raw_queue.put((jid, act, False, aid, rid))
    main = _Loop(SimpleNamespace(termination_reason="max_rounds", error="exhausted"))
    asyncio.run(_drain(raw_queue, None, svc, main_loop=main))
    assert _persisted(tmp_path).last_status == "error"


def test_cancelled_run_is_persisted_as_cancelled_and_releases_claim(tmp_path: Path) -> None:
    svc, action_queue, _run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services("hang")

    async def scenario() -> None:
        await drain_scheduler_queue(
            action_queue=action_queue,
            services=services,
            session_lane=_Lane(),
            global_lane=_Lane(),
            force_isolated=True,
            on_settle=lambda jid, rid, status, error: svc.record_run_outcome(
                jid, rid, status, error=error
            ),
        )
        (task,) = list(_INFLIGHT_SCHEDULED_TASKS)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert services.loop.marks == ["error"]
    job = _persisted(tmp_path)
    assert job.last_status == "cancelled" and job.running_since_ms is None


def test_unpersisted_outcome_keeps_the_run_claimed(tmp_path: Path) -> None:
    svc, action_queue, run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(SimpleNamespace(termination_reason="natural", error=None, text="done"))

    def failing_settle(*_args: Any) -> None:
        raise OSError("store unavailable")

    async def scenario() -> None:
        await drain_scheduler_queue(
            action_queue=action_queue,
            services=services,
            session_lane=_Lane(),
            global_lane=_Lane(),
            force_isolated=True,
            on_settle=failing_settle,
        )
        await asyncio.gather(*list(_INFLIGHT_SCHEDULED_TASKS), return_exceptions=True)

    asyncio.run(scenario())
    job = _persisted(tmp_path)
    assert job.run_id == run_id and job.running_since_ms is not None
    assert svc.run_now("job")["reason"] == "already_running"


def _active(run_id: str) -> bool:
    from core.scheduler import service

    with service._ACTIVE_RUNS_LOCK:
        return run_id in service._ACTIVE_RUNS


class _FailingErrorWriteLoop(_Loop):
    async def amark_session_error(self) -> None:
        self.marks.append("error-write-attempt")
        raise OSError("session store unavailable")


@pytest.mark.parametrize("failure", [RuntimeError("tool crashed"), "hang"])
def test_unpersisted_session_error_is_not_settled(
    tmp_path: Path, failure: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """R1: a failed required session write never becomes a settled run."""
    svc, action_queue, run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(failure)
    services.loop = _FailingErrorWriteLoop(failure)

    async def scenario() -> BaseException | None:
        await drain_scheduler_queue(
            action_queue=action_queue,
            services=services,
            session_lane=_Lane(),
            global_lane=_Lane(),
            force_isolated=True,
            on_settle=lambda jid, rid, status, error: svc.record_run_outcome(
                jid, rid, status, error=error
            ),
        )
        (task,) = list(_INFLIGHT_SCHEDULED_TASKS)
        if failure == "hang":
            await asyncio.sleep(0)
            task.cancel()
        (outcome,) = await asyncio.gather(task, return_exceptions=True)
        return outcome

    outcome = asyncio.run(scenario())
    if failure == "hang":
        assert isinstance(outcome, asyncio.CancelledError)
    else:
        assert outcome == "unresolved"
        (record,) = [r for r in caplog.records if "is unresolved" in r.getMessage()]
        assert record.exc_info is not None
        assert record.exc_info[1].__cause__ is failure  # primary failure preserved
    assert services.loop.marks == ["error-write-attempt"]
    job = _persisted(tmp_path)
    assert job.run_id == run_id and job.running_since_ms is not None
    assert _active(run_id)
    assert svc.run_now("job")["reason"] == "already_running"


def test_settlement_store_failure_is_the_task_failure_and_not_announced(tmp_path: Path) -> None:
    """R2: canonical success + real scheduler store write failure."""
    svc, action_queue, run_id = _svc_with_dispatched_run(tmp_path)
    services = _Services(SimpleNamespace(termination_reason="natural", error=None, text="done"))
    tmp_path.chmod(0o500)  # the store's tempfile+rename now fails for real
    try:
        outcomes, completed = asyncio.run(_drain_collect(action_queue, services, svc))
    finally:
        tmp_path.chmod(0o700)
    assert outcomes == ["unresolved"]
    assert services.loop.marks == ["completed"]
    assert completed == []  # no completion announced for an unpersisted settlement
    job = _persisted(tmp_path)
    assert job.run_id == run_id and _active(run_id)


def test_stale_settlement_is_not_announced(tmp_path: Path) -> None:
    svc, action_queue, _run_id = _svc_with_dispatched_run(tmp_path)
    assert svc.delete_job("job")  # the run's job vanished: its outcome is stale
    services = _Services(SimpleNamespace(termination_reason="natural", error=None, text="done"))
    outcomes, completed = asyncio.run(_drain_collect(action_queue, services, svc))
    assert outcomes == ["stale"]
    assert completed == []


def test_main_session_cancellation_settles_cancelled(tmp_path: Path) -> None:
    """R3: the main-session branch records cancellation, then propagates it."""
    svc, raw_queue, run_id = _svc_with_dispatched_run(tmp_path)
    jid, act, _iso, aid, rid = raw_queue.get_nowait()
    raw_queue.put((jid, act, False, aid, rid))
    main = _Loop("hang")

    async def scenario() -> None:
        drain = asyncio.create_task(_drain(raw_queue, None, svc, main_loop=main))
        await asyncio.sleep(0.05)
        drain.cancel()
        with pytest.raises(asyncio.CancelledError):
            await drain

    asyncio.run(scenario())
    job = _persisted(tmp_path)
    assert job.last_status == "cancelled" and job.running_since_ms is None
    assert not _active(run_id)


def test_main_session_settlement_failure_propagates(tmp_path: Path) -> None:
    svc, raw_queue, run_id = _svc_with_dispatched_run(tmp_path)
    jid, act, _iso, aid, rid = raw_queue.get_nowait()
    raw_queue.put((jid, act, False, aid, rid))
    main = _Loop(SimpleNamespace(termination_reason="natural", error=None))
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(OSError):
            asyncio.run(_drain(raw_queue, None, svc, main_loop=main))
    finally:
        tmp_path.chmod(0o700)
    assert _persisted(tmp_path).run_id == run_id and _active(run_id)

"""Scheduler store transactions and fenced run claims (S5).

Every durable mutation is lock -> reload -> operate -> persist, and a run is
claimed against the current store with a ``run_id`` fence. These tests use
independent service instances (and processes) on one store, the way two
daemons or a stale in-memory copy would.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from core.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService
from core.scheduler.service import SchedulerStoreError

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _svc(tmp_path: Path, **kwargs: Any) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        log_dir=tmp_path / "logs",
        enable_jitter=False,
        **kwargs,
    )


def _job(job_id: str, **kwargs: Any) -> ScheduledJob:
    kwargs.setdefault("schedule", Schedule(kind=ScheduleKind.EVERY, every_ms=60_000))
    kwargs.setdefault("action", f"action {job_id}")
    return ScheduledJob(job_id=job_id, name=job_id, **kwargs)


# A process identity that cannot exist (PID beyond any real range).
_DEAD_OWNER = "4194303999:1.000000"


def _set_disk_owner(tmp_path: Path, job_id: str, owner: str) -> None:
    store = tmp_path / "scheduled_tasks.json"
    data = json.loads(store.read_text())
    data[job_id]["run_owner"] = owner
    store.write_text(json.dumps(data))


def _disk(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((tmp_path / "scheduled_tasks.json").read_text())
    return data


def test_stale_instance_cannot_lose_another_instances_addition(tmp_path: Path) -> None:
    a, b = _svc(tmp_path), _svc(tmp_path)
    a.load()
    b.load()  # b's memory predates a's addition
    a.create_job(_job("from-a"))
    b.create_job(_job("from-b"))
    assert set(_disk(tmp_path)) == {"from-a", "from-b"}


def test_stale_instance_cannot_resurrect_deleted_or_unpause_paused_jobs(tmp_path: Path) -> None:
    a = _svc(tmp_path)
    a.create_job(_job("deleted"))
    a.create_job(_job("paused"))
    b = _svc(tmp_path)
    b.load()  # b holds both jobs, enabled
    assert a.delete_job("deleted")
    assert a.set_job_enabled("paused", False)

    b.add_job(_job("new-in-b"))  # an unrelated pending change
    b.save()
    disk = _disk(tmp_path)
    assert "deleted" not in disk
    assert disk["paused"]["enabled"] is False
    assert "new-in-b" in disk
    # An update to a job deleted elsewhere is dropped, not re-created.
    assert b.update_job("deleted", enabled=False) is False
    b.save()
    assert "deleted" not in _disk(tmp_path)


def test_command_against_a_job_deleted_elsewhere_reports_not_found(tmp_path: Path) -> None:
    a = _svc(tmp_path)
    a.create_job(_job("j"))
    b = _svc(tmp_path)
    b.load()
    assert a.delete_job("j")
    assert b.set_job_enabled("j", False) is False
    assert b.delete_job("j") is False
    assert "j" not in _disk(tmp_path)


_CREATE = """
import sys
from pathlib import Path
from core.scheduler import Schedule, ScheduledJob, ScheduleKind, SchedulerService
svc = SchedulerService(store_path=Path(sys.argv[1]), log_dir=Path(sys.argv[2]))
for index in range(int(sys.argv[4])):
    job_id = f"{sys.argv[3]}-{index}"
    svc.create_job(ScheduledJob(job_id=job_id, name=job_id,
        schedule=Schedule(kind=ScheduleKind.EVERY, every_ms=60_000 + index),
        action=f"run {job_id}"))
"""


def test_concurrent_processes_never_lose_additions(tmp_path: Path) -> None:
    store, logs = tmp_path / "scheduled_tasks.json", tmp_path / "logs"
    procs = [
        subprocess.Popen(  # noqa: S603  # nosec B603 - fixed test interpreter argv
            [sys.executable, "-c", _CREATE, str(store), str(logs), f"p{n}", "8"],
            cwd=_REPO_ROOT,
        )
        for n in range(4)
    ]
    assert [proc.wait(timeout=120) for proc in procs] == [0, 0, 0, 0]
    assert len(_disk(tmp_path)) == 32


def test_two_instances_fire_one_due_occurrence_once(tmp_path: Path) -> None:
    fired: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def slow_dispatch(jid: str, _act: str, _iso: bool, _aid: str, _rid: str) -> None:
        fired.append(jid)
        entered.set()
        release.wait(5)

    _svc(tmp_path).create_job(_job("due"))
    a = _svc(tmp_path, on_job_fired=slow_dispatch)
    b = _svc(tmp_path, on_job_fired=slow_dispatch)
    a.load()
    b.load()
    now = time.time() * 1000 + 120_000  # past next_run for both stale copies

    worker = threading.Thread(target=a.check_due_jobs, kwargs={"now_ms": now})
    worker.start()
    assert entered.wait(5)
    second = b.check_due_jobs(now_ms=now)  # same occurrence, already claimed on disk
    release.set()
    worker.join(5)
    assert fired == ["due"]
    assert second == []


def test_concurrent_manual_runs_execute_once(tmp_path: Path) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def slow_callback(data: dict[str, Any]) -> None:
        calls.append(data["job_id"])
        entered.set()
        release.wait(5)

    svc = _svc(tmp_path)
    svc.create_job(_job("manual", action="", callback=slow_callback))
    results: list[dict[str, Any]] = []
    worker = threading.Thread(target=lambda: results.append(svc.run_now("manual")))
    worker.start()
    assert entered.wait(5)
    skipped = svc.run_now("manual")
    release.set()
    worker.join(5)
    assert calls == ["manual"]
    assert skipped["status"] == "skipped" and skipped["reason"] == "already_running"
    assert results[0]["status"] == "ok"


def test_old_completion_cannot_settle_a_newer_run(tmp_path: Path) -> None:
    fired: list[str] = []
    svc = _svc(tmp_path, on_job_fired=lambda jid, act, iso, aid, rid: fired.append(rid))
    svc.create_job(_job("action-job"))
    first = svc.run_now("action-job")
    assert first["status"] == "dispatched"
    # Elapsed time alone never frees the claim while its owner is alive...
    svc.STUCK_TIMEOUT_MS = -1.0
    assert svc.run_now("action-job")["reason"] == "already_running"
    assert svc.detect_stuck_jobs() == ["action-job"]
    assert svc.run_now("action-job")["reason"] == "already_running"
    # ...only an owner observed gone does: here the claiming process "crashed".
    _set_disk_owner(tmp_path, "action-job", _DEAD_OWNER)
    second = svc.run_now("action-job")
    assert second["status"] == "dispatched" and second["run_id"] != first["run_id"]

    assert svc.record_run_outcome("action-job", first["run_id"], "ok") is False
    current = _svc(tmp_path)
    current.load()
    job = current.get_job("action-job")
    assert job is not None and job.run_id == second["run_id"]
    assert job.running_since_ms is not None

    assert svc.record_run_outcome("action-job", second["run_id"], "error", error="boom")
    current.load()
    job = current.get_job("action-job")
    assert job is not None and job.run_id == "" and job.last_status == "error"
    assert fired == [first["run_id"], second["run_id"]]


def test_manual_run_does_not_consume_the_next_scheduled_occurrence(tmp_path: Path) -> None:
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    future = time.time() * 1000 + 3_600_000
    svc.create_job(_job("at-job", schedule=Schedule(kind=ScheduleKind.AT, at_ms=future)))
    svc.create_job(_job("every-job"))
    every_next = svc.get_job("every-job").next_run_at_ms  # type: ignore[union-attr]

    for job_id in ("at-job", "every-job"):
        run = svc.run_now(job_id)
        assert svc.record_run_outcome(job_id, run["run_id"], "ok")

    reloaded = _svc(tmp_path)
    reloaded.load()
    at_job = reloaded.get_job("at-job")
    assert at_job is not None and at_job.enabled and at_job.next_run_at_ms == future
    assert reloaded.get_job("every-job").next_run_at_ms == every_next  # type: ignore[union-attr]


def test_scheduled_at_run_is_disabled_before_dispatch_returns(tmp_path: Path) -> None:
    """A crash after dispatch cannot re-fire the one-shot job on restart."""
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    at_ms = time.time() * 1000 + 1_000
    svc.create_job(_job("once", schedule=Schedule(kind=ScheduleKind.AT, at_ms=at_ms)))
    results = svc.check_due_jobs(now_ms=at_ms + 10)
    assert [r["status"] for r in results] == ["dispatched"]

    # Simulated crash: the outcome is never reported. The claim is on disk.
    restarted = _svc(tmp_path, on_job_fired=lambda *_args: None)
    restarted.load()
    assert restarted.recover_missed_tasks(now_ms=at_ms + 500) == []
    assert restarted.check_due_jobs(now_ms=at_ms + 500) == []


def test_unreadable_store_rejects_mutation_and_stays_byte_identical(tmp_path: Path) -> None:
    store = tmp_path / "scheduled_tasks.json"
    store.write_text("{not json", encoding="utf-8")
    svc = _svc(tmp_path)
    with pytest.raises(SchedulerStoreError):
        svc.create_job(_job("x"))
    with pytest.raises(SchedulerStoreError):
        svc.save()
    assert store.read_text(encoding="utf-8") == "{not json"


_HOLD_RUN = """
import sys, time
from pathlib import Path
from core.scheduler import SchedulerService
svc = SchedulerService(store_path=Path(sys.argv[1]), log_dir=Path(sys.argv[2]),
                       on_job_fired=lambda *args: None)
svc.load()
assert svc.run_now("held")["status"] == "dispatched"
print("claimed", flush=True)
time.sleep(60)
"""


def test_live_owner_in_another_process_is_never_overlapped(tmp_path: Path) -> None:
    """Review 1: elapsed time past STUCK_TIMEOUT_MS is not observed termination."""
    _svc(tmp_path).create_job(_job("held"))
    proc = subprocess.Popen(  # noqa: S603  # nosec B603 - fixed test interpreter argv
        [sys.executable, "-c", _HOLD_RUN, str(tmp_path / "scheduled_tasks.json"), str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=_REPO_ROOT,
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "claimed"
        svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
        svc.STUCK_TIMEOUT_MS = -1.0  # every active run is "stuck" by age
        svc.load()
        assert svc.run_now("held")["reason"] == "already_running"
        assert svc.check_due_jobs(now_ms=time.time() * 1000 + 600_000) == []
        assert svc.detect_stuck_jobs() == ["held"]
        assert svc.run_now("held")["reason"] == "already_running"  # still not released
        proc.kill()
        proc.wait(timeout=10)
        # Owner observed gone: its run is recorded interrupted and a new run may start.
        assert svc.run_now("held")["status"] == "dispatched"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_manual_provenance_is_persisted_for_cross_instance_settlement(tmp_path: Path) -> None:
    """Review 3: settling a manual run of a future AT job elsewhere keeps the job."""
    future = time.time() * 1000 + 3_600_000
    a = _svc(tmp_path, on_job_fired=lambda *_args: None)
    a.create_job(
        _job("at", schedule=Schedule(kind=ScheduleKind.AT, at_ms=future), delete_after_run=True)
    )
    run = a.run_now("at")
    b = _svc(tmp_path)
    b.load()
    assert b.record_run_outcome("at", run["run_id"], "ok")
    disk = _disk(tmp_path)["at"]
    assert disk["enabled"] is True and disk["next_run_at_ms"] == future


def test_malformed_row_rejects_every_write_and_keeps_the_file(tmp_path: Path) -> None:
    """Review 4: a parsed store with one malformed job is unreadable, not prunable."""
    good = _svc(tmp_path)
    good.create_job(_job("good"))
    store = tmp_path / "scheduled_tasks.json"
    data = json.loads(store.read_text())
    data["broken"] = {"job_id": "broken", "name": "missing schedule"}
    store.write_text(json.dumps(data))
    before = store.read_bytes()
    svc = _svc(tmp_path)
    for mutate in (
        lambda: svc.create_job(_job("new")),
        lambda: svc.delete_job("good"),
        svc.save,
    ):
        with pytest.raises(SchedulerStoreError):
            mutate()
    assert store.read_bytes() == before


def test_callback_rows_survive_writes_by_instances_without_the_callback(tmp_path: Path) -> None:
    owner = _svc(tmp_path)
    owner.add_job(_job("report", action="", callback=lambda _data: None, enabled=False))
    owner.save()
    other = _svc(tmp_path)  # e.g. a process that never registers this callback
    other.create_job(_job("unrelated"))
    assert set(_disk(tmp_path)) == {"report", "unrelated"}
    assert _disk(tmp_path)["report"]["enabled"] is False


def test_rescheduled_cron_is_revalidated_under_the_claim(tmp_path: Path) -> None:
    """Review 5: a stale "due" decision cannot fire a schedule changed elsewhere."""
    fired: list[str] = []
    a = _svc(tmp_path, on_job_fired=lambda jid, *_rest: fired.append(jid))
    a.create_job(_job("cron", schedule=Schedule(kind=ScheduleKind.CRON, cron_expr="* * * * *")))
    b = _svc(tmp_path)
    b.load()
    minute = time.localtime().tm_min
    never_now = f"{(minute + 30) % 60} * * * *"
    b.update_job("cron", schedule=Schedule(kind=ScheduleKind.CRON, cron_expr=never_now))
    b.save()
    # a still holds "* * * * *" in memory; its outer check says due.
    assert a.check_due_jobs() == []
    assert fired == []


def test_missed_at_disabled_elsewhere_is_not_recovered(tmp_path: Path) -> None:
    fired: list[str] = []
    now = time.time() * 1000
    a = _svc(tmp_path, on_job_fired=lambda jid, *_rest: fired.append(jid))
    a.create_job(_job("missed", schedule=Schedule(kind=ScheduleKind.AT, at_ms=now + 1_000)))
    b = _svc(tmp_path)
    b.load()
    assert b.set_job_enabled("missed", False)
    assert a.find_missed_tasks(now_ms=now + 2_000)  # stale in-memory view says missed
    assert a.recover_missed_tasks(now_ms=now + 2_000) == []
    assert fired == []


def test_failed_claim_publication_leaves_no_registered_owner(tmp_path: Path) -> None:
    """R4: a claim whose durable write fails is withdrawn from the live registry."""
    from core.scheduler import service

    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    svc.create_job(_job("j"))
    with service._ACTIVE_RUNS_LOCK:
        before = set(service._ACTIVE_RUNS)
    tmp_path.chmod(0o500)  # real write failure: no tempfile can be created
    try:
        for _ in range(3):
            with pytest.raises(OSError):
                svc.run_now("j")
    finally:
        tmp_path.chmod(0o700)
    with service._ACTIVE_RUNS_LOCK:
        assert set(service._ACTIVE_RUNS) == before
    assert _disk(tmp_path)["j"]["run_id"] == ""
    # After the fault clears the claim works and is registered once.
    run = svc.run_now("j")
    assert run["status"] == "dispatched"
    with service._ACTIVE_RUNS_LOCK:
        assert service._ACTIVE_RUNS - before == {run["run_id"]}


def test_failed_claim_write_does_not_advance_the_occurrence_in_memory(tmp_path: Path) -> None:
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    svc.create_job(_job("every"))
    job = svc.get_job("every")
    assert job is not None and job.next_run_at_ms is not None
    due = job.next_run_at_ms + 1
    with (
        mock.patch.object(svc, "_write_locked", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        svc.check_due_jobs(now_ms=due)
    restored = svc.get_job("every")
    assert restored is not None and restored.next_run_at_ms == job.next_run_at_ms
    assert restored.running_since_ms is None
    [result] = svc.check_due_jobs(now_ms=due)
    assert result["status"] == "dispatched"


def test_stuck_run_is_reported_once_per_run(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []
    hooks = mock.Mock(
        trigger=lambda _event, payload: (
            payloads.append(payload)
            if payload.get("source") == "scheduler_stuck_detection"
            else None
        )
    )
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None, hooks=hooks)
    svc.create_job(_job("held"))
    first = svc.run_now("held")
    svc.STUCK_TIMEOUT_MS = -1.0
    assert svc.detect_stuck_jobs() == ["held"]
    assert svc.detect_stuck_jobs() == []
    svc.load()  # a store reload rebuilds the row; the same run stays reported
    assert svc.detect_stuck_jobs() == []
    assert len(payloads) == 1
    held = svc.get_job("held")
    assert held is not None and held.last_status == "stuck"
    assert svc.run_now("held")["reason"] == "already_running"
    # A run whose owner is gone is still settled, and a new stuck run is reported.
    _set_disk_owner(tmp_path, "held", _DEAD_OWNER)
    second = svc.run_now("held")
    assert second["status"] == "dispatched" and second["run_id"] != first["run_id"]
    assert svc.detect_stuck_jobs() == ["held"]
    assert len(payloads) == 2


def test_failed_cron_claim_write_keeps_the_minute_retryable(tmp_path: Path) -> None:
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    svc.create_job(_job("cron", schedule=Schedule(kind=ScheduleKind.CRON, cron_expr="* * * * *")))
    now = time.time() * 1000
    with (
        mock.patch.object(svc, "_write_locked", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        svc.check_due_jobs(now_ms=now)
    [result] = svc.check_due_jobs(now_ms=now)
    assert result["status"] == "dispatched"


def test_failed_claim_write_restores_a_session_only_job(tmp_path: Path) -> None:
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None)
    svc.create_job(_job("durable"))  # a store exists, so claims run in a transaction
    svc.create_job(_job("session", durable=False))
    job = svc.get_job("session")
    assert job is not None and job.next_run_at_ms is not None
    due = job.next_run_at_ms + 1
    with (
        mock.patch.object(svc, "_write_locked", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        svc.run_now("session")
    assert job.running_since_ms is None and job.run_id == ""
    assert job.next_run_at_ms == due - 1
    assert svc.run_now("session")["status"] == "dispatched"


def test_stuck_report_survives_a_failure_later_in_the_same_tick(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []
    hooks = mock.Mock(trigger=lambda _event, payload: payloads.append(payload))
    svc = _svc(tmp_path, on_job_fired=lambda *_args: None, hooks=hooks)
    svc.create_job(_job("alive"))
    svc.create_job(_job("gone"))
    svc.run_now("alive")
    svc.run_now("gone")
    _set_disk_owner(tmp_path, "gone", _DEAD_OWNER)
    svc.load()
    svc.STUCK_TIMEOUT_MS = -1.0
    with (
        mock.patch.object(svc, "_settle", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        svc.detect_stuck_jobs()
    payloads.clear()
    assert "alive" in svc.detect_stuck_jobs()
    assert any("alive" in p.get("stuck_jobs", []) for p in payloads)

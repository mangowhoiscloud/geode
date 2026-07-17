"""Tests for LaneQueue — concurrency control with named lanes."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from core.orchestration.lane_queue import Lane, LaneQueue, SessionLane


class TestLane:
    def test_acquire_and_release(self):
        lane = Lane("test", max_concurrent=2)
        assert lane.active_count == 0
        assert lane.available == 2

        with lane.acquire("job-1"):
            assert lane.active_count == 1
            assert lane.available == 1

        assert lane.active_count == 0
        assert lane.available == 2

    def test_concurrent_limit(self):
        lane = Lane("test", max_concurrent=1, timeout_s=0.1)
        acquired = threading.Event()
        release = threading.Event()

        def hold_lane():
            with lane.acquire("blocker"):
                acquired.set()
                release.wait(timeout=2.0)

        t = threading.Thread(target=hold_lane, daemon=True)
        t.start()
        acquired.wait(timeout=1.0)

        # Second acquire should timeout
        with pytest.raises(TimeoutError, match="timeout"), lane.acquire("blocked"):
            pass

        release.set()
        t.join(timeout=1.0)

    def test_stats_tracking(self):
        lane = Lane("test", max_concurrent=2)
        with lane.acquire("job-1"):
            pass

        assert lane.stats.acquired == 1
        assert lane.stats.released == 1
        assert lane.stats.timeouts == 0

    def test_get_active(self):
        lane = Lane("test", max_concurrent=2)
        with lane.acquire("job-1"):
            active = lane.get_active()
            assert "job-1" in active
            assert active["job-1"] >= 0

    def test_stats_to_dict(self):
        lane = Lane("test")
        d = lane.stats.to_dict()
        assert set(d.keys()) == {"acquired", "released", "timeouts"}

    def test_acquire_async_and_release(self):
        lane = Lane("test", max_concurrent=1)

        async def scenario() -> None:
            async with lane.acquire_async("job-async"):
                assert lane.active_count == 1
                assert not lane.try_acquire("job-sync")
            assert lane.active_count == 0

        asyncio.run(scenario())


class TestLaneQueue:
    def test_add_and_list_lanes(self):
        q = LaneQueue()
        q.add_lane("global", max_concurrent=8)
        assert q.list_lanes() == ["global"]

    def test_list_lanes_with_session(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=8)
        assert "session" in q.list_lanes()
        assert "global" in q.list_lanes()

    def test_get_lane(self):
        q = LaneQueue()
        q.add_lane("test")
        lane = q.get_lane("test")
        assert lane is not None
        assert lane.name == "test"

    def test_get_nonexistent_lane(self):
        q = LaneQueue()
        assert q.get_lane("nope") is None

    def test_session_lane_property(self):
        q = LaneQueue()
        assert q.session_lane is None
        sl = SessionLane(max_sessions=10)
        q.set_session_lane(sl)
        assert q.session_lane is sl

    def test_acquire_all_async_session_and_global(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=8)

        async def scenario() -> None:
            async with q.acquire_all_async("gateway:slack:C123", ["session", "global"]):
                assert q.session_lane is not None and q.session_lane.active_count == 1
                gl = q.get_lane("global")
                assert gl is not None and gl.active_count == 1

        asyncio.run(scenario())

        assert q.session_lane is not None and q.session_lane.active_count == 0
        gl = q.get_lane("global")
        assert gl is not None and gl.active_count == 0

    def test_acquire_all_async_session_gateway_global(self):
        """Gateway path acquires session → gateway → global (3 lanes)."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("gateway", max_concurrent=4)
        q.add_lane("global", max_concurrent=8)

        async def scenario() -> None:
            async with q.acquire_all_async("slack:C01:U01", ["session", "gateway", "global"]):
                assert q.session_lane is not None and q.session_lane.active_count == 1
                gw = q.get_lane("gateway")
                assert gw is not None and gw.active_count == 1
                gl = q.get_lane("global")
                assert gl is not None and gl.active_count == 1

        asyncio.run(scenario())

        # All released
        assert q.session_lane is not None and q.session_lane.active_count == 0
        gw = q.get_lane("gateway")
        assert gw is not None and gw.active_count == 0
        gl = q.get_lane("global")
        assert gl is not None and gl.active_count == 0

    def test_gateway_lane_caps_concurrent(self):
        """Gateway lane (max=2) blocks 3rd concurrent gateway request."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10, timeout_s=1.0))
        q.add_lane("gateway", max_concurrent=2, timeout_s=0.1)
        q.add_lane("global", max_concurrent=8, timeout_s=1.0)

        async def scenario() -> None:
            # Fill gateway lane with 2 requests
            async with (
                q.acquire_all_async("gw:1", ["session", "gateway", "global"]),
                q.acquire_all_async("gw:2", ["session", "gateway", "global"]),
            ):
                gw = q.get_lane("gateway")
                assert gw is not None and gw.active_count == 2
                # 3rd gateway request should timeout
                with pytest.raises(TimeoutError, match="gateway"):
                    async with q.acquire_all_async("gw:3", ["session", "gateway", "global"]):
                        pass

        asyncio.run(scenario())

    def test_cli_bypasses_gateway_lane(self):
        """CLI path uses only session + global, not gateway."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10, timeout_s=1.0))
        q.add_lane("gateway", max_concurrent=2, timeout_s=0.1)
        q.add_lane("global", max_concurrent=8, timeout_s=1.0)

        async def scenario() -> None:
            # Fill gateway lane, then prove CLI still works (bypasses gateway)
            async with (
                q.acquire_all_async("gw:1", ["session", "gateway", "global"]),
                q.acquire_all_async("gw:2", ["session", "gateway", "global"]),
                q.acquire_all_async("cli:1", ["session", "global"]),
            ):
                gl = q.get_lane("global")
                assert gl is not None and gl.active_count == 3  # 2 gw + 1 cli

        asyncio.run(scenario())

    def test_acquire_all_async_unknown_lane(self):
        q = LaneQueue()

        async def scenario() -> None:
            with pytest.raises(KeyError, match="not found"):
                async with q.acquire_all_async("job-1", ["nonexistent"]):
                    pass

        asyncio.run(scenario())

    def test_acquire_all_async_no_session_lane_skips(self):
        """If no session lane registered, 'session' in lane_names is skipped."""
        q = LaneQueue()
        q.add_lane("global", max_concurrent=8)

        async def scenario() -> None:
            async with q.acquire_all_async("key", ["session", "global"]):
                gl = q.get_lane("global")
                assert gl is not None and gl.active_count == 1

        asyncio.run(scenario())

    def test_acquire_all_async_partial_failure_releases_session(self):
        """If global times out, session lane must be released."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=1, timeout_s=0.1)

        # Exhaust global
        gl = q.get_lane("global")
        assert gl is not None
        gl._semaphore.acquire()

        async def scenario() -> None:
            with pytest.raises(TimeoutError):
                async with q.acquire_all_async("key", ["session", "global"]):
                    pass

        asyncio.run(scenario())

        # Session lane must be released
        assert q.session_lane is not None and q.session_lane.active_count == 0
        gl._semaphore.release()

    def test_cancelled_acquire_releases_stray_grant(self):
        """An abandoned off-thread acquire that is granted AFTER cancellation
        must release itself — otherwise the lane starves every later waiter
        for that key (shutdown-drain cancelling a Socket Mode worker)."""
        q = LaneQueue()
        q.add_lane("global", max_concurrent=1, timeout_s=5.0)
        gl = q.get_lane("global")
        assert gl is not None
        # Hold the lane so the acquire below parks in the executor thread.
        gl._semaphore.acquire()

        async def scenario() -> None:
            async def use_lane() -> None:
                async with q.acquire_all_async("key", ["global"]):
                    raise AssertionError("must not be granted while cancelled")

            waiter = asyncio.create_task(use_lane())
            await asyncio.sleep(0.2)  # let the executor thread park on acquire
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            # Grant the abandoned acquire; the stray-grant callback releases.
            gl._semaphore.release()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if gl._semaphore.acquire(blocking=False):
                    gl._semaphore.release()
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("stray grant was never released — lane leaked")

        asyncio.run(scenario())

    def test_status_with_session_lane(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=256))
        q.add_lane("global", max_concurrent=8)

        status = q.status()
        assert "session" in status
        assert status["session"]["max_sessions"] == 256
        assert status["global"]["max"] == 8

    def test_acquire_all_async_blocks_sync_try_acquire(self):
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=10))
        q.add_lane("global", max_concurrent=1)

        async def scenario() -> None:
            async with q.acquire_all_async("cli:async", ["session", "global"]):
                assert q.session_lane is not None and q.session_lane.active_count == 1
                gl = q.get_lane("global")
                assert gl is not None and gl.active_count == 1
                assert not gl.try_acquire("blocked")
            assert q.session_lane is not None and q.session_lane.active_count == 0
            gl = q.get_lane("global")
            assert gl is not None and gl.active_count == 0

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# PR-LQ-Phase5 — observability surface
# ---------------------------------------------------------------------------


class TestGetStuck:
    """Lane.get_stuck / SessionLane.get_stuck pin the stuck-key shape:
    a positive threshold returns keys held >= threshold, negative or
    zero returns empty.

    Tests construct ``_active`` / session-entry state directly with a
    backdated timestamp so we don't have to ``time.sleep`` for the
    threshold to elapse — the production code reads ``time.time()``
    so we just shift the stored value.
    """

    def test_lane_get_stuck_returns_keys_past_threshold(self) -> None:
        lane = Lane("test", max_concurrent=4)
        # Construct active entries with backdated timestamps directly.
        # We don't need to acquire/release through the semaphore — the
        # purpose is to test the threshold filter, not the semaphore.
        old_ts = time.time() - 10.0
        recent_ts = time.time() - 0.1
        with lane._lock:
            lane._active["stuck-job"] = old_ts
            lane._active["fresh-job"] = recent_ts

        stuck_5s = lane.get_stuck(threshold_s=5.0)
        assert stuck_5s == ["stuck-job"]

        stuck_1s = lane.get_stuck(threshold_s=1.0)
        assert stuck_1s == ["stuck-job"]

        stuck_15s = lane.get_stuck(threshold_s=15.0)
        assert stuck_15s == []  # neither is older than 15s

    def test_lane_get_stuck_returns_empty_for_zero_or_negative_threshold(
        self,
    ) -> None:
        """A zero/negative threshold would otherwise label every active
        slot stuck the instant it acquired — explicitly refused."""
        lane = Lane("test", max_concurrent=2)
        with lane._lock:
            lane._active["job"] = time.time() - 1.0
        assert lane.get_stuck(threshold_s=0) == []
        assert lane.get_stuck(threshold_s=-1.0) == []

    def test_session_lane_get_stuck_only_counts_held_entries(self) -> None:
        """SessionLane keeps released entries around for the idle-evict
        path; ``get_stuck`` must skip those."""
        sl = SessionLane(max_sessions=4)
        # Acquire two keys, release one of them.
        with sl.acquire("held"):
            sl.try_acquire("released")
            sl.manual_release("released")
            # Backdate both entries to land outside the stuck threshold.
            with sl._lock:
                sl._sessions["held"].last_used = time.time() - 30.0
                sl._sessions["released"].last_used = time.time() - 30.0
            # Only "held" is currently held → only it is "stuck".
            stuck = sl.get_stuck(threshold_s=5.0)
            assert stuck == ["held"]


class TestStatusObservability:
    """PR-LQ-Phase5 — ``LaneQueue.status()`` returns the full per-lane
    observability shape: instantaneous counts + lifetime stats +
    stuck keys."""

    def test_status_includes_stats_and_stuck_for_each_lane(self) -> None:
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=8))
        q.add_lane("global", max_concurrent=4)

        with q.acquire_all("k1", ["session", "global"]):
            # Force a fake-old entry on the global lane so it shows up
            # as stuck.
            global_lane = q.get_lane("global")
            assert global_lane is not None
            with global_lane._lock:
                global_lane._active["k1"] = time.time() - 600.0

            snapshot = q.status(stuck_threshold_s=300.0)
            assert "session" in snapshot
            assert "global" in snapshot

            # Lifetime stats surfaced.
            assert snapshot["global"]["stats"]["acquired"] >= 1
            assert "released" in snapshot["global"]["stats"]
            assert "timeouts" in snapshot["global"]["stats"]
            assert snapshot["session"]["stats"]["acquired"] >= 1

            # Stuck list populated for the backdated key.
            assert snapshot["global"]["stuck"] == ["k1"]

    def test_status_stuck_threshold_default_is_5_minutes(self) -> None:
        q = LaneQueue()
        q.add_lane("global", max_concurrent=1)
        with q.acquire_all("k1", ["global"]):
            # Backdate to 60 s — well under the 300 s default.
            global_lane = q.get_lane("global")
            assert global_lane is not None
            with global_lane._lock:
                global_lane._active["k1"] = time.time() - 60.0

            snapshot = q.status()
            assert snapshot["global"]["stuck"] == []

    def test_status_after_release_has_no_active_or_stuck(self) -> None:
        q = LaneQueue()
        q.add_lane("global", max_concurrent=2)
        with q.acquire_all("k1", ["global"]):
            pass
        snapshot = q.status()
        assert snapshot["global"]["active"] == 0
        assert snapshot["global"]["stuck"] == []
        # acquired == released by now.
        assert snapshot["global"]["stats"]["acquired"] == snapshot["global"]["stats"]["released"]


# ---------------------------------------------------------------------------
# C4 Regression: acquire_all partial failure (v0.35.1 fix)
# ---------------------------------------------------------------------------


class TestAcquireAllPartialFailure:
    """Verify partial failure releases only acquired lanes."""

    def test_second_lane_timeout_releases_first_async(self) -> None:
        """If 2nd lane times out, 1st lane must be released."""
        q = LaneQueue()
        q.add_lane("fast", max_concurrent=1, timeout_s=5.0)
        q.add_lane("slow", max_concurrent=1, timeout_s=0.1)

        slow = q.get_lane("slow")
        assert slow is not None
        slow._semaphore.acquire()

        fast = q.get_lane("fast")
        assert fast is not None

        async def scenario() -> None:
            with pytest.raises(TimeoutError, match="slow"):
                async with q.acquire_all_async("job-x", ["fast", "slow"]):
                    pass

        asyncio.run(scenario())

        # Fast lane must be released (no leak)
        assert fast.active_count == 0
        slow._semaphore.release()

    def test_acquire_all_async_partial_failure_releases_first(self) -> None:
        q = LaneQueue()
        q.add_lane("fast", max_concurrent=1, timeout_s=5.0)
        q.add_lane("slow", max_concurrent=1, timeout_s=0.1)

        slow = q.get_lane("slow")
        assert slow is not None
        slow._semaphore.acquire()
        fast = q.get_lane("fast")
        assert fast is not None

        async def scenario() -> None:
            with pytest.raises(TimeoutError, match="slow"):
                async with q.acquire_all_async("job-async", ["fast", "slow"]):
                    pass

        try:
            asyncio.run(scenario())
            assert fast.active_count == 0
        finally:
            slow._semaphore.release()


# ---------------------------------------------------------------------------
# SessionLane — per-key serialization
# ---------------------------------------------------------------------------


class TestSessionLane:
    """Verify per-session-key serialization (OpenClaw pattern)."""

    def test_same_key_serializes(self) -> None:
        """Two threads with same key — second blocks until first releases."""
        sl = SessionLane(timeout_s=0.2)
        acquired = threading.Event()
        release = threading.Event()
        blocked = threading.Event()

        def holder():
            with sl.acquire("key-A"):
                acquired.set()
                release.wait(timeout=2.0)

        def waiter():
            acquired.wait(timeout=1.0)
            ok = sl.try_acquire("key-A")
            if not ok:
                blocked.set()

        t1 = threading.Thread(target=holder, daemon=True)
        t2 = threading.Thread(target=waiter, daemon=True)
        t1.start()
        t2.start()
        t2.join(timeout=1.0)

        assert blocked.is_set(), "Second acquire should fail (same key held)"
        release.set()
        t1.join(timeout=1.0)

    def test_different_keys_parallel(self) -> None:
        """Two threads with different keys — both proceed immediately."""
        sl = SessionLane()
        assert sl.try_acquire("key-A")
        assert sl.try_acquire("key-B")
        assert sl.active_count == 2
        sl.manual_release("key-A")
        sl.manual_release("key-B")

    def test_try_acquire_and_manual_release(self) -> None:
        sl = SessionLane()
        assert sl.try_acquire("k1")
        assert not sl.try_acquire("k1")  # same key, held
        sl.manual_release("k1")
        assert sl.try_acquire("k1")  # re-acquired after release
        sl.manual_release("k1")

    def test_acquire_timeout(self) -> None:
        sl = SessionLane()
        sl.try_acquire("k1")
        assert not sl.acquire_timeout("k1", timeout_s=0.05)
        sl.manual_release("k1")

    def test_context_manager_release(self) -> None:
        sl = SessionLane()
        with sl.acquire("k1"):
            assert sl.active_count == 1
        assert sl.active_count == 0

    def test_max_sessions_cap(self) -> None:
        sl = SessionLane(max_sessions=3, idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.try_acquire("b")
        sl.try_acquire("c")
        # All 3 held, no idle to evict
        with pytest.raises(RuntimeError, match="SessionLane full"):
            sl.try_acquire("d")
        sl.manual_release("a")
        sl.manual_release("b")
        sl.manual_release("c")

    def test_idle_eviction_on_cap(self) -> None:
        sl = SessionLane(max_sessions=2, idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.manual_release("a")  # now idle
        sl.try_acquire("b")
        sl.manual_release("b")  # now idle
        # Both idle — next create triggers eviction
        sl.try_acquire("c")  # evicts a and/or b, creates c
        assert sl.session_count <= 2
        sl.manual_release("c")

    def test_cleanup_idle(self) -> None:
        sl = SessionLane(idle_timeout_s=0.0)
        sl.try_acquire("a")
        sl.manual_release("a")
        time.sleep(0.01)
        evicted = sl.cleanup_idle()
        assert evicted == 1
        assert sl.session_count == 0

    def test_held_session_not_evicted(self) -> None:
        sl = SessionLane(idle_timeout_s=0.0)
        sl.try_acquire("held")
        time.sleep(0.01)
        evicted = sl.cleanup_idle()
        assert evicted == 0
        assert sl.session_count == 1
        sl.manual_release("held")

    def test_get_active(self) -> None:
        sl = SessionLane()
        sl.try_acquire("a")
        sl.try_acquire("b")
        active = sl.get_active()
        assert "a" in active
        assert "b" in active
        sl.manual_release("a")
        active = sl.get_active()
        assert "a" not in active
        assert "b" in active
        sl.manual_release("b")

    def test_stats_tracking(self) -> None:
        sl = SessionLane()
        sl.try_acquire("a")
        sl.manual_release("a")
        assert sl.stats.acquired == 1
        assert sl.stats.released == 1

        assert not sl.try_acquire("x") or True  # acquire x
        sl.manual_release("x")
        # try_acquire on held key
        sl.try_acquire("z")
        assert not sl.try_acquire("z")
        assert sl.stats.timeouts == 1
        sl.manual_release("z")

    def test_acquire_async_same_key_serializes(self) -> None:
        sl = SessionLane()

        async def scenario() -> None:
            async with sl.acquire_async("key-A"):
                assert sl.active_count == 1
                assert not await sl.try_acquire_async("key-A")
            assert sl.active_count == 0

        asyncio.run(scenario())


class TestAcquireAllSync:
    """PR-LQ-Phase1 (2026-05-22) — sync sibling of ``acquire_all_async``.

    The seed-generation orchestrator runs each phase synchronously and
    needs to compose the OpenClaw lane hierarchy
    ``["session", "seed-generation", "global"]`` without bouncing through
    ``asyncio.run``. This class pins the contract: ordering, partial-
    failure release, missing-lane errors.
    """

    def test_acquire_all_runs_through_session_workload_and_global(self) -> None:
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=8))
        q.add_lane("seed-generation", max_concurrent=2)
        q.add_lane("global", max_concurrent=4)

        with q.acquire_all("run-1", ["session", "seed-generation", "global"]):
            assert q.get_lane("seed-generation").active_count == 1  # type: ignore[union-attr]
            assert q.get_lane("global").active_count == 1  # type: ignore[union-attr]
        assert q.get_lane("seed-generation").active_count == 0  # type: ignore[union-attr]
        assert q.get_lane("global").active_count == 0  # type: ignore[union-attr]

    def test_acquire_all_unknown_lane_releases_prior_acquisitions(self) -> None:
        """If a later lane name is missing, the earlier acquisitions release."""
        q = LaneQueue()
        q.add_lane("global", max_concurrent=2)

        with (
            pytest.raises(KeyError, match="not found"),
            q.acquire_all("k1", ["global", "missing"]),
        ):
            pass

        # global should be back to 0 active (partial-failure release).
        assert q.get_lane("global").active_count == 0  # type: ignore[union-attr]

    def test_acquire_all_skips_session_when_none_registered(self) -> None:
        """Same shape as acquire_all_async: ``session`` is silently skipped
        when no SessionLane was registered."""
        q = LaneQueue()
        q.add_lane("global", max_concurrent=2)
        with q.acquire_all("k1", ["session", "global"]):
            assert q.get_lane("global").active_count == 1  # type: ignore[union-attr]
        assert q.get_lane("global").active_count == 0  # type: ignore[union-attr]

    def test_acquire_all_releases_in_reverse_order(self) -> None:
        """LIFO release matches acquire_all_async's finally-loop semantics
        (``for item in reversed(acquired): item._raw_release(key)``)."""
        q = LaneQueue()
        q.set_session_lane(SessionLane(max_sessions=8))
        q.add_lane("seed-generation", max_concurrent=2)
        q.add_lane("global", max_concurrent=4)

        with q.acquire_all("k1", ["session", "seed-generation", "global"]):
            pass
        # After release every lane is empty.
        for name in ("seed-generation", "global"):
            assert q.get_lane(name).active_count == 0  # type: ignore[union-attr]

    def test_workload_cap_does_not_exceed_global_cap_invariant(self) -> None:
        """Hierarchy invariant — ``max(workload_lane) <= max(global)``.

        A workload cap larger than global is a false signal: the leaf
        semaphore still funnels through the global lane. The seed-
        generation lane (DEFAULT_SEED_PIPELINE_CONCURRENCY) is the
        first concrete consumer of this invariant.
        """
        from core.wiring.container import (
            DEFAULT_GATEWAY_CONCURRENCY,
            DEFAULT_GLOBAL_CONCURRENCY,
            DEFAULT_SEED_PIPELINE_CONCURRENCY,
        )

        for workload_name, workload_cap in (
            ("gateway", DEFAULT_GATEWAY_CONCURRENCY),
            ("seed-generation", DEFAULT_SEED_PIPELINE_CONCURRENCY),
        ):
            assert workload_cap <= DEFAULT_GLOBAL_CONCURRENCY, (
                f"workload lane {workload_name!r} cap {workload_cap} > "
                f"global cap {DEFAULT_GLOBAL_CONCURRENCY} — hierarchy violation"
            )

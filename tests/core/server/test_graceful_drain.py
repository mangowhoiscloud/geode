"""Tests for graceful serve drain — SIGTERM → active session completion wait."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.llm.loop_affinity import LoopAffineClientCache
from core.orchestration.lane_queue import Lane, SessionLane
from core.server.ipc_server.poller import CLIPoller


class TestGracefulDrainLogic:
    """Test the drain polling logic used by serve shutdown."""

    def test_drain_completes_when_no_active(self):
        """Drain loop exits immediately when no sessions are active."""
        sl = SessionLane(max_sessions=10)
        assert sl.active_count == 0

        # Simulate drain loop
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.1)
        assert sl.active_count == 0

    def test_drain_waits_for_active_session(self):
        """Drain loop waits until active session releases."""
        sl = SessionLane(max_sessions=10)
        released = threading.Event()

        def _hold_session():
            with sl.acquire("test-session"):
                time.sleep(0.3)
            released.set()

        t = threading.Thread(target=_hold_session)
        t.start()
        time.sleep(0.05)  # let thread acquire

        assert sl.active_count == 1

        # Drain loop
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.1)

        assert sl.active_count == 0
        assert released.is_set()
        t.join()

    def test_drain_timeout_with_stuck_session(self):
        """Drain loop respects timeout when session is stuck."""
        sl = SessionLane(max_sessions=10)
        stop = threading.Event()

        def _hold_forever():
            with sl.acquire("stuck-session"):
                stop.wait()  # hold until test says stop

        t = threading.Thread(target=_hold_forever, daemon=True)
        t.start()
        time.sleep(0.05)

        assert sl.active_count == 1

        # Drain with short timeout
        drain_timeout = 0.3
        deadline = time.monotonic() + drain_timeout
        timed_out = True
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                timed_out = False
                break
            time.sleep(0.05)

        assert timed_out
        assert sl.active_count == 1

        # Cleanup
        stop.set()
        t.join(timeout=2.0)

    def test_global_lane_active_count(self):
        """Lane.active_count reflects held slots."""
        lane = Lane("test", max_concurrent=4)
        assert lane.active_count == 0

        acquired = threading.Event()
        release = threading.Event()

        def _hold():
            with lane.acquire("w1"):
                acquired.set()
                release.wait()

        t = threading.Thread(target=_hold, daemon=True)
        t.start()
        acquired.wait(timeout=2.0)
        assert lane.active_count == 1

        release.set()
        t.join(timeout=2.0)
        assert lane.active_count == 0

    def test_multiple_sessions_drain(self):
        """Drain waits for all concurrent sessions to complete."""
        sl = SessionLane(max_sessions=10)
        threads: list[threading.Thread] = []
        completed = {"count": 0}
        lock = threading.Lock()

        def _hold(key: str, hold_time: float):
            with sl.acquire(key):
                time.sleep(hold_time)
            with lock:
                completed["count"] += 1

        # Start 3 sessions with different hold times
        for i, hold in enumerate([0.1, 0.2, 0.3]):
            t = threading.Thread(target=_hold, args=(f"s{i}", hold))
            t.start()
            threads.append(t)
        time.sleep(0.05)
        assert sl.active_count == 3

        # Drain
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if sl.active_count == 0:
                break
            time.sleep(0.05)

        assert sl.active_count == 0
        assert completed["count"] == 3
        for t in threads:
            t.join()


class TestCLIPollerStopAccepting:
    """Test CLIPoller.stop_accepting() method."""

    def test_stop_accepting_exists(self):
        """CLIPoller has stop_accepting method."""
        from core.server.ipc_server.poller import CLIPoller

        assert hasattr(CLIPoller, "stop_accepting")

    def test_stop_accepting_idempotent(self):
        """Calling stop_accepting on non-started poller does not crash."""
        from unittest.mock import MagicMock

        from core.server.ipc_server.poller import CLIPoller

        services = MagicMock()
        poller = CLIPoller(services)
        # Should not raise
        poller.stop_accepting()
        poller.stop_accepting()  # second call also safe


@pytest.fixture()
def sdk_poller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[CLIPoller, threading.Event, threading.Event, list[BaseException]]]:
    """Own a real IPC worker/SDK drain without opening any socket or provider."""
    release = threading.Event()
    closing = threading.Event()
    failures: list[BaseException] = []
    cache = LoopAffineClientCache("ipc-shutdown-regression")

    class Client:
        async def close(self) -> None:
            closing.set()
            if failures:
                raise failures[0]
            while not release.is_set():
                await asyncio.sleep(0.005)

    poller = CLIPoller(MagicMock(), socket_path=tmp_path / "cli.sock")

    async def serve() -> None:
        cache.get(Client)
        poller._ready_event.set()
        while not poller._stop_event.is_set():
            await asyncio.sleep(0.005)

    monkeypatch.setattr(poller, "_serve_async", serve)
    poller.start()
    thread = poller._thread
    assert thread is not None
    join = thread.join

    def short_join(timeout: float | None = None) -> None:
        assert timeout == 5.0  # Production keeps the existing shutdown deadline.
        join(timeout=0.03 if not release.is_set() and not failures else timeout)

    monkeypatch.setattr(thread, "join", short_join)
    poller.socket_path.touch()  # Ownership marker, not a listening socket.
    try:
        yield poller, release, closing, failures
    finally:
        release.set()
        poller._stop_event.set()
        join(timeout=2)
        assert not thread.is_alive()
        # Failed SDK cleanup remains observable on repeated stop calls.
        with contextlib.suppress(BaseException):
            poller.stop()
        remaining = poller._thread
        if remaining is not None:
            threading.Thread.join(remaining, timeout=2)
            assert not remaining.is_alive()


@pytest.mark.parametrize("operation", ["stop", "stop_accepting"])
def test_ipc_delayed_sdk_close_retains_owner_and_blocks_restart(
    sdk_poller: tuple[CLIPoller, threading.Event, threading.Event, list[BaseException]],
    operation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    poller, release, closing, _ = sdk_poller
    thread = poller._thread
    assert thread is not None
    caplog.set_level(logging.INFO)
    if operation == "stop":
        with pytest.raises(TimeoutError, match="still stopping"):
            poller.stop()
    else:
        poller.stop_accepting()  # Admission can stop before SDK drain finishes.
    assert closing.wait(timeout=2)
    assert poller._thread is thread and thread.is_alive()
    assert poller.socket_path.exists()
    assert "CLI channel stopped" not in [record.message for record in caplog.records]
    with pytest.raises(RuntimeError, match="still stopping"):
        poller.start()
    assert poller._thread is thread

    release.set()
    threading.Thread.join(thread, timeout=2)
    poller.stop()
    poller.stop()
    assert poller._thread is None
    assert not poller.socket_path.exists()
    poller.start()
    assert poller._thread is not thread
    poller.stop()
    assert poller._thread is None


@pytest.mark.parametrize("failure", [ValueError("close failed"), asyncio.CancelledError()])
@pytest.mark.parametrize("admission_first", [False, True])
def test_ipc_sdk_cleanup_failure_reaches_stop_and_serve(
    sdk_poller: tuple[CLIPoller, threading.Event, threading.Event, list[BaseException]],
    failure: BaseException,
    admission_first: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from core.cli.typer_serve import _shutdown_serve_components

    poller, release, closing, failures = sdk_poller
    failures.append(failure)
    release.set()
    caplog.set_level(logging.INFO)
    if admission_first:
        poller.stop_accepting()
    with pytest.raises(BaseExceptionGroup) as caught:
        poller.stop()
    assert caught.value.exceptions == (failure,)
    assert closing.is_set()
    assert poller._thread is None
    assert not poller.socket_path.exists()
    assert "CLI channel stopped" not in [record.message for record in caplog.records]
    runtime, webhook = MagicMock(), MagicMock()
    runtime.shutdown.return_value = True
    assert not _shutdown_serve_components(
        cli_poller=poller,
        webhook_server=webhook,
        runtime=runtime,
        primary_error=RuntimeError("existing host failure"),
    )
    runtime.shutdown.assert_called_once_with()
    webhook.shutdown.assert_called_once_with()


def test_ipc_stop_attempts_siblings_after_first_cleanup_failure(
    sdk_poller: tuple[CLIPoller, threading.Event, threading.Event, list[BaseException]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poller, release, _, _ = sdk_poller
    release.set()
    primary = ValueError("server close failed")
    monkeypatch.setattr(poller, "_close_async_server", MagicMock(side_effect=primary))
    first, second = MagicMock(), MagicMock()
    first.close_threadsafe.side_effect = KeyboardInterrupt("client close failed")
    poller._active_clients.update([first, second])
    with pytest.raises(ValueError) as caught:
        poller.stop()
    assert caught.value is primary
    first.close_threadsafe.assert_called_once_with()
    second.close_threadsafe.assert_called_once_with()
    assert poller._thread is None
    assert not poller.socket_path.exists()


def test_ipc_natural_worker_exit_can_be_stopped_repeatedly(
    sdk_poller: tuple[CLIPoller, threading.Event, threading.Event, list[BaseException]],
) -> None:
    poller, release, closing, _ = sdk_poller
    thread = poller._thread
    assert thread is not None
    release.set()
    poller._stop_event.set()
    threading.Thread.join(thread, timeout=2)
    assert closing.is_set() and not thread.is_alive()
    poller.stop()
    poller.stop_accepting()
    poller.stop()
    assert poller._thread is None


def test_ipc_startup_failure_stays_observable_during_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OSError("fixture startup failure")
    poller = CLIPoller(MagicMock(), socket_path=tmp_path / "cli.sock")

    async def fail() -> None:
        raise failure

    monkeypatch.setattr(poller, "_serve_async", fail)
    try:
        with pytest.raises(RuntimeError, match="startup failed") as caught:
            poller.start()
        assert caught.value.__cause__ is failure
        with pytest.raises(OSError) as stopped:
            poller.stop()
        assert stopped.value is failure
        assert poller._thread is None
    finally:
        thread = poller._thread
        if thread is not None:
            threading.Thread.join(thread, timeout=2)
            assert not thread.is_alive()

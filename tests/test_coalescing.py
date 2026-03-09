"""Tests for CoalescingQueue — request deduplication with debounce."""

from __future__ import annotations

import threading
import time

from geode.orchestration.coalescing import CoalescingQueue


class TestCoalescingQueue:
    def test_single_submit_fires(self):
        results: list[str] = []
        event = threading.Event()

        def callback(key, data):
            results.append(key)
            event.set()

        q = CoalescingQueue(window_ms=50)
        q.submit("key1", callback)
        event.wait(timeout=1.0)

        assert results == ["key1"]
        assert q.stats.submitted == 1
        assert q.stats.executed == 1
        assert q.stats.coalesced == 0

    def test_duplicate_submits_coalesce(self):
        results: list[str] = []
        event = threading.Event()

        def callback(key, data):
            results.append(key)
            event.set()

        q = CoalescingQueue(window_ms=100)
        q.submit("key1", callback)
        q.submit("key1", callback)
        q.submit("key1", callback)
        event.wait(timeout=1.0)
        # Small extra wait for any straggling timers
        time.sleep(0.05)

        assert len(results) == 1  # Coalesced to single execution
        assert q.stats.submitted == 3
        assert q.stats.coalesced == 2
        assert q.stats.executed == 1

    def test_different_keys_independent(self):
        results: list[str] = []
        event = threading.Event()

        def callback(key, data):
            results.append(key)
            if len(results) >= 2:
                event.set()

        q = CoalescingQueue(window_ms=50)
        q.submit("key1", callback)
        q.submit("key2", callback)
        event.wait(timeout=1.0)

        assert sorted(results) == ["key1", "key2"]

    def test_cancel(self):
        results: list[str] = []

        def callback(key, data):
            results.append(key)

        q = CoalescingQueue(window_ms=200)
        q.submit("key1", callback)
        cancelled = q.cancel("key1")

        assert cancelled is True
        time.sleep(0.3)
        assert results == []

    def test_cancel_nonexistent(self):
        q = CoalescingQueue()
        assert q.cancel("nope") is False

    def test_cancel_all(self):
        q = CoalescingQueue(window_ms=500)
        q.submit("a", lambda k, d: None)
        q.submit("b", lambda k, d: None)
        count = q.cancel_all()
        assert count == 2
        assert q.pending_count == 0

    def test_pending_count(self):
        q = CoalescingQueue(window_ms=500)
        assert q.pending_count == 0
        q.submit("a", lambda k, d: None)
        assert q.pending_count == 1
        q.cancel_all()

    def test_data_passed_to_callback(self):
        received: list = []
        event = threading.Event()

        def callback(key, data):
            received.append((key, data))
            event.set()

        q = CoalescingQueue(window_ms=50)
        q.submit("key1", callback, {"ip": "Berserk"})
        event.wait(timeout=1.0)

        assert received == [("key1", {"ip": "Berserk"})]

    def test_callback_error_tracked(self):
        event = threading.Event()

        def bad_callback(key, data):
            event.set()
            raise ValueError("boom")

        q = CoalescingQueue(window_ms=50)
        q.submit("key1", bad_callback)
        event.wait(timeout=1.0)
        time.sleep(0.05)

        assert q.stats.errors == 1

    def test_stats_to_dict(self):
        q = CoalescingQueue()
        d = q.stats.to_dict()
        assert set(d.keys()) == {"submitted", "coalesced", "executed", "errors"}

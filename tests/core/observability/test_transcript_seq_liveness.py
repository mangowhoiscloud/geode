"""PR-COMM-4 — transcript seq + liveness watchdog tests.

Pins two coupled invariants:

1. ``SessionTranscript._append`` + ``record_lifecycle_event`` stamp a
   per-instance monotonic ``seq`` on every JSONL row so multi-event
   timelines can be sorted deterministically even when ``ts`` ties
   (sub-second clock drift / NTP reset).
2. ``SessionTranscript.last_touched_at`` + ``is_stale`` expose the
   transcript file's mtime so external watchdogs can spot runs that
   hung without firing any hook event.

``RunTranscript`` (self_improving_loop) gets the same liveness
passthrough so seed-generation operators can poll
``run_transcript.is_stale(900)`` without poking inside the underlying
SessionTranscript.

Coverage map:

* :class:`TestSeqMonotonic` — seq starts at 1 and increments by 1 per
  event for both ``_append`` and ``record_lifecycle_event``.
* :class:`TestLastTouchedAt` — file mtime probed; None when file
  doesn't exist; OSError → None (defensive).
* :class:`TestIsStale` — threshold comparison; never-started run is
  not stale; injectable ``now`` for determinism.
* :class:`TestRunTranscriptLiveness` — passthrough from RunTranscript
  delegates to its own ``path`` (NOT the wrapped SessionTranscript's
  default file_path).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.observability.transcript import SessionTranscript
from core.self_improving.loop.observe.run_transcript import RunTranscript


class TestSeqMonotonic:
    def test_record_session_start_lands_seq_1(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-1", transcript_dir=tmp_path)
        tx.record_session_start(model="x")
        row = json.loads((tmp_path / "s-1.jsonl").read_text().splitlines()[0])
        assert row["seq"] == 1

    def test_consecutive_appends_increment(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-2", transcript_dir=tmp_path)
        tx.record_session_start(model="x")
        tx.record_user_message("hi")
        tx.record_assistant_message("hello")
        seqs = [
            json.loads(line)["seq"] for line in (tmp_path / "s-2.jsonl").read_text().splitlines()
        ]
        assert seqs == [1, 2, 3]

    def test_record_lifecycle_event_also_stamps_seq(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-3", transcript_dir=tmp_path)
        tx.record_lifecycle_event(event="phase_started", payload={"phase": "init"})
        tx.record_lifecycle_event(event="phase_finished", payload={"phase": "init"})
        seqs = [
            json.loads(line)["seq"] for line in (tmp_path / "s-3.jsonl").read_text().splitlines()
        ]
        assert seqs == [1, 2]

    def test_seq_holds_under_concurrent_threads(self, tmp_path: Path) -> None:
        """Codex MCP review catch: pre-fix the seq stamp lock was
        released before the write lock was re-acquired, so two threads
        could allocate seqs N+1 / N+2 and then write in the opposite
        order. With the unified lock, seq order ALWAYS matches file
        write order. 100 concurrent appends from 10 threads must
        produce 100 rows with seqs 1..100 in file order."""
        import threading

        tx = SessionTranscript("s-concurrent", transcript_dir=tmp_path)

        def _do_appends() -> None:
            for _ in range(10):
                tx.record_user_message("x")

        threads = [threading.Thread(target=_do_appends) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        seqs = [
            json.loads(line)["seq"]
            for line in (tmp_path / "s-concurrent.jsonl").read_text().splitlines()
        ]
        assert seqs == list(range(1, 101)), (
            f"seq order broken — first 10: {seqs[:10]}, last 10: {seqs[-10:]}"
        )

    def test_seq_independent_across_instances(self, tmp_path: Path) -> None:
        """Per-instance counter — two SessionTranscripts writing to
        different files each start at 1. Cross-process writers to the
        SAME file are documented to produce interleaved seqs; readers
        must re-sort by (ts, seq)."""
        tx_a = SessionTranscript("s-a", transcript_dir=tmp_path / "a")
        tx_b = SessionTranscript("s-b", transcript_dir=tmp_path / "b")
        tx_a.record_session_start(model="x")
        tx_b.record_session_start(model="x")
        tx_a.record_user_message("hi")
        seq_a = [
            json.loads(line)["seq"]
            for line in (tmp_path / "a" / "s-a.jsonl").read_text().splitlines()
        ]
        seq_b = [
            json.loads(line)["seq"]
            for line in (tmp_path / "b" / "s-b.jsonl").read_text().splitlines()
        ]
        assert seq_a == [1, 2]
        assert seq_b == [1]


class TestLastTouchedAt:
    def test_none_when_file_missing(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-never", transcript_dir=tmp_path)
        # No event recorded — file doesn't exist yet.
        assert tx.last_touched_at() is None

    def test_returns_mtime_after_write(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-touched", transcript_dir=tmp_path)
        before = time.time()
        tx.record_session_start(model="x")
        touched = tx.last_touched_at()
        assert touched is not None
        # mtime should be ≥ wall clock at write time (within 5s slack
        # for filesystem timestamp granularity on noisy CI runners).
        assert touched >= before - 1.0


class TestIsStale:
    def test_never_started_run_is_not_stale(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-fresh", transcript_dir=tmp_path)
        # File doesn't exist yet — a never-started run isn't "stale",
        # it just hasn't begun. Distinguishes "hung" from "not yet run".
        assert tx.is_stale(threshold_s=60.0) is False

    def test_recent_write_not_stale(self, tmp_path: Path) -> None:
        tx = SessionTranscript("s-recent", transcript_dir=tmp_path)
        tx.record_session_start(model="x")
        assert tx.is_stale(threshold_s=60.0) is False

    def test_old_write_is_stale_with_injected_now(self, tmp_path: Path) -> None:
        """Deterministic test using injectable ``now`` — actual wall
        clock drift doesn't affect the assertion."""
        tx = SessionTranscript("s-old", transcript_dir=tmp_path)
        tx.record_session_start(model="x")
        touched = tx.last_touched_at()
        assert touched is not None
        # Simulate "now" being 1000s later than the file mtime
        future = touched + 1000.0
        assert tx.is_stale(threshold_s=500.0, now=future) is True
        assert tx.is_stale(threshold_s=2000.0, now=future) is False


class TestRunTranscriptLiveness:
    def test_run_transcript_last_touched_after_append(self, tmp_path: Path) -> None:
        rt = RunTranscript(
            session_id="run-live",
            gen_tag="gen-1",
            component="autoresearch",
            path=tmp_path / "transcript.jsonl",
        )
        before = time.time()
        rt.append("phase_started", payload={"phase": "x"})
        touched = rt.last_touched_at()
        assert touched is not None
        assert touched >= before - 1.0

    def test_run_transcript_is_stale_with_injected_now(self, tmp_path: Path) -> None:
        rt = RunTranscript(
            session_id="run-stale",
            gen_tag="gen-1",
            component="autoresearch",
            path=tmp_path / "transcript.jsonl",
        )
        rt.append("phase_started")
        touched = rt.last_touched_at()
        assert touched is not None
        assert rt.is_stale(threshold_s=100.0, now=touched + 200.0) is True
        assert rt.is_stale(threshold_s=300.0, now=touched + 200.0) is False

    def test_run_transcript_never_started_is_not_stale(self, tmp_path: Path) -> None:
        rt = RunTranscript(
            session_id="run-never",
            gen_tag="gen-1",
            component="autoresearch",
            path=tmp_path / "transcript.jsonl",
        )
        assert rt.is_stale(threshold_s=10.0) is False

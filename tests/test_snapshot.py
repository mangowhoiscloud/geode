"""Tests for L4.5 Snapshot Manager (Peekaboo)."""

from pathlib import Path

import pytest

from geode.automation.snapshot import Snapshot, SnapshotManager


class TestSnapshot:
    def test_to_dict(self):
        s = Snapshot(
            snapshot_id="snap-001",
            session_id="sess-1",
            pipeline_state={"tier": "S"},
        )
        d = s.to_dict()
        assert d["snapshot_id"] == "snap-001"
        assert d["pipeline_state"]["tier"] == "S"

    def test_from_dict(self):
        d = {
            "snapshot_id": "snap-001",
            "session_id": "sess-1",
            "pipeline_state": {"score": 82.2},
            "created_at": 1000.0,
        }
        s = Snapshot.from_dict(d)
        assert s.snapshot_id == "snap-001"
        assert s.pipeline_state["score"] == 82.2

    def test_round_trip(self):
        s = Snapshot(
            snapshot_id="snap-x",
            session_id="s1",
            prompt_hash="abc",
            rubric_hash="def",
            config_hash="ghi",
            pipeline_state={"a": 1},
            context={"b": 2},
        )
        s2 = Snapshot.from_dict(s.to_dict())
        assert s2.snapshot_id == s.snapshot_id
        assert s2.prompt_hash == "abc"


class TestSnapshotManager:
    def test_capture(self):
        mgr = SnapshotManager()
        snap = mgr.capture("sess-1", pipeline_state={"tier": "S"})
        assert snap.session_id == "sess-1"
        assert snap.pipeline_state["tier"] == "S"

    def test_restore(self):
        mgr = SnapshotManager()
        snap = mgr.capture("sess-1", pipeline_state={"score": 82})
        restored = mgr.restore(snap.snapshot_id)
        assert restored.pipeline_state["score"] == 82

    def test_restore_not_found(self):
        mgr = SnapshotManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.restore("snap-nonexistent")

    def test_list_snapshots(self):
        mgr = SnapshotManager()
        mgr.capture("s1", pipeline_state={"a": 1})
        mgr.capture("s1", pipeline_state={"a": 2})
        mgr.capture("s2", pipeline_state={"b": 1})
        all_snaps = mgr.list_snapshots()
        assert len(all_snaps) == 3

    def test_list_snapshots_by_session(self):
        mgr = SnapshotManager()
        mgr.capture("s1")
        mgr.capture("s2")
        assert len(mgr.list_snapshots(session_id="s1")) == 1

    def test_list_snapshots_newest_first(self):
        mgr = SnapshotManager()
        mgr.capture("s1")
        mgr.capture("s1")
        snaps = mgr.list_snapshots()
        assert snaps[0].created_at >= snaps[1].created_at

    def test_delete(self):
        mgr = SnapshotManager()
        snap = mgr.capture("s1")
        assert mgr.delete(snap.snapshot_id) is True
        assert mgr.delete(snap.snapshot_id) is False

    def test_prune_keeps_max_recent(self):
        mgr = SnapshotManager(max_recent=3)
        for i in range(10):
            mgr.capture("s1", pipeline_state={"i": i})
        pruned = mgr.prune()
        assert pruned > 0
        remaining = mgr.list_snapshots()
        assert len(remaining) >= 3

    def test_file_persistence(self, tmp_path: Path):
        mgr = SnapshotManager(storage_dir=tmp_path / "snaps")
        snap = mgr.capture("s1", pipeline_state={"x": 42})

        # Reload
        mgr2 = SnapshotManager(storage_dir=tmp_path / "snaps")
        restored = mgr2.restore(snap.snapshot_id)
        assert restored.pipeline_state["x"] == 42

    def test_capture_with_hashes(self):
        mgr = SnapshotManager()
        snap = mgr.capture(
            "s1",
            prompt_hash="p1",
            rubric_hash="r1",
            config_hash="c1",
        )
        assert snap.prompt_hash == "p1"
        assert snap.rubric_hash == "r1"
        assert snap.config_hash == "c1"

    def test_thread_safety_concurrent_captures(self):
        """Concurrent captures should not corrupt internal state."""
        import threading

        mgr = SnapshotManager()
        errors: list[str] = []

        def _capture(session: str, count: int) -> None:
            try:
                for _ in range(count):
                    mgr.capture(session)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_capture, args=(f"s{i}", 10)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(mgr.list_snapshots()) == 40  # 4 threads × 10 captures

    def test_prune_no_op_when_under_limit(self):
        mgr = SnapshotManager(max_recent=100)
        mgr.capture("s1")
        assert mgr.prune() == 0

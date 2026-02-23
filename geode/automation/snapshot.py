"""Snapshot Manager (Peekaboo) — capture and restore pipeline state snapshots.

Provides point-in-time snapshots of pipeline state for debugging,
rollback, and reproducibility. File-based JSON persistence.

Architecture-v6 §4.5: Automation Layer — Snapshot Manager.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from geode.orchestration.hooks import HookSystem

log = logging.getLogger(__name__)

DEFAULT_MAX_RECENT = 30
DEFAULT_PRUNE_KEEP_WEEKLY = True


@dataclass
class Snapshot:
    """A point-in-time pipeline state snapshot."""

    snapshot_id: str
    session_id: str
    prompt_hash: str = ""
    rubric_hash: str = ""
    config_hash: str = ""
    pipeline_state: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "prompt_hash": self.prompt_hash,
            "rubric_hash": self.rubric_hash,
            "config_hash": self.config_hash,
            "pipeline_state": self.pipeline_state,
            "context": self.context,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Snapshot:
        return cls(
            snapshot_id=d["snapshot_id"],
            session_id=d["session_id"],
            prompt_hash=d.get("prompt_hash", ""),
            rubric_hash=d.get("rubric_hash", ""),
            config_hash=d.get("config_hash", ""),
            pipeline_state=d.get("pipeline_state", {}),
            context=d.get("context", {}),
            created_at=d.get("created_at", 0.0),
        )


class SnapshotManager:
    """Capture and restore pipeline state snapshots.

    Usage:
        mgr = SnapshotManager(storage_dir=Path("/tmp/snapshots"))
        snap = mgr.capture("session-1", state={"tier": "S", "score": 82.2})
        restored = mgr.restore(snap.snapshot_id)
    """

    def __init__(
        self,
        storage_dir: Path | None = None,
        max_recent: int = DEFAULT_MAX_RECENT,
        hooks: HookSystem | None = None,
    ) -> None:
        self._storage_dir = storage_dir
        self._max_recent = max_recent
        self._hooks = hooks
        self._lock = threading.Lock()
        self._snapshots: dict[str, Snapshot] = {}

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def capture(
        self,
        session_id: str,
        *,
        pipeline_state: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        prompt_hash: str = "",
        rubric_hash: str = "",
        config_hash: str = "",
    ) -> Snapshot:
        """Capture a new snapshot."""
        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
        snap = Snapshot(
            snapshot_id=snapshot_id,
            session_id=session_id,
            prompt_hash=prompt_hash,
            rubric_hash=rubric_hash,
            config_hash=config_hash,
            pipeline_state=pipeline_state or {},
            context=context or {},
        )
        with self._lock:
            self._snapshots[snapshot_id] = snap
            self._persist_snapshot(snap)

        if self._hooks:
            from geode.orchestration.hooks import HookEvent

            self._hooks.trigger(HookEvent.SNAPSHOT_CAPTURED, {
                "snapshot_id": snapshot_id,
                "session_id": session_id,
            })

        log.info("Captured snapshot %s for session %s", snapshot_id, session_id)
        return snap

    def restore(self, snapshot_id: str) -> Snapshot:
        """Restore a snapshot by ID.

        Returns the Snapshot. Raises KeyError if not found.
        """
        with self._lock:
            snap = self._snapshots.get(snapshot_id)
        if snap is None:
            raise KeyError(f"Snapshot '{snapshot_id}' not found")
        log.info("Restored snapshot %s", snapshot_id)
        return snap

    def list_snapshots(
        self,
        session_id: str | None = None,
    ) -> list[Snapshot]:
        """List all snapshots, optionally filtered by session. Newest first."""
        with self._lock:
            snaps = list(self._snapshots.values())
        if session_id:
            snaps = [s for s in snaps if s.session_id == session_id]
        return sorted(snaps, key=lambda s: s.created_at, reverse=True)

    def prune(self, max_recent: int | None = None) -> int:
        """Prune old snapshots, keeping max_recent most recent + weekly snapshots.

        Returns number of pruned snapshots.
        """
        with self._lock:
            limit = max_recent or self._max_recent
            all_snaps = sorted(
                self._snapshots.values(), key=lambda s: s.created_at, reverse=True,
            )

            if len(all_snaps) <= limit:
                return 0

            # Keep the most recent ones
            keep = set()
            for snap in all_snaps[:limit]:
                keep.add(snap.snapshot_id)

            # Keep weekly snapshots (one per 7-day period)
            seen_weeks: set[int] = set()
            for snap in all_snaps:
                week = int(snap.created_at // (7 * 86400))
                if week not in seen_weeks:
                    keep.add(snap.snapshot_id)
                    seen_weeks.add(week)

            # Remove the rest
            to_remove = [sid for sid in self._snapshots if sid not in keep]
            for sid in to_remove:
                del self._snapshots[sid]
                self._remove_from_disk(sid)

        log.info("Pruned %d snapshots (kept %d)", len(to_remove), len(keep))
        return len(to_remove)

    def delete(self, snapshot_id: str) -> bool:
        """Delete a specific snapshot. Returns True if found."""
        with self._lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]
                self._remove_from_disk(snapshot_id)
                return True
        return False

    def _persist_snapshot(self, snap: Snapshot) -> None:
        """Write snapshot to disk."""
        if not self._storage_dir:
            return
        f = self._storage_dir / f"{snap.snapshot_id}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap.to_dict(), indent=2), encoding="utf-8")
        os.replace(str(tmp), str(f))

    def _remove_from_disk(self, snapshot_id: str) -> None:
        """Remove snapshot file from disk."""
        if not self._storage_dir:
            return
        f = self._storage_dir / f"{snapshot_id}.json"
        if f.exists():
            f.unlink()

    def _load_from_disk(self) -> None:
        """Load all snapshots from disk."""
        if not self._storage_dir:
            return
        for f in self._storage_dir.glob("snap-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snap = Snapshot.from_dict(data)
                self._snapshots[snap.snapshot_id] = snap
            except (json.JSONDecodeError, KeyError, OSError) as e:
                log.warning("Failed to load snapshot %s: %s", f.name, e)

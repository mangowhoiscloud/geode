"""InMemory Session Store — dict-based with TTL support.

Layer 2 memory component for storing ephemeral session data
(analysis context, user preferences, intermediate results).

Supports optional file-backed persistence so session data
survives process restarts.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class SessionEntry:
    """A single session entry with creation time for TTL."""

    data: dict[str, Any]
    created_at: float = field(default_factory=time.time)


class InMemorySessionStore:
    """Dict-based session store with TTL (seconds).

    If ``storage_dir`` is provided, sessions are persisted to JSON files
    and restored on startup, surviving process restarts.

    Usage:
        store = InMemorySessionStore(ttl=3600)  # 1 hour
        store.set("session-1", {"ip_name": "Berserk", "mode": "full_pipeline"})
        data = store.get("session-1")  # {"ip_name": "Berserk", ...}
    """

    def __init__(
        self,
        ttl: float = 3600.0,
        storage_dir: Path | None = None,
    ) -> None:
        self._store: dict[str, SessionEntry] = {}
        self._ttl = ttl
        self._storage_dir = storage_dir

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    @property
    def ttl(self) -> float:
        return self._ttl

    def set(self, session_id: str, data: dict[str, Any]) -> None:
        """Store or update session data."""
        self._store[session_id] = SessionEntry(data=data)
        self._persist(session_id)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data. Returns None if expired or missing."""
        entry = self._store.get(session_id)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            del self._store[session_id]
            self._remove_from_disk(session_id)
            return None
        return entry.data

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        existed = self._store.pop(session_id, None) is not None
        if existed:
            self._remove_from_disk(session_id)
        return existed

    def exists(self, session_id: str) -> bool:
        """Check if session exists and is not expired."""
        return self.get(session_id) is not None

    def clear(self) -> None:
        """Remove all sessions."""
        if self._storage_dir:
            for f in self._storage_dir.glob("sess-*.json"):
                f.unlink(missing_ok=True)
        self._store.clear()

    def list_sessions(self) -> list[str]:
        """List all non-expired session IDs."""
        self._evict_expired()
        return list(self._store.keys())

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None:
        """Save a checkpoint snapshot for a session."""
        key = f"__checkpoint__:{session_id}"
        self._store[key] = SessionEntry(data=checkpoint_data)
        self._persist(key)

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        """Load the most recent checkpoint for a session. Returns None if missing/expired."""
        key = f"__checkpoint__:{session_id}"
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            del self._store[key]
            self._remove_from_disk(key)
            return None
        return entry.data

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        now = time.time()
        expired = [sid for sid, entry in self._store.items() if now - entry.created_at > self._ttl]
        for sid in expired:
            del self._store[sid]
            self._remove_from_disk(sid)

    # ------------------------------------------------------------------
    # File persistence
    # ------------------------------------------------------------------

    def _safe_filename(self, session_id: str) -> str:
        """Convert session_id to a safe filename.

        Strips all non-alphanumeric chars (except hyphen/underscore) to prevent
        path traversal attacks like '../../etc/passwd'.
        """
        import re

        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
        return f"sess-{safe}.json"

    def _persist(self, session_id: str) -> None:
        """Write a single session entry to disk."""
        if not self._storage_dir:
            return
        entry = self._store.get(session_id)
        if entry is None:
            return
        fpath = self._storage_dir / self._safe_filename(session_id)
        tmp = fpath.with_suffix(".tmp")
        try:
            payload = {
                "session_id": session_id,
                "data": entry.data,
                "created_at": entry.created_at,
            }
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(fpath))
        except (TypeError, ValueError, OSError) as exc:
            log.debug("Failed to persist session %s: %s", session_id, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _remove_from_disk(self, session_id: str) -> None:
        """Remove a session file from disk."""
        if not self._storage_dir:
            return
        fpath = self._storage_dir / self._safe_filename(session_id)
        fpath.unlink(missing_ok=True)

    def _load_from_disk(self) -> None:
        """Load all session files from disk, skipping expired ones."""
        if not self._storage_dir:
            return
        now = time.time()
        loaded = 0
        for fpath in self._storage_dir.glob("sess-*.json"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
                created_at = raw.get("created_at", 0.0)
                if now - created_at > self._ttl:
                    fpath.unlink(missing_ok=True)
                    continue
                sid = raw["session_id"]
                self._store[sid] = SessionEntry(
                    data=raw["data"],
                    created_at=created_at,
                )
                loaded += 1
            except (json.JSONDecodeError, KeyError, OSError) as exc:
                log.warning("Failed to load session file %s: %s", fpath.name, exc)
        if loaded:
            log.info("Restored %d sessions from disk", loaded)

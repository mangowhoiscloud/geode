"""InMemory Session Store — dict-based with TTL support.

Layer 2 memory component for storing ephemeral session data
(analysis context, user preferences, intermediate results).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionEntry:
    """A single session entry with creation time for TTL."""

    data: dict[str, Any]
    created_at: float = field(default_factory=time.time)


class InMemorySessionStore:
    """Dict-based session store with TTL (seconds).

    Usage:
        store = InMemorySessionStore(ttl=3600)  # 1 hour
        store.set("session-1", {"ip_name": "Berserk", "mode": "full_pipeline"})
        data = store.get("session-1")  # {"ip_name": "Berserk", ...}
    """

    def __init__(self, ttl: float = 3600.0) -> None:
        self._store: dict[str, SessionEntry] = {}
        self._ttl = ttl

    @property
    def ttl(self) -> float:
        return self._ttl

    def set(self, session_id: str, data: dict[str, Any]) -> None:
        """Store or update session data."""
        self._store[session_id] = SessionEntry(data=data)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data. Returns None if expired or missing."""
        entry = self._store.get(session_id)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            del self._store[session_id]
            return None
        return entry.data

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        return self._store.pop(session_id, None) is not None

    def exists(self, session_id: str) -> bool:
        """Check if session exists and is not expired."""
        return self.get(session_id) is not None

    def clear(self) -> None:
        """Remove all sessions."""
        self._store.clear()

    def list_sessions(self) -> list[str]:
        """List all non-expired session IDs."""
        self._evict_expired()
        return list(self._store.keys())

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None:
        """Save a checkpoint snapshot for a session."""
        key = f"__checkpoint__:{session_id}"
        self._store[key] = SessionEntry(data=checkpoint_data)

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        """Load the most recent checkpoint for a session. Returns None if missing/expired."""
        key = f"__checkpoint__:{session_id}"
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            del self._store[key]
            return None
        return entry.data

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        now = time.time()
        expired = [sid for sid, entry in self._store.items() if now - entry.created_at > self._ttl]
        for sid in expired:
            del self._store[sid]

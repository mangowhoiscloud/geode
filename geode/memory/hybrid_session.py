"""Hybrid Session Store — multi-tier session storage with fallback.

Implements Redis (simulated), PostgreSQL (file-based), and Hybrid (L1→L2)
session stores following the SessionStorePort protocol.

Architecture-v6 §3 Layer 2: Hybrid Session tier.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geode.infrastructure.ports.memory_port import SessionStorePort

log = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = 4.0
DEFAULT_TTL_SECONDS = DEFAULT_TTL_HOURS * 3600


# ---------------------------------------------------------------------------
# Redis Session Store (in-memory simulation)
# ---------------------------------------------------------------------------


@dataclass
class _RedisEntry:
    """Simulated Redis entry with TTL."""

    data: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = DEFAULT_TTL_SECONDS


class RedisSessionStore:
    """In-memory Redis simulation implementing SessionStorePort.

    Simulates Redis key-value store with TTL expiration.
    """

    def __init__(self, ttl_hours: float = DEFAULT_TTL_HOURS) -> None:
        self._store: dict[str, _RedisEntry] = {}
        self._checkpoints: dict[str, _RedisEntry] = {}
        self._ttl_seconds = ttl_hours * 3600

    def get(self, session_id: str) -> dict[str, Any] | None:
        entry = self._store.get(session_id)
        if entry is None:
            return None
        if time.time() - entry.created_at > entry.ttl_seconds:
            del self._store[session_id]
            return None
        return entry.data

    def set(self, session_id: str, data: dict[str, Any]) -> None:
        self._store[session_id] = _RedisEntry(data=data, ttl_seconds=self._ttl_seconds)

    def delete(self, session_id: str) -> bool:
        return self._store.pop(session_id, None) is not None

    def exists(self, session_id: str) -> bool:
        return self.get(session_id) is not None

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None:
        self._checkpoints[session_id] = _RedisEntry(
            data=checkpoint_data, ttl_seconds=self._ttl_seconds
        )

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        entry = self._checkpoints.get(session_id)
        if entry is None:
            return None
        if time.time() - entry.created_at > entry.ttl_seconds:
            del self._checkpoints[session_id]
            return None
        return entry.data

    def list_sessions(self) -> list[str]:
        """List all non-expired session IDs."""
        now = time.time()
        return [
            sid for sid, entry in self._store.items()
            if now - entry.created_at <= entry.ttl_seconds
        ]


# ---------------------------------------------------------------------------
# PostgreSQL Session Store (file-based simulation)
# ---------------------------------------------------------------------------


class PostgreSQLSessionStore:
    """File-based PostgreSQL simulation implementing SessionStorePort.

    Each session is stored as a JSON file in the storage directory.
    """

    def __init__(self, storage_dir: Path) -> None:
        self._dir = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._checkpoint_dir = storage_dir / "checkpoints"
        self._checkpoint_dir.mkdir(exist_ok=True)

    def _session_file(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace(":", "_")
        return self._dir / f"{safe}.json"

    def _checkpoint_file(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace(":", "_")
        return self._checkpoint_dir / f"{safe}.json"

    def get(self, session_id: str) -> dict[str, Any] | None:
        f = self._session_file(session_id)
        if not f.exists():
            return None
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
            result: dict[str, Any] | None = record.get("data")
            return result
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, session_id: str, data: dict[str, Any]) -> None:
        record = {"session_id": session_id, "data": data, "updated_at": time.time()}
        f = self._session_file(session_id)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(str(tmp), str(f))

    def delete(self, session_id: str) -> bool:
        f = self._session_file(session_id)
        if f.exists():
            f.unlink()
            return True
        return False

    def exists(self, session_id: str) -> bool:
        return self._session_file(session_id).exists()

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None:
        record = {"session_id": session_id, "data": checkpoint_data, "saved_at": time.time()}
        f = self._checkpoint_file(session_id)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(str(tmp), str(f))

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        f = self._checkpoint_file(session_id)
        if not f.exists():
            return None
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
            result: dict[str, Any] | None = record.get("data")
            return result
        except (json.JSONDecodeError, OSError):
            return None

    def list_sessions(self) -> list[str]:
        """List all session IDs from stored files."""
        return [
            f.stem for f in self._dir.glob("*.json")
        ]


# ---------------------------------------------------------------------------
# Hybrid Session Store (L1→L2 fallback with write-through)
# ---------------------------------------------------------------------------


class HybridSessionStore:
    """Two-tier session store: L1 (fast, in-memory) → L2 (durable, file-based).

    Reads check L1 first, falling back to L2 on miss.
    Writes go to both tiers (write-through).

    Usage:
        l1 = RedisSessionStore(ttl_hours=4)
        l2 = PostgreSQLSessionStore(Path("/tmp/sessions"))
        hybrid = HybridSessionStore(l1, l2)
        hybrid.set("s1", {"ip": "Berserk"})
        data = hybrid.get("s1")  # L1 hit
    """

    def __init__(
        self,
        l1: SessionStorePort,
        l2: SessionStorePort,
    ) -> None:
        self._l1 = l1
        self._l2 = l2

    @property
    def l1(self) -> SessionStorePort:
        return self._l1

    @property
    def l2(self) -> SessionStorePort:
        return self._l2

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Get from L1, fallback to L2. Backfill L1 on L2 hit."""
        data = self._l1.get(session_id)
        if data is not None:
            return data

        data = self._l2.get(session_id)
        if data is not None:
            # Backfill L1
            self._l1.set(session_id, data)
        return data

    def set(self, session_id: str, data: dict[str, Any]) -> None:
        """Write-through: write to both L1 and L2."""
        self._l1.set(session_id, data)
        self._l2.set(session_id, data)

    def delete(self, session_id: str) -> bool:
        """Delete from both tiers."""
        r1 = self._l1.delete(session_id)
        r2 = self._l2.delete(session_id)
        return r1 or r2

    def exists(self, session_id: str) -> bool:
        """Check existence in either tier."""
        return self._l1.exists(session_id) or self._l2.exists(session_id)

    def save_checkpoint(self, session_id: str, checkpoint_data: dict[str, Any]) -> None:
        """Save checkpoint to both tiers."""
        self._l1.save_checkpoint(session_id, checkpoint_data)
        self._l2.save_checkpoint(session_id, checkpoint_data)

    def load_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        """Load checkpoint from L1, fallback to L2."""
        data = self._l1.load_checkpoint(session_id)
        if data is not None:
            return data
        return self._l2.load_checkpoint(session_id)

    def list_sessions(self) -> list[str]:
        """List sessions from both tiers (deduplicated)."""
        return list(set(self._l1.list_sessions()) | set(self._l2.list_sessions()))

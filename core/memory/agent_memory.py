"""AgentMemoryStore — isolated per-task memory for sub-agents.

GAP 6: Each sub-agent gets its own scoped memory store at
``.geode/agent-memory/{task_id}/``, preventing cross-contamination between
parallel sub-agent executions.

Data is stored as simple key-value text files with a TTL-based expiry.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from core.infrastructure.atomic_io import atomic_write_json

log = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path(".geode") / "agent-memory"
DEFAULT_TTL_HOURS = 24.0


class AgentMemoryStore:
    """File-backed key-value memory scoped to a single sub-agent task.

    Usage::

        store = AgentMemoryStore("task-analyze-berserk")
        store.save("findings", "Berserk is S-tier")
        findings = store.get("findings")
        store.clear()

        # Class method for periodic cleanup
        AgentMemoryStore.cleanup_expired()
    """

    def __init__(
        self,
        task_id: str,
        base_dir: Path | None = None,
        ttl_hours: float = DEFAULT_TTL_HOURS,
    ) -> None:
        self._task_id = task_id
        self._base_dir = base_dir or DEFAULT_BASE_DIR
        self._task_dir = self._base_dir / task_id
        self._ttl_hours = ttl_hours

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def task_dir(self) -> Path:
        return self._task_dir

    def save(self, key: str, value: str) -> None:
        """Save a key-value pair. Overwrites if exists."""
        self._task_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "value": value,
            "created_at": time.time(),
            "task_id": self._task_id,
        }
        file_path = self._task_dir / f"{key}.json"
        atomic_write_json(file_path, entry)

    def get(self, key: str) -> str | None:
        """Get a value by key. Returns None if not found or expired."""
        file_path = self._task_dir / f"{key}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            # Check TTL
            age_hours = (time.time() - data.get("created_at", 0)) / 3600
            if age_hours > self._ttl_hours:
                file_path.unlink(missing_ok=True)
                return None
            val: str | None = data.get("value")
            return val
        except (json.JSONDecodeError, OSError):
            return None

    def list_keys(self) -> list[str]:
        """List all non-expired keys in this task's memory."""
        if not self._task_dir.exists():
            return []
        keys = []
        for f in self._task_dir.iterdir():
            if f.suffix == ".json":
                key = f.stem
                # Check if still valid (not expired)
                if self.get(key) is not None:
                    keys.append(key)
        return sorted(keys)

    def clear(self) -> None:
        """Remove all memory for this task."""
        if not self._task_dir.exists():
            return
        import shutil

        shutil.rmtree(self._task_dir, ignore_errors=True)

    @classmethod
    def cleanup_expired(
        cls,
        base_dir: Path | None = None,
        ttl_hours: float = DEFAULT_TTL_HOURS,
    ) -> int:
        """Remove expired task memory directories. Returns count removed."""
        bd = base_dir or DEFAULT_BASE_DIR
        if not bd.exists():
            return 0

        import shutil

        cutoff = time.time() - (ttl_hours * 3600)
        removed = 0

        for task_dir in list(bd.iterdir()):
            if not task_dir.is_dir():
                continue
            # Check the newest file in the directory
            newest = 0.0
            for f in task_dir.iterdir():
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        newest = max(newest, data.get("created_at", 0))
                    except (json.JSONDecodeError, OSError):
                        pass
            if newest > 0 and newest < cutoff:
                shutil.rmtree(task_dir, ignore_errors=True)
                removed += 1

        return removed

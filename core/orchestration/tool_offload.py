"""Tool Result Offloading — store large results to filesystem, inject summaries.

When a tool result exceeds the configured token threshold, the full result
is persisted to `.geode/tool-offload/{session_id}/` and replaced in context
with a compact summary + retrieval reference.  The LLM can recall the full
result on demand via the ``recall_tool_result`` tool.

JetBrains Research (2025.12) + Manus AI pattern: observation masking +
offloading achieves ~50% input token reduction with equivalent solve rates.
"""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from core.utils.atomic_io import atomic_write_json

log = logging.getLogger(__name__)

# ContextVar DI (following memory_tools.py pattern)
_offload_store_ctx: ContextVar[ToolResultOffloadStore | None] = ContextVar(
    "tool_offload_store", default=None
)


def set_offload_store(store: ToolResultOffloadStore | None) -> None:
    """Inject the offload store into the current context."""
    _offload_store_ctx.set(store)


def get_offload_store() -> ToolResultOffloadStore | None:
    """Retrieve the offload store from the current context."""
    return _offload_store_ctx.get()


class ToolResultOffloadStore:
    """File-backed store for large tool results.

    Stores results at ``.geode/tool-offload/{session_id}/{ref_id}.json``
    with TTL-based expiry.  Thread-safe via atomic writes (no shared mutable state).
    """

    def __init__(
        self,
        *,
        session_id: str,
        threshold: int = 5000,
        ttl_hours: float = 4.0,
        base_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.threshold = threshold
        self._ttl_s = ttl_hours * 3600
        self._base_dir = base_dir or Path(".geode/tool-offload")
        self._session_dir = self._base_dir / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)

    def offload(self, ref_id: str, result: Any) -> str:
        """Persist *result* to disk and return *ref_id*.

        The caller should replace the in-context tool result with a compact
        summary referencing this *ref_id*.
        """
        payload = {
            "ref_id": ref_id,
            "result": result,
            "offloaded_at": time.time(),
        }
        path = self._session_dir / f"{ref_id}.json"
        atomic_write_json(path, payload, indent=None)
        log.debug("Offloaded tool result %s (%s)", ref_id, path)
        return ref_id

    def recall(self, ref_id: str) -> dict[str, Any]:
        """Retrieve the full result for *ref_id*.

        Returns the original result dict, or an error dict if not found / expired.
        """
        path = self._session_dir / f"{ref_id}.json"
        if not path.exists():
            return {"error": f"Offloaded result not found: {ref_id}"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"error": f"Failed to read offloaded result {ref_id}: {exc}"}

        # TTL check
        offloaded_at = data.get("offloaded_at", 0.0)
        if time.time() - float(offloaded_at) > self._ttl_s:
            path.unlink(missing_ok=True)
            return {"error": f"Offloaded result expired: {ref_id}"}

        result: dict[str, Any] = data.get("result", {})
        return result

    def cleanup_expired(self) -> int:
        """Remove expired offload files.  Returns count of removed files."""
        if not self._session_dir.exists():
            return 0
        removed = 0
        now = time.time()
        for path in self._session_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if now - data.get("offloaded_at", 0.0) > self._ttl_s:
                    path.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                path.unlink(missing_ok=True)
                removed += 1
        # Remove empty session dir
        if self._session_dir.exists() and not any(self._session_dir.iterdir()):
            self._session_dir.rmdir()
        return removed

    def cleanup_session(self) -> int:
        """Remove all offload files for this session."""
        if not self._session_dir.exists():
            return 0
        removed = 0
        for path in self._session_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        if self._session_dir.exists() and not any(self._session_dir.iterdir()):
            self._session_dir.rmdir()
        return removed


def extract_result_summary(result: Any, *, max_chars: int = 400) -> str:
    """Extract a compact summary from a tool result.

    Priority: ``summary`` field > ``text`` field > JSON preview.
    """
    if isinstance(result, dict):
        # Prefer explicit summary field (SubAgentResult always has one)
        if "summary" in result:
            s = str(result["summary"])
            return s[:max_chars] if len(s) > max_chars else s

        # Try common text fields
        for key in ("text", "content", "message", "output"):
            val = result.get(key)
            if isinstance(val, str):
                return val[:max_chars] if len(val) > max_chars else val

        # Fall back to key listing + partial JSON
        keys = list(result.keys())[:10]
        preview = json.dumps(result, ensure_ascii=False, default=str)[:max_chars]
        return f"keys={keys} preview={preview}"

    s = str(result)
    return s[:max_chars] if len(s) > max_chars else s

"""Tool Result Offloading — store large results to filesystem, inject summaries.

When a tool result exceeds the configured token threshold, the full result
is persisted in the user-owned workspace store and replaced in context
with a compact summary + retrieval reference.  The LLM can recall the full
result on demand via the ``recall_tool_result`` tool.

JetBrains Research (2025.12) + Manus AI pattern: observation masking +
offloading achieves ~50% input token reduction with equivalent solve rates.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from core.memory.atomic_write import atomic_write_json
from core.orchestration.context_budget import MIN_TOOL_RESULT_TOKENS

log = logging.getLogger(__name__)


def _valid_component(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and not any(char in "/\\" or ord(char) < 32 for char in value)
    )


class ToolResultOffloadStore:
    """File-backed store for large tool results.

    Stores results at ``~/.geode/projects/{id}/tool-offload/{session_id}/{ref_id}.json``
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
        from core.paths import get_project_root, get_tool_offload_dir

        if not _valid_component(session_id):
            raise ValueError("Offload session ID must be a single path component")
        self.session_id = session_id
        # A positive threshold below the supported floor is raised to it.
        self.threshold = max(threshold, MIN_TOOL_RESULT_TOKENS) if threshold > 0 else threshold
        self._ttl_s = ttl_hours * 3600
        self._workspace = get_project_root() if base_dir is None else None
        self._base_dir = (base_dir or get_tool_offload_dir(self._workspace)).absolute()
        self._storage_root = self._base_dir.parent.resolve()
        self._session_dir = self._base_dir / session_id
        self._admitted = base_dir is not None

    def _check_session_directory(self) -> None:
        for directory in (self._base_dir, self._session_dir):
            if directory.is_symlink() or not directory.resolve().is_relative_to(self._storage_root):
                raise ValueError("Offload directory escapes its workspace store")
        if not self._admitted:
            from core.paths import admit_project_data_dir

            if admit_project_data_dir(self._workspace).resolve() != self._storage_root:
                raise ValueError("Offload workspace identity changed")
            self._admitted = True

    def _result_path(self, ref_id: str) -> Path:
        if not _valid_component(ref_id):
            raise ValueError("Offload reference must be a single path component")
        self._check_session_directory()
        path = self._session_dir / f"{ref_id}.json"
        if path.is_symlink():
            raise ValueError("Offload result must not be a symlink")
        return path

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
        path = self._result_path(ref_id)
        atomic_write_json(path, payload, indent=None)
        log.debug("Offloaded tool result %s (%s)", ref_id, path)
        return ref_id

    def recall(self, ref_id: str) -> dict[str, Any]:
        """Retrieve the full result for *ref_id*.

        Returns the original result dict, or an error dict if not found / expired.
        """
        try:
            path = self._result_path(ref_id)
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return {"error": f"Offloaded result not found: {ref_id}"}
        except (ValueError, OSError) as exc:
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
        self._check_session_directory()
        if not self._session_dir.exists():
            return 0
        removed = 0
        now = time.time()
        for path in self._session_dir.glob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8"
                ) as stream:
                    data = json.load(stream)
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
        self._check_session_directory()
        if not self._session_dir.exists():
            return 0
        removed = 0
        for path in self._session_dir.glob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
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
        # Prefer an explicit summary field when the tool returns one.
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

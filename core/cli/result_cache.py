"""Result cache -- multi-IP LRU cache with disk persistence.

Extracted from ``core/cli/__init__.py`` for architectural clarity.

Cache expiry:
  - TTL: 24 hours (configurable via ``ttl_seconds``)
  - Content hash: SHA-256 of serialized JSON, verified on load
  - Expired/corrupted entries are skipped during disk load
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RESULT_CACHE_DIR = Path(".geode/result_cache")
_RESULT_CACHE_MAX = 8
_DEFAULT_TTL_SECONDS = 86400  # 24 hours


class ResultCache:
    """OrderedDict-based LRU cache for pipeline results, with disk persistence.

    Supports TTL-based expiry and content hash verification.
    """

    def __init__(
        self,
        max_size: int = _RESULT_CACHE_MAX,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        cache_dir: Path | None = None,
    ) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache_dir = cache_dir or _RESULT_CACHE_DIR
        self._load_from_disk()

    def get(self, ip_name: str) -> dict[str, Any] | None:
        key = ip_name.lower()
        if key not in self._cache:
            return None
        entry = self._cache[key]
        # Check in-memory TTL
        if self._is_expired(entry):
            log.debug("Cache expired for %s (TTL)", key)
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return entry

    def put(self, result: dict[str, Any] | None) -> None:
        if result is None:
            return
        ip_name = result.get("ip_name", "")
        if not ip_name:
            return
        key = ip_name.lower()
        # Add cache metadata
        result = dict(result)  # shallow copy to avoid mutating caller
        result["_cached_at"] = time.time()
        result["_content_hash"] = self._compute_hash(result)
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        self._persist(key, result)

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        """Check if a cache entry has exceeded TTL."""
        cached_at = float(entry.get("_cached_at", 0))
        if not cached_at:
            return False  # Legacy entries without timestamp are kept
        return bool((time.time() - cached_at) > self._ttl_seconds)

    def _is_hash_valid(self, entry: dict[str, Any]) -> bool:
        """Verify content hash matches the stored hash."""
        stored_hash = str(entry.get("_content_hash", ""))
        if not stored_hash:
            return True  # Legacy entries without hash are accepted
        computed = self._compute_hash(entry)
        return bool(computed == stored_hash)

    @staticmethod
    def _compute_hash(data: dict[str, Any]) -> str:
        """Compute SHA-256 hash of cache content (excluding cache metadata)."""
        # Remove cache-internal keys before hashing
        clean = {k: v for k, v in data.items() if not k.startswith("_c")}
        try:
            serialized = _json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
            return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        except (TypeError, ValueError):
            return ""

    def _persist(self, key: str, result: dict[str, Any]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            safe = key.replace(" ", "-")
            fpath = self._cache_dir / f"{safe}.json"
            from pydantic import BaseModel

            from core.utils.atomic_io import atomic_write_json

            def _default(obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                return str(obj)

            atomic_write_json(fpath, result, default=_default)
        except Exception:
            log.debug("Failed to persist result cache for %s", key, exc_info=True)

    def _load_from_disk(self) -> None:
        if not self._cache_dir.exists():
            return
        for fpath in sorted(self._cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = _json.loads(fpath.read_text(encoding="utf-8"))
                # Skip expired entries
                if self._is_expired(data):
                    log.debug("Skipping expired cache file: %s", fpath.name)
                    continue
                # Skip corrupted entries (hash mismatch)
                if not self._is_hash_valid(data):
                    log.warning("Skipping corrupted cache file: %s (hash mismatch)", fpath.name)
                    continue
                ip = data.get("ip_name", fpath.stem)
                self._cache[ip.lower()] = data
            except Exception:
                log.debug("Failed to load result cache %s", fpath.name, exc_info=True)
        # Trim to max
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


# Backward-compatible alias (tests import _ResultCache)
_ResultCache = ResultCache

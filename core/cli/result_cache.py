"""Result cache — multi-IP LRU cache with disk persistence.

Extracted from ``core/cli/__init__.py`` for architectural clarity.
"""

from __future__ import annotations

import json as _json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RESULT_CACHE_DIR = Path(".geode/result_cache")
_RESULT_CACHE_MAX = 8


class ResultCache:
    """OrderedDict-based LRU cache for pipeline results, with disk persistence."""

    def __init__(self, max_size: int = _RESULT_CACHE_MAX) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._load_from_disk()

    def get(self, ip_name: str) -> dict[str, Any] | None:
        key = ip_name.lower()
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, result: dict[str, Any] | None) -> None:
        if result is None:
            return
        ip_name = result.get("ip_name", "")
        if not ip_name:
            return
        key = ip_name.lower()
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        self._persist(key, result)

    def _persist(self, key: str, result: dict[str, Any]) -> None:
        try:
            _RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            safe = key.replace(" ", "-")
            fpath = _RESULT_CACHE_DIR / f"{safe}.json"
            from pydantic import BaseModel

            def _default(obj: Any) -> Any:
                if isinstance(obj, BaseModel):
                    return obj.model_dump()
                return str(obj)

            fpath.write_text(
                _json.dumps(result, ensure_ascii=False, default=_default),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Failed to persist result cache for %s", key, exc_info=True)

    def _load_from_disk(self) -> None:
        if not _RESULT_CACHE_DIR.exists():
            return
        for fpath in sorted(_RESULT_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = _json.loads(fpath.read_text(encoding="utf-8"))
                ip = data.get("ip_name", fpath.stem)
                self._cache[ip.lower()] = data
            except Exception:
                log.debug("Failed to load result cache %s", fpath.name, exc_info=True)
        # Trim to max
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


# Backward-compatible alias (tests import _ResultCache)
_ResultCache = ResultCache

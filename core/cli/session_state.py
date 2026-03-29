"""Session state management — ContextVars, ResultCache, accessors.

Extracted from cli/__init__.py to reduce God Object (Kent Beck Phase 3).
"""

from __future__ import annotations

import json as _json
import logging
import threading
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from core.cli.search import IPSearchEngine
    from core.cli.startup import ReadinessReport

log = logging.getLogger(__name__)

# Thread-safe singletons for REPL session via contextvars
_search_engine_ctx: ContextVar[Any] = ContextVar("search_engine", default=None)
_readiness_ctx: ContextVar[Any] = ContextVar("readiness", default=None)
_scheduler_service_ctx: ContextVar[Any] = ContextVar("scheduler_service", default=None)
_user_task_graph_ctx: ContextVar[Any] = ContextVar("user_task_graph", default=None)


# ---------------------------------------------------------------------------
# Multi-IP LRU analysis result cache
# ---------------------------------------------------------------------------


def _get_result_cache_dir() -> Path:
    from core.paths import get_project_data_dir

    return get_project_data_dir() / "result_cache"


_RESULT_CACHE_DIR = _get_result_cache_dir()
_RESULT_CACHE_MAX = 8


class _ResultCache:
    """OrderedDict-based LRU cache for pipeline results, with disk persistence."""

    def __init__(self, max_size: int = _RESULT_CACHE_MAX) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._load_from_disk()

    def get(self, ip_name: str) -> dict[str, Any] | None:
        key = ip_name.lower()
        with self._lock:
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
        with self._lock:
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


_result_cache = _ResultCache()


def _get_search_engine() -> IPSearchEngine:
    """Get or create the context-local IPSearchEngine."""
    from core.cli.search import IPSearchEngine as _IPSearchEngine

    engine = _search_engine_ctx.get()
    if engine is None:
        engine = _IPSearchEngine()
        _search_engine_ctx.set(engine)
    return cast("IPSearchEngine", engine)


def _get_readiness() -> ReadinessReport | None:
    """Get the context-local ReadinessReport."""
    return cast("ReadinessReport | None", _readiness_ctx.get())


def _set_readiness(report: ReadinessReport) -> None:
    """Set the context-local ReadinessReport."""
    _readiness_ctx.set(report)


def _get_last_result() -> dict[str, Any] | None:
    """Get the most recently cached pipeline result (any IP)."""
    if not _result_cache._cache:
        return None
    # Last item in OrderedDict = most recent
    key = next(reversed(_result_cache._cache))
    return _result_cache._cache[key]


def _set_last_result(result: dict[str, Any] | None) -> None:
    """Cache a pipeline result (multi-IP LRU)."""
    _result_cache.put(result)


def _get_user_task_graph() -> Any:
    """Get (or lazily create) the context-local user TaskGraph."""
    from core.orchestration.task_system import TaskGraph

    graph = _user_task_graph_ctx.get()
    if graph is None:
        graph = TaskGraph()
        _user_task_graph_ctx.set(graph)
    return graph


def _reset_user_task_graph() -> None:
    """Reset the context-local user TaskGraph (new session)."""
    from core.orchestration.task_system import TaskGraph

    _user_task_graph_ctx.set(TaskGraph())

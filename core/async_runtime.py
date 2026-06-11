"""Async runtime helpers for process-edge entrypoints."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)


def run_process_coroutine[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from a synchronous process/thread entrypoint.

    This helper is only for true outer boundaries such as Typer commands,
    daemon threads, and worker subprocess entrypoints. Runtime code should
    propagate ``await`` instead of calling this function.

    PR-LOOP-POLLUTION-FIX (2026-06-12) — calling this from an
    ``asyncio.to_thread`` worker is the loop-pollution canary: it means an
    async runtime path was bridged sync and is now spawning a throwaway
    event loop per call. Combined with loop-bound shared resources (httpx
    client pools) that pattern produced the 2026-06-12 web_search
    insta-fail/hang incident. The warning below keeps any regression
    observable in serve logs; the structural fix is to register the
    handler as async and ``await`` it (see
    core/cli/tool_handlers/delegated.py).
    """
    thread_name = threading.current_thread().name
    if thread_name.startswith("asyncio_"):
        log.warning(
            "run_process_coroutine() called from to_thread worker %r — this "
            "spawns a throwaway event loop per call (loop-pollution canary, "
            "PR-LOOP-POLLUTION-FIX 2026-06-12). Register the handler as "
            "async and await it instead.",
            thread_name,
        )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        with asyncio.Runner() as runner:
            return runner.run(coro)

    coro.close()
    raise RuntimeError("run_process_coroutine() cannot be called from an active event loop")

"""Async runtime helpers for process-edge entrypoints."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_process_coroutine[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from a synchronous process/thread entrypoint.

    This helper is only for true outer boundaries such as Typer commands,
    daemon threads, and worker subprocess entrypoints. Runtime code should
    propagate ``await`` instead of calling this function.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        with asyncio.Runner() as runner:
            return runner.run(coro)

    coro.close()
    raise RuntimeError("run_process_coroutine() cannot be called from an active event loop")

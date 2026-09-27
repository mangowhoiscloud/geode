"""Async runtime helpers for process-edge entrypoints."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)


async def _drain_owned_loop() -> None:
    """Settle this owned loop's work, then release its SDK transports."""
    from core.llm.loop_affinity import drain_current_loop_clients

    owner = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not owner]

    async def finish() -> None:
        try:
            for task in pending:
                task.cancel()
            results = await asyncio.gather(*pending, return_exceptions=True)
            failures = [
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            ]
            if failures:
                log.warning(
                    "%d background task(s) failed during loop shutdown (%s)",
                    len(failures),
                    ", ".join(type(error).__name__ for error in failures[:5]),
                )
        finally:
            try:
                await asyncio.get_running_loop().shutdown_asyncgens()
            finally:
                await drain_current_loop_clients()

    cleanup = asyncio.create_task(finish(), name="geode-loop-cleanup")
    cancellation: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as exc:
            # Repeated cancellation must not abandon the owned cleanup task.
            if cancellation is None:
                cancellation = exc
        except BaseException:
            break  # Read its terminal exception below after all clients were attempted.
    try:
        cleanup.result()
    except BaseException as exc:
        if cancellation is None:
            raise
        log.warning("Loop cleanup also failed during cancellation (%s)", type(exc).__name__)
    if cancellation is not None:
        raise cancellation


@contextmanager
def owned_asyncio_runner() -> Iterator[asyncio.Runner]:
    """Own a fresh loop and drain its clients before Runner closes it.

    Uses public asyncio APIs only. No borrowed loop or individual runtime may
    use this cleanup: all tasks on the newly created loop belong to this edge.
    """
    runner = asyncio.Runner()
    failure: BaseException | None = None
    try:
        yield runner
    except BaseException as exc:
        failure = exc
    finally:
        cleanups: tuple[Callable[[], None], ...] = (
            lambda: runner.run(_drain_owned_loop()),
            runner.close,
        )
        for cleanup in cleanups:
            try:
                cleanup()
            except BaseException as exc:
                if failure is None:
                    failure = exc
                else:
                    log.warning(
                        "Loop cleanup also failed after work failed (%s)", type(exc).__name__
                    )
        if failure is not None:
            raise failure


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
    core/tools/handlers/delegated.py).
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
        with owned_asyncio_runner() as runner:
            return runner.run(coro)

    coro.close()
    raise RuntimeError("run_process_coroutine() cannot be called from an active event loop")

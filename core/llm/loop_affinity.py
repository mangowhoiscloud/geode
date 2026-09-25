"""Reuse async SDK clients on their owning loop and close them before loop exit.

Each loop entry holds the active selection and all clients still owned, including
clients retired by credential changes. A separate owner index keeps caches alive
across adapter registry replacement. Sessions borrow these shared resources;
only a loop owner drains them after its work and streams have settled.

Weak loop keys do not guarantee cleanup: client transports can reference their
loop. Already-closed external loops use a drop-only fallback on the next get;
async cleanup cannot safely run on a different loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class _LoopClients:
    active: Any = None
    identity: str | None = None
    # ponytail: retired clients live until loop teardown; add leases if rotation retention grows.
    owned: list[Any] = field(default_factory=list)


# Dict keys retain registration order for close attempts and failure reporting.
_LOOP_OWNERS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[LoopAffineClientCache, None]
] = weakref.WeakKeyDictionary()
_OWNERS_LOCK = threading.Lock()


def _discard_closed_loops() -> None:
    with _OWNERS_LOCK:
        closed = {loop: _LOOP_OWNERS.pop(loop) for loop in list(_LOOP_OWNERS) if loop.is_closed()}
    # Never acquire a cache lock while holding the owner-index lock.
    for loop, owners in closed.items():
        for cache in owners:
            cache._take_owned_clients(loop)


async def drain_current_loop_clients() -> None:
    """Close owned SDK clients after all work on the current loop has settled.

    Never call this for one session or runtime: adapters share clients across
    sessions on the same loop. Borrowed clients passed to capability helpers
    are not registered here. Builders passed to the cache transfer ownership.
    Failed closes remain owned for a retry while this loop is still alive.
    """
    loop = asyncio.get_running_loop()
    with _OWNERS_LOCK:
        owners = _LOOP_OWNERS.pop(loop, {})
    failures: list[BaseException] = []
    failure_count = 0
    cancellation: asyncio.CancelledError | None = None
    for cache in owners:
        for client in cache._take_owned_clients(loop):
            try:
                close = asyncio.create_task(client.close())
                while not close.done():
                    try:
                        await asyncio.shield(close)
                    except asyncio.CancelledError as exc:
                        if close.cancelled():
                            break
                        if cancellation is None:
                            cancellation = exc
                    except BaseException:
                        break
                close.result()
            except BaseException as exc:
                cache._retain_failed_client(loop, client)
                failure_count += 1
                if len(failures) < 5:
                    failures.append(exc)
    if cancellation is not None:
        if failures:
            log.warning("%d SDK client cleanup(s) also failed during cancellation", failure_count)
        raise cancellation
    if failures:
        raise BaseExceptionGroup(
            f"SDK client cleanup failed for {failure_count} client(s)", failures
        )


class LoopAffineClientCache:
    """One async SDK client per owning event loop.

    Builders transfer ownership of clients with an async ``close()`` method.
    ``invalidate()`` retires active selections without closing in-flight clients.
    Without a running loop, ``get`` builds an uncached client owned by its caller.
    """

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopClients] = (
            weakref.WeakKeyDictionary()
        )
        # Cache state is shared by the main loop and poller threads.
        self._lock = threading.Lock()

    def get(self, builder: Callable[[], Any], *, identity: str | None = None) -> Any:
        """Reuse the selection only while its optional non-secret identity matches."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("loop-affine[%s]: no running loop — building uncached client", self._name)
            return builder()

        _discard_closed_loops()
        with self._lock:
            entry = self._by_loop.get(loop)
            if entry is not None and entry.active is not None and entry.identity == identity:
                return entry.active

            # Keep construction/publication atomic with credential invalidation.
            # Builders are synchronous SDK constructors; they do not send requests
            # or call back into this cache.
            client = builder()
            if entry is None:
                entry = self._by_loop[loop] = _LoopClients()
            entry.active = client
            entry.identity = identity
            entry.owned.append(client)
            bound = sum(item.active is not None for item in self._by_loop.values())
            with _OWNERS_LOCK:
                _LOOP_OWNERS.setdefault(loop, {})[self] = None
        log.info(
            "loop-affine[%s]: client bound to loop %#x on thread %s (%d loop(s) bound)",
            self._name,
            id(loop),
            threading.current_thread().name,
            bound,
        )
        return client

    def invalidate(self) -> None:
        """Retire active selections without closing in-flight clients."""
        with self._lock:
            for entry in self._by_loop.values():
                entry.active = None

    def _take_owned_clients(self, loop: asyncio.AbstractEventLoop) -> list[Any]:
        """Detach this loop's selection and owned clients before cleanup."""
        with self._lock:
            entry = self._by_loop.pop(loop, None)
            return entry.owned if entry is not None else []

    def _retain_failed_client(self, loop: asyncio.AbstractEventLoop, client: Any) -> None:
        """Keep a failed close retryable without changing the active selection."""
        with self._lock:
            entry = self._by_loop.setdefault(loop, _LoopClients())
            entry.owned.append(client)
            with _OWNERS_LOCK:
                _LOOP_OWNERS.setdefault(loop, {})[self] = None

    def bound_loop_count(self) -> int:
        """Number of loops with an active client selection — observability."""
        with self._lock:
            return sum(entry.active is not None for entry in self._by_loop.values())

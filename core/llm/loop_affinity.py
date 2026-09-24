"""Event-loop-affine async client cache — PR-LOOP-POLLUTION-FIX (2026-06-12).

httpx ``AsyncClient`` (and the SDK clients wrapping it — ``AsyncAnthropic``,
``AsyncOpenAI``) binds its connection-pool primitives (asyncio ``Event`` /
``Lock`` via anyio) to the event loop that first drives them. The httpx
contract is "one client shared between *tasks*" — tasks of a single loop.
Reusing the client from a different loop produces one of two failures:

- ``RuntimeError: <asyncio.locks.Event ...> is bound to a different event
  loop`` → surfaces as an instant ``APIConnectionError`` (~2-4ms), or
- an eternal ``await`` on a foreign loop's Event — no exception, no log,
  a zombie coroutine.

Incident (2026-06-12 00:08, serve daemon): three parallel ``web_search``
calls each ran on a throwaway ``asyncio.Runner`` loop (sync delegate
handler residue) while sharing one process-global cached client — one
insta-failed (recovered by the dispatch retry), two hung forever
(``sample`` showed two zombie ``asyncio_N`` worker loops in kevent and an
Anthropic socket stuck in CLOSE_WAIT).

This cache replaces ``self._client`` single-slot caching in adapters:
one client **per owning event loop**, keyed weakly so a dead loop's entry
disappears with the loop. The genuinely-multi-loop daemon topology (main
serve loop + CLIPoller thread loop + gateway turns) then gets one healthy
client per loop instead of one poisoned client shared across them.

GEODE's process/thread loop owners drain current and retired clients before
closing their loops. Credential rotation retires clients without interrupting
in-flight calls. External loop owners can call ``drain_current_loop_clients``
after their work has settled. Already-closed external loops retain the legacy
drop-only fallback: async cleanup cannot safely run on another loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Cache selection and resource lifetime differ: registry replacement and
# credential invalidation must not abandon clients still used by a session.
# Keep their cache owner alive until its actual event loop is drained.
# ponytail: retired clients live until loop teardown; add leases if rotation retention grows.
_OWNED_CLIENTS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[LoopAffineClientCache, list[Any]]
] = weakref.WeakKeyDictionary()
_OWNERS_LOCK = threading.Lock()


async def drain_current_loop_clients() -> None:
    """Close owned SDK clients after all work on the current loop has settled.

    Never call this for one session or runtime: adapters share clients across
    sessions on the same loop. Borrowed clients passed to capability helpers
    are not registered here. Builders passed to the cache transfer ownership.
    Failed closes remain owned for a retry while this loop is still alive.
    """
    loop = asyncio.get_running_loop()
    with _OWNERS_LOCK:
        owners = _OWNED_CLIENTS.pop(loop, {})
    failures: list[BaseException] = []
    failure_count = 0
    cancellation: asyncio.CancelledError | None = None
    for cache, clients in owners.items():
        with cache._lock:
            cache._by_loop.pop(loop, None)
        for client in clients:
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
                with _OWNERS_LOCK:
                    _OWNED_CLIENTS.setdefault(loop, {}).setdefault(cache, []).append(client)
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

    ``get(builder)`` returns the cached client for the *currently running*
    loop, building (and caching) one via ``builder()`` on first use per
    loop. Entries are held in a ``WeakKeyDictionary`` keyed by the loop —
    when a loop is garbage-collected (e.g. a finished ``asyncio.Runner``),
    its client entry vanishes with it.

    Called without a running loop (sync probe paths), the client is built
    fresh and NOT cached; that synchronous caller owns its cleanup.

    ``invalidate()`` drops active selections, retaining ownership until loop
    teardown so in-flight requests can finish using the previous credential.
    """

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = (
            weakref.WeakKeyDictionary()
        )
        # The cache is touched from multiple threads (main serve loop,
        # CLIPoller thread, to_thread workers) — guard the dict itself.
        self._lock = threading.Lock()

    def get(self, builder: Callable[[], Any]) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("loop-affine[%s]: no running loop — building uncached client", self._name)
            return builder()

        with self._lock:
            with _OWNERS_LOCK:
                for stale_loop in [key for key in _OWNED_CLIENTS if key.is_closed()]:
                    del _OWNED_CLIENTS[stale_loop]
            # Sweep closed-loop entries. The WeakKeyDictionary alone is NOT
            # sufficient cleanup: the cached client's loop-bound transports
            # can keep a strong reference back to its (closed) loop, so the
            # weak key never dies and the entry would otherwise persist —
            # one leaked client per throwaway loop (Codex MCP review
            # 2026-06-12). The sweep bounds that to "until any next get()".
            for cached_loop in [k for k in self._by_loop if k.is_closed()]:
                del self._by_loop[cached_loop]
            cached = self._by_loop.get(loop)
            if cached is not None:
                return cached

            # Keep construction/publication atomic with credential invalidation.
            # Builders are synchronous SDK constructors; they do not send requests
            # or call back into this cache.
            client = builder()
            self._by_loop[loop] = client
            bound = len(self._by_loop)
            with _OWNERS_LOCK:
                _OWNED_CLIENTS.setdefault(loop, {}).setdefault(self, []).append(client)
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
            self._by_loop.clear()

    def bound_loop_count(self) -> int:
        """Number of live loops currently holding a client — observability."""
        with self._lock:
            return len(self._by_loop)

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

Old clients on dead loops are dropped, not closed — ``aclose()`` requires
the owning loop, which may already be gone; CPython reclaims the sockets
via GC finalizers. The INFO log on each new binding keeps the rebuild
observable in serve logs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class LoopAffineClientCache:
    """One async SDK client per owning event loop.

    ``get(builder)`` returns the cached client for the *currently running*
    loop, building (and caching) one via ``builder()`` on first use per
    loop. Entries are held in a ``WeakKeyDictionary`` keyed by the loop —
    when a loop is garbage-collected (e.g. a finished ``asyncio.Runner``),
    its client entry vanishes with it.

    Called without a running loop (sync probe paths), the client is built
    fresh and NOT cached — correctness over reuse on that rare path.

    ``invalidate()`` drops all entries — for credential rotation (e.g.
    OAuth token refresh) where every loop must rebuild against the new
    secret.
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

        client = builder()
        with self._lock:
            self._by_loop[loop] = client
            bound = len(self._by_loop)
        log.info(
            "loop-affine[%s]: client bound to loop %#x on thread %s (%d loop(s) bound)",
            self._name,
            id(loop),
            threading.current_thread().name,
            bound,
        )
        return client

    def invalidate(self) -> None:
        """Drop every cached client (credential rotation)."""
        with self._lock:
            self._by_loop.clear()

    def bound_loop_count(self) -> int:
        """Number of live loops currently holding a client — observability."""
        with self._lock:
            return len(self._by_loop)

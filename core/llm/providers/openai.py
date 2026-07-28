"""OpenAI provider — client lifecycle + retry wrapper.

Merged from core.infrastructure.adapters.llm.openai_adapter.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.llm.loop_affinity import LoopAffineClientCache

log = logging.getLogger(__name__)

# Retry policy values (max_retries / retry_base_delay / retry_max_delay) are
# resolved lazily from ``core.config.settings.llm_*`` inside
# ``retry_with_backoff_generic`` (fallback.py).  Keeping a single source of
# truth ensures runtime ``settings.llm_max_retries`` tuning reaches every
# provider — previously OpenAI/GLM passed module-local constants that pinned
# them to ``3`` regardless of configuration.

# H11-tail: DEFAULT_OPENAI_MODEL / OPENAI_FALLBACK_MODELS were boot-frozen
# module aliases of OPENAI_PRIMARY / OPENAI_FALLBACK_CHAIN. Consumers now read
# the live values from ``core.config`` via function-local imports so a
# routing.toml reload is seen without a restart.


_openai_client: Any = None  # openai.OpenAI | None — lazy import
_openai_lock = threading.Lock()
# PR-LOOP-POLLUTION-FIX (2026-06-12) — async client is per-event-loop, not
# process-global (see core/llm/loop_affinity.py).
_async_openai_clients = LoopAffineClientCache("openai-provider")


def _resolve_openai_key() -> str:
    """Resolve OpenAI API key from ProfileRotator (OAuth preferred) or settings."""
    from core.config import settings
    from core.llm.credentials import resolve_provider_key

    return resolve_provider_key("openai", settings.openai_api_key)


def _get_openai_client() -> Any:
    """Lazy import and return cached OpenAI client (thread-safe).

    PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28, Codex MCP MED) —
    ``max_retries=0`` matches the adapter-side invariant
    (``_openai_common.build_async_openai_client``) so legacy callers that
    still hit this singleton (paperclip ``OpenAIAdapter``,
    ``llm_extract_learning``, ``models.py``) don't compound SDK + app
    retry loops on stalled streams.
    """
    global _openai_client
    if _openai_client is None:
        with _openai_lock:
            if _openai_client is None:
                import openai

                _openai_client = openai.OpenAI(api_key=_resolve_openai_key(), max_retries=0)
    return _openai_client


def _get_async_openai_client() -> Any:
    """Return the async OpenAI client bound to the CURRENT event loop.

    See :func:`_get_openai_client` for the ``max_retries=0`` rationale and
    ``core/llm/loop_affinity.py`` for why the cache is per-loop.
    """

    def _build() -> Any:
        import openai

        return openai.AsyncOpenAI(api_key=_resolve_openai_key(), max_retries=0)

    return _async_openai_clients.get(_build)


def reset_openai_client() -> None:
    """Reset cached OpenAI client (e.g. after /key openai changes)."""
    global _openai_client
    with _openai_lock:
        _openai_client = None
    _async_openai_clients.invalidate()


# ── 2026-07-29 prune ───────────────────────────────────────────────────────
# ``OpenAIAdapter`` (legacy sync/tool-use orchestrator) and its
# ``_get_retryable_errors`` helper were deleted: no production caller —
# OpenAI-family traffic runs through ``core/llm/adapters`` (openai_payg /
# codex_oauth / codex_cli). This module keeps only client lifecycle
# (``_get_openai_client`` / ``reset_openai_client``) as the low-level layer.

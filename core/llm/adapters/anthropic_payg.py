"""AnthropicPaygAdapter — PAYG (API-key) path to Anthropic models.

Layer 3 adapter (paperclip ``ServerAdapterModule`` shape). Calls the Anthropic
SDK with the API key from settings — and *not* the OAuth profile, even if
``ProfileRotator`` would prefer it under the legacy
``_resolve_anthropic_key()`` global priority. Codex MCP review 2026-05-23
flagged the singleton-client sharing as a BLOCKER for source isolation; this
adapter now owns its client via :func:`_anthropic_common.build_async_anthropic_client`.

Pair with :class:`AnthropicOAuthAdapter` (same provider, different source).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.llm.adapters._anthropic_common import (
    build_async_anthropic_client,
    build_create_kwargs,
    build_stream_kwargs,
    translate_response,
)
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    ModelSpec,
    QuotaWindows,
    StreamEvent,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.orchestration.anthropic_api_lane import acquire_anthropic_api_lane_async

log = logging.getLogger(__name__)


@dataclass
class AnthropicPaygAdapter:
    """PAYG-routed Anthropic adapter — owns its own AsyncAnthropic client."""

    name: str = "anthropic-payg"
    provider: str = "anthropic"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    # PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28) — capability flags consumed by
    # ``core.llm.adapters.dispatch`` for exact-route tool-side dispatch.
    supports_web_search: bool = True
    supports_text_completion: bool = True
    # ComputerUseCapable — injected on the live request path
    # (``_anthropic_common._maybe_inject_computer_use``).
    supports_computer_use: bool = True
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop.
    # The previous single-slot ``_client`` cache was shared across the
    # daemon's loops and poisoned the connection pool (instant
    # APIConnectionError / eternal hang) — see core/llm/loop_affinity.py.
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("anthropic-payg"), init=False, repr=False
    )

    def computer_tool_param(
        self, *, display_width: int, display_height: int
    ) -> dict[str, Any] | None:
        """ComputerUseCapable — Anthropic ``computer_20251124`` tool definition.

        Delegates to the shared builder so this enumerable contract returns the
        exact param the live request path injects (no drift).
        """
        from core.llm.adapters._anthropic_common import anthropic_computer_tool_param

        return anthropic_computer_tool_param(display_width, display_height)

    def _get_client(self) -> Any:
        from core.config import settings

        api_key = settings.anthropic_api_key
        if not api_key:
            raise RuntimeError(
                "AnthropicPaygAdapter: ANTHROPIC_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``anthropic_api_key`` in settings or use "
                "the anthropic-oauth adapter instead."
            )
        return self._clients.get(lambda: build_async_anthropic_client(api_key))

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        # PR-OAUTH-API-LANES (2026-05-26) — pooled with anthropic-oauth in
        # the same per-account anthropic-api lane (Anthropic rate-limits
        # per-account, not per-source).
        lane_key = f"anthropic-payg:{req.model}"
        async with acquire_anthropic_api_lane_async(lane_key):
            try:
                response = await client.messages.create(**build_create_kwargs(req))
            except Exception as exc:
                self._last_error = exc
                log.warning(
                    "anthropic-payg: messages.create failed model=%s err=%s",
                    req.model,
                    exc,
                )
                raise
        return translate_response(response)

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult:
        """Anthropic ``web_search_20260209`` tool via PAYG endpoint.

        ``model`` is the session's resolved model — honoured when in the
        documented support set, else escalated to ANTHROPIC_PRIMARY
        (PR-WEB-SEARCH-MODEL-HINT, 2026-06-12).
        """
        from core.llm.adapters._capability_impls import (
            anthropic_web_search,
            resolve_web_search_model,
        )

        return await anthropic_web_search(
            self._get_client(),
            query=query,
            max_results=max_results,
            model=resolve_web_search_model(model),
            adapter_name=self.name,
        )

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
    ) -> TextCompletionResult:
        """Single-turn ``messages.create`` — used by compaction / extraction."""
        from core.config import ANTHROPIC_PRIMARY
        from core.llm.adapters._capability_impls import anthropic_complete_text

        return await anthropic_complete_text(
            self._get_client(),
            prompt=prompt,
            system=system,
            model=model or ANTHROPIC_PRIMARY,
            max_tokens=max_tokens,
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        async with client.messages.stream(**build_stream_kwargs(req)) as stream:
            async for text_chunk in stream.text_stream:
                yield StreamEvent(kind="text", payload={"text": text_chunk})
            final = await stream.get_final_message()
            yield StreamEvent(
                kind="stop",
                payload={
                    "stop_reason": getattr(final, "stop_reason", "end_turn") or "end_turn",
                    "usage": {
                        "input_tokens": getattr(final.usage, "input_tokens", 0),
                        "output_tokens": getattr(final.usage, "output_tokens", 0),
                    },
                },
            )

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings

        api_key = settings.anthropic_api_key
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("anthropic_api_key", "missing"),),
                hints=(
                    "Set ``ANTHROPIC_API_KEY`` in your environment or in ~/.geode/config.toml.",
                    "Or use the anthropic-oauth adapter if you have a Claude subscription.",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("anthropic_api_key", f"set ({len(api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY
        from core.llm.model_catalog import model_spec_for_adapter

        ids = [ANTHROPIC_PRIMARY, *ANTHROPIC_FALLBACK_CHAIN]
        seen: set[str] = set()
        models: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            models.append(model_spec_for_adapter(mid, provider=self.provider))
        return models

    def get_quota_windows(self) -> QuotaWindows | None:
        # PAYG is metered per-call; no aggregate quota window.
        return None

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import ANTHROPIC_PRIMARY, settings

        if not settings.anthropic_api_key:
            return None
        return CredentialDetection(
            model=ANTHROPIC_PRIMARY,
            provider=self.provider,
            source_path="settings.anthropic_api_key",
        )


__all__ = ["AnthropicPaygAdapter"]

"""OpenAIPaygAdapter — PAYG (API-key) path to OpenAI models.

Layer 3 adapter for OpenAI provider, source=payg. Owns its own
``AsyncOpenAI`` client bound explicitly to ``OPENAI_API_KEY`` — bypasses the
module-level singleton in ``core.llm.providers.openai`` which routes through
``ProfileRotator`` and would prefer an OAuth profile if one existed. Codex
MCP review 2026-05-23 flagged that singleton sharing as a BLOCKER for source
isolation.

Pair with :class:`CodexOAuthAdapter` (same provider, OAuth path) and
:class:`CodexCliAdapter` (subprocess path).

PR-OPENAI-RESPONSES (2026-06-13): ``acomplete``/``astream`` moved from
Chat Completions to the Responses API via the shared
:func:`core.llm.adapters._openai_common.build_responses_kwargs`
(``backend="platform"``) — completing the migration that
``acomplete_text``/``aweb_search`` started. Responses is OpenAI's
forward-going surface; new features (tool_search deferred loading 등)
are Responses-only. Chat Completions now lives only on the GLM adapters
(z.ai compatibility surface lacks Responses).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.llm.adapters._openai_common import (
    build_async_openai_client,
    build_responses_kwargs,
    openai_computer_tool_param,
    translate_codex_response,
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
from core.orchestration.openai_api_lane import acquire_openai_api_lane_async

log = logging.getLogger(__name__)


@dataclass
class OpenAIPaygAdapter:
    """PAYG-routed OpenAI adapter — owns its own AsyncOpenAI client."""

    name: str = "openai-payg"
    provider: str = "openai"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    # PR-ADAPTER-PATTERN-UNIFICATION — Responses API web_search hosted tool
    # works on the PAYG endpoint. The Codex backend subscription endpoint
    # does not advertise web_search support (frontier audit 2026-05-28).
    supports_web_search: bool = True
    supports_text_completion: bool = True
    # ComputerUseCapable — the GA ``{type: "computer"}`` tool is injected on the
    # live Responses path (``_openai_common._maybe_inject_openai_computer_use``)
    # for GA-capable models only.
    # backend acceptance: platform live-verified 2026-06-17 (gpt-5.5 round-trip)
    supports_computer_use: bool = True
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop
    # (see core/llm/loop_affinity.py).
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("openai-payg"), init=False, repr=False
    )

    def computer_tool_param(
        self, *, display_width: int, display_height: int
    ) -> dict[str, Any] | None:
        """ComputerUseCapable — OpenAI Responses GA ``{type: "computer"}`` param.

        Delegates to the shared builder so this enumerable contract returns the
        exact param the live request path injects (no drift). The GA tool is
        bare: ``display_width`` / ``display_height`` are part of the protocol
        contract (Anthropic uses them) but the GA shape carries no dims — the
        geometry is inferred from the screenshots — so they are accepted and
        ignored here.

        # backend acceptance: platform live-verified 2026-06-17 (gpt-5.5 round-trip)
        """
        del display_width, display_height  # GA {type:"computer"} is bare
        return openai_computer_tool_param()

    def _get_client(self) -> Any:
        from core.config import settings

        api_key = settings.openai_api_key
        if not api_key:
            raise RuntimeError(
                "OpenAIPaygAdapter: OPENAI_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``openai_api_key`` in settings or use "
                "the codex-oauth / codex-cli adapter instead."
            )
        return self._clients.get(lambda: build_async_openai_client(api_key))

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult:
        # ``model`` hint intentionally unused — OpenAI's per-model hosted
        # web_search support matrix is unverified (doc-before-behaviour,
        # CLAUDE.md §4d); OPENAI_PRIMARY stays the search model.
        del model
        from core.config import OPENAI_PRIMARY
        from core.llm.adapters._capability_impls import openai_web_search

        return await openai_web_search(
            self._get_client(),
            query=query,
            max_results=max_results,
            model=OPENAI_PRIMARY,
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
        """Single-turn text completion via the OpenAI Responses API.

        Responses is the forward-going surface
        (per developers.openai.com/api/docs) and the same API the Codex
        backend speaks — sharing it here keeps the per-provider request
        shape uniform with the agent loop's main ``acomplete`` path.
        Chat Completions stays only on GLM adapters where z.ai's
        OpenAI-compatibility surface lacks Responses support.
        """
        from core.config import OPENAI_PRIMARY
        from core.llm.adapters._capability_impls import openai_responses_complete_text

        return await openai_responses_complete_text(
            self._get_client(),
            prompt=prompt,
            system=system,
            model=model or OPENAI_PRIMARY,
            max_tokens=max_tokens,
        )

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        kwargs = build_responses_kwargs(req, backend="platform", adapter_name=self.name)
        # PR-OAUTH-API-LANES (2026-05-26) — pooled with codex-oauth in
        # the same per-account openai-api lane (OpenAI rate-limits
        # per-account, not per-source).
        lane_key = f"openai-payg:{req.model}"
        async with acquire_openai_api_lane_async(lane_key):
            try:
                # Stream + aggregate, mirroring codex-oauth: uniform SSE
                # handling across both Responses backends, and reasoning
                # items arrive as typed output items either way.
                async with client.responses.stream(**kwargs) as stream:
                    accumulated: list[Any] = []
                    async for event in stream:
                        if getattr(event, "type", "") == "response.output_item.done":
                            item = getattr(event, "item", None)
                            if item is not None:
                                accumulated.append(item)
                    final = await stream.get_final_response()
            except Exception as exc:
                self._last_error = exc
                log.warning(
                    "openai-payg: responses.stream failed model=%s err=%s",
                    req.model,
                    exc,
                )
                raise
        return translate_codex_response(final, accumulated_items=accumulated)

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        kwargs = build_responses_kwargs(req, backend="platform", adapter_name=self.name)
        async with client.responses.stream(**kwargs) as stream:
            async for event in stream:
                ev_type = getattr(event, "type", "")
                if ev_type.endswith("output_text.delta"):
                    yield StreamEvent(kind="text", payload={"text": getattr(event, "delta", "")})
                elif ev_type == "response.completed":
                    yield StreamEvent(kind="stop", payload={"stop_reason": "completed"})

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings

        if not settings.openai_api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("openai_api_key", "missing"),),
                hints=(
                    "Set ``OPENAI_API_KEY`` in your environment or in ~/.geode/config.toml.",
                    "Or use codex-oauth (ChatGPT subscription) / codex-cli (local binary).",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("openai_api_key", f"set ({len(settings.openai_api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import OPENAI_FALLBACK_CHAIN, OPENAI_PRIMARY

        ids = [OPENAI_PRIMARY, *OPENAI_FALLBACK_CHAIN]
        seen: set[str] = set()
        models: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            models.append(
                ModelSpec(
                    id=mid,
                    label=mid,
                    context_tokens=128_000,
                    supports_thinking=mid.startswith(("o3", "o4")),
                    supports_tools=True,
                )
            )
        return models

    def get_quota_windows(self) -> QuotaWindows | None:
        return None  # PAYG, metered per call

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import OPENAI_PRIMARY, settings

        if not settings.openai_api_key:
            return None
        return CredentialDetection(
            model=OPENAI_PRIMARY,
            provider=self.provider,
            source_path="settings.openai_api_key",
        )


__all__ = ["OpenAIPaygAdapter"]

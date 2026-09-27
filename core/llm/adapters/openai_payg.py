"""OpenAIPaygAdapter — PAYG (API-key) path to OpenAI models.

Layer 3 adapter for OpenAI provider, source=payg. Owns its own
``AsyncOpenAI`` client bound to a same-endpoint API-key/PAYG profile or the
existing settings key. Subscription and OAuth profiles never supply this
route's credential. A changed selection retires the client without closing
requests that still use it.

Pair with :class:`CodexOAuthAdapter` (same provider, OAuth path).

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

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.config.policy_source import PolicySourcePaths
from core.llm.adapters._openai_common import (
    build_async_openai_client,
    build_responses_kwargs,
    openai_computer_tool_param,
    translate_codex_response,
    translate_responses_stream,
)
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    ModelSpec,
    StreamEvent,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.routing import resolve_routing
from core.orchestration.openai_api_lane import acquire_openai_api_lane_async

log = logging.getLogger(__name__)


@dataclass
class OpenAIPaygAdapter:
    """PAYG-routed OpenAI adapter — owns its own AsyncOpenAI client."""

    name: str = "openai-payg"
    provider: str = "openai"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    # Responses web search is supported on this API-key route; subscription
    # support and request shaping remain owned by CodexOAuthAdapter.
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

    routing_sources: PolicySourcePaths | None = field(default=None, repr=False)

    def _credential(self, model: str = "") -> tuple[str, str, str]:
        """Read the selected PAYG key, endpoint and non-secret provenance."""
        from core.config import settings
        from core.llm.registry import get_provider_spec

        spec = get_provider_spec(self.provider)
        if spec is None:
            raise RuntimeError("PAYG provider composition is not registered")
        base_url = os.environ.get("OPENAI_BASE_URL") or spec.default_base_url
        target = resolve_routing(
            model,
            provider=self.provider,
            source=self.source,
            base_url=base_url,
            sources=self.routing_sources,
        )
        if target is not None:
            return target.profile.key, target.base_url, f"auth profile:{target.profile.name}"
        return settings.openai_api_key, base_url, "settings.openai_api_key"

    def _get_client(self, model: str = "") -> Any:
        api_key, base_url, _ = self._credential(model)
        if not api_key:
            raise RuntimeError(
                "OpenAIPaygAdapter: OPENAI_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``openai_api_key`` in settings or use "
                "the codex-oauth adapter instead."
            )
        return self._clients.get(
            lambda: build_async_openai_client(api_key, base_url=base_url),
            identity=hashlib.sha256(f"{base_url}\0{api_key}".encode()).hexdigest(),
        )

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = "", effort: str | None = None
    ) -> WebSearchResult:
        # Responses web search accepts the selected model and its reasoning
        # effort together; keep the same model as the calling session.
        # ref: https://developers.openai.com/api/docs/guides/tools-web-search
        from core.config import OPENAI_PRIMARY
        from core.llm.adapters._capability_impls import openai_effort_kwargs, openai_web_search

        openai_effort_kwargs(model or OPENAI_PRIMARY, effort)
        return await openai_web_search(
            self._get_client(model or OPENAI_PRIMARY),
            query=query,
            max_results=max_results,
            model=model or OPENAI_PRIMARY,
            adapter_name=self.name,
            effort=effort,
        )

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
        effort: str | None = None,
    ) -> TextCompletionResult:
        """Single-turn text completion via the OpenAI Responses API.

        Responses is the forward-going surface
        (per developers.openai.com/api/docs) and the same API the Codex
        backend speaks — sharing it here keeps the per-provider request
        shape uniform with the agent loop's main ``acomplete`` path.
        GLM adapters preserve their documented account-compatible
        Chat Completions route separately.
        """
        from core.config import OPENAI_PRIMARY
        from core.llm.adapters._capability_impls import (
            openai_effort_kwargs,
            openai_responses_complete_text,
        )

        openai_effort_kwargs(model or OPENAI_PRIMARY, effort)
        return await openai_responses_complete_text(
            self._get_client(model or OPENAI_PRIMARY),
            prompt=prompt,
            system=system,
            model=model or OPENAI_PRIMARY,
            max_tokens=max_tokens,
            effort=effort,
        )

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        kwargs = build_responses_kwargs(req, backend="platform", adapter_name=self.name)
        client = self._get_client(req.model)
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
                    "openai-payg: responses.stream failed model=%s error_type=%s",
                    req.model,
                    type(exc).__name__,
                )
                raise
        return translate_codex_response(final, accumulated_items=accumulated)

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        kwargs = build_responses_kwargs(req, backend="platform", adapter_name=self.name)
        client = self._get_client(req.model)
        async with client.responses.stream(**kwargs) as stream:
            async for event in translate_responses_stream(stream):
                yield event

    def test_environment(self) -> EnvironmentReport:
        api_key, _, _ = self._credential()
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("openai_api_key", "missing"),),
                hints=(
                    "Set ``OPENAI_API_KEY`` in your environment or in ~/.geode/config.toml.",
                    "Or use codex-oauth (ChatGPT subscription).",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("openai_api_key", f"set ({len(api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import OPENAI_FALLBACK_CHAIN, OPENAI_PRIMARY
        from core.llm.model_catalog import model_ids_for_source, model_spec_for_adapter

        return [
            model_spec_for_adapter(mid, provider=self.provider)
            for mid in model_ids_for_source(
                provider=self.provider,
                source=self.source,
                configured=(OPENAI_PRIMARY, *OPENAI_FALLBACK_CHAIN),
            )
        ]

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import OPENAI_PRIMARY

        api_key, _, source_path = self._credential()
        if not api_key:
            return None
        return CredentialDetection(
            model=OPENAI_PRIMARY,
            provider=self.provider,
            source_path=source_path,
        )


__all__ = ["OpenAIPaygAdapter"]

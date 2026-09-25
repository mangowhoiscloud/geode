"""GlmPaygAdapter — PAYG (api/paas/v4) endpoint for ZhipuAI GLM.

Layer 3 adapter for the ``glm`` provider, source=payg. Uses
``api.z.ai/api/paas/v4`` (PAYG, metered) with a matching API-key/PAYG profile
or ``settings.zai_api_key``. GLM speaks the OpenAI Chat Completions wire
shape so the adapter reuses :mod:`core.llm.adapters._openai_common`
helpers (``build_messages`` + ``translate_chat_response``).

Coding Plan eligibility is a separate product policy from API compatibility.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.llm.adapters._openai_common import (
    build_async_openai_client,
    translate_chat_response,
)
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    Message,
    ModelSpec,
    StreamEvent,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.providers.glm import build_glm_chat_kwargs, translate_glm_stream
from core.llm.strategies.plan_registry import resolve_payg_profile

log = logging.getLogger(__name__)


@dataclass
class GlmPaygAdapter:
    """PAYG-routed GLM adapter (api/paas/v4 endpoint).

    Owns its own ``AsyncOpenAI`` client bound explicitly to the PAYG endpoint so a
    subscription Coding Plan profile in :class:`ProfileStore` cannot
    silently shadow the PAYG path (mirrors the
    :class:`AnthropicPaygAdapter` isolation pattern — Codex MCP
    2026-05-23 BLOCKER).
    """

    name: str = "glm-payg"
    provider: str = "glm"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    # PAYG native search and the subscription MCP product are separate routes.
    supports_web_search: bool = True
    supports_text_completion: bool = True
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop
    # (see core/llm/loop_affinity.py).
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("glm-payg"), init=False, repr=False
    )

    def _credential(self) -> tuple[str, str, str]:
        """Read the selected PAYG key, endpoint and non-secret provenance."""
        from core.config import settings
        from core.llm.registry import get_provider_spec

        spec = get_provider_spec(self.provider)
        if spec is None:
            raise RuntimeError("PAYG provider composition is not registered")
        base_url = spec.default_base_url
        profile = resolve_payg_profile(self.provider, base_url=base_url)
        if profile is not None:
            return profile.key, base_url, f"auth profile:{profile.name}"
        return settings.zai_api_key, base_url, "settings.zai_api_key"

    def _get_client(self) -> Any:
        api_key, base_url, _ = self._credential()
        if not api_key:
            raise RuntimeError(
                "GlmPaygAdapter: ZAI_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``zai_api_key`` in settings."
            )
        return self._clients.get(
            lambda: build_async_openai_client(api_key, base_url=base_url),
            identity=hashlib.sha256(f"{base_url}\0{api_key}".encode()).hexdigest(),
        )

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult:
        # ``model`` hint intentionally unused — z.ai's per-model web_search
        # support matrix is unverified (doc-before-behaviour, CLAUDE.md §4d).
        del model
        from core.config import GLM_PRIMARY
        from core.llm.adapters._capability_impls import glm_web_search

        return await glm_web_search(
            self._get_client(),
            query=query,
            max_results=max_results,
            model=GLM_PRIMARY,
            adapter_name=self.name,
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
        from core.config import GLM_PRIMARY

        result = await self.acomplete(
            AdapterCallRequest(
                model=model or GLM_PRIMARY,
                messages=(Message(role="user", content=prompt),),
                system_prompt=system,
                max_tokens=max_tokens,
                effort=effort if effort is not None else "",
            )
        )
        return TextCompletionResult(text=result.text, usage=result.usage)

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        kwargs = build_glm_chat_kwargs(req, adapter_name=self.name, source=self.source)
        client = self._get_client()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._last_error = exc
            log.warning(
                "glm-payg: chat.completions.create failed model=%s error_type=%s",
                req.model,
                type(exc).__name__,
            )
            raise
        return translate_chat_response(
            response, provider=self.provider, adapter_name=self.name, model=req.model
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        kwargs = build_glm_chat_kwargs(req, adapter_name=self.name, source=self.source, stream=True)
        client = self._get_client()
        chunks = await client.chat.completions.create(**kwargs)
        async for event in translate_glm_stream(chunks):
            yield event

    def test_environment(self) -> EnvironmentReport:
        api_key, _, _ = self._credential()
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("zai_api_key", "missing"),),
                hints=("Set ``ZAI_API_KEY`` in your environment or in ~/.geode/config.toml.",),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("zai_api_key", f"set ({len(api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import GLM_FALLBACK_CHAIN, GLM_PRIMARY
        from core.llm.model_catalog import model_ids_for_source, model_spec_for_adapter

        return [
            model_spec_for_adapter(mid, provider=self.provider)
            for mid in model_ids_for_source(
                provider=self.provider,
                source=self.source,
                configured=(GLM_PRIMARY, *GLM_FALLBACK_CHAIN),
            )
        ]

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import GLM_PRIMARY

        api_key, _, source_path = self._credential()
        if not api_key:
            return None
        return CredentialDetection(
            model=GLM_PRIMARY,
            provider=self.provider,
            source_path=source_path,
        )


__all__ = ["GlmPaygAdapter"]

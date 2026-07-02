"""GlmPaygAdapter — PAYG (api/paas/v4) endpoint for ZhipuAI GLM.

Layer 3 adapter for the ``glm`` provider, source=payg. Uses
``api.z.ai/api/paas/v4`` (PAYG, metered) with the API key in
``settings.zai_api_key``. GLM speaks the OpenAI Chat Completions wire
shape so the adapter reuses :mod:`core.llm.adapters._openai_common`
helpers (``build_messages`` + ``translate_chat_response``).

Pair with :class:`GlmCodingPlanAdapter` (same provider, subscription
``api/coding/paas/v4`` endpoint). Codex MCP A2 (v0.99.44) Follow-up F.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.llm.adapters._openai_common import (
    build_async_openai_client,
    build_messages,
    translate_chat_response,
    translate_tool,
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
from core.llm.providers.glm import build_glm_reasoning_extra_body

log = logging.getLogger(__name__)


@dataclass
class GlmPaygAdapter:
    """PAYG-routed GLM adapter (api/paas/v4 endpoint).

    Owns its own ``AsyncOpenAI`` client bound explicitly to
    ``settings.zai_api_key`` + :data:`core.config.GLM_PAYG_BASE_URL` so a
    subscription Coding Plan profile in :class:`ProfileStore` cannot
    silently shadow the PAYG path (mirrors the
    :class:`AnthropicPaygAdapter` isolation pattern — Codex MCP
    2026-05-23 BLOCKER).
    """

    name: str = "glm-payg"
    provider: str = "glm"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    # PR-ADAPTER-PATTERN-UNIFICATION — z.ai native web_search Chat Completions
    # tool works on PAYG. Coding Plan subscription endpoint untested for
    # web_search (frontier audit 2026-05-28); glm_coding_plan adapter keeps
    # supports_web_search=False until verified.
    supports_web_search: bool = True
    supports_text_completion: bool = True
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop
    # (see core/llm/loop_affinity.py).
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("glm-payg"), init=False, repr=False
    )

    def _get_client(self) -> Any:
        from core.config import GLM_PAYG_BASE_URL, settings

        api_key = settings.zai_api_key
        if not api_key:
            raise RuntimeError(
                "GlmPaygAdapter: ZAI_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``zai_api_key`` in settings or use "
                "the glm-coding-plan adapter (subscription endpoint) instead."
            )
        return self._clients.get(
            lambda: build_async_openai_client(api_key, base_url=GLM_PAYG_BASE_URL)
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
    ) -> TextCompletionResult:
        from core.config import GLM_PRIMARY
        from core.llm.adapters._capability_impls import openai_chat_complete_text

        return await openai_chat_complete_text(
            self._get_client(),
            prompt=prompt,
            system=system,
            model=model or GLM_PRIMARY,
            max_tokens=max_tokens,
        )

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": build_messages(req),
            "max_tokens": req.max_tokens,
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.tools:
            from core.llm.adapters._openai_common import cap_tools

            translated = [translate_tool(t) for t in req.tools]
            kwargs["tools"] = cap_tools(translated, model=req.model, adapter_name="glm-payg")
            tc = _translate_tool_choice(req.tool_choice)
            if tc is not None:
                kwargs["tool_choice"] = tc
        if req.stop_sequences:
            kwargs["stop"] = list(req.stop_sequences)
        _reasoning_xb = build_glm_reasoning_extra_body(req.model)
        if _reasoning_xb is not None:
            kwargs["extra_body"] = _reasoning_xb
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._last_error = exc
            log.warning(
                "glm-payg: chat.completions.create failed model=%s err=%s",
                req.model,
                exc,
            )
            raise
        return translate_chat_response(response)

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": build_messages(req),
            "max_tokens": req.max_tokens,
            "stream": True,
        }
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        _reasoning_xb = build_glm_reasoning_extra_body(req.model)
        if _reasoning_xb is not None:
            kwargs["extra_body"] = _reasoning_xb
        async for chunk in await client.chat.completions.create(**kwargs):
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue
            delta = getattr(choice, "delta", None)
            text_chunk = getattr(delta, "content", None) if delta else None
            if text_chunk:
                yield StreamEvent(kind="text", payload={"text": text_chunk})
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason is not None:
                yield StreamEvent(kind="stop", payload={"stop_reason": finish_reason})

    def test_environment(self) -> EnvironmentReport:
        from core.config import settings

        if not settings.zai_api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("zai_api_key", "missing"),),
                hints=(
                    "Set ``ZAI_API_KEY`` in your environment or in ~/.geode/config.toml.",
                    "Or use glm-coding-plan (Coding Plan subscription).",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("zai_api_key", f"set ({len(settings.zai_api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import GLM_FALLBACK_CHAIN, GLM_PRIMARY
        from core.llm.model_catalog import model_spec_for_adapter

        ids = [GLM_PRIMARY, *GLM_FALLBACK_CHAIN]
        seen: set[str] = set()
        models: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            models.append(model_spec_for_adapter(mid, provider=self.provider))
        return models

    def get_quota_windows(self) -> QuotaWindows | None:
        return None  # PAYG metered per-call

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import GLM_PRIMARY, settings

        if not settings.zai_api_key:
            return None
        return CredentialDetection(
            model=GLM_PRIMARY,
            provider=self.provider,
            source_path="settings.zai_api_key",
        )


def _translate_tool_choice(tc: str | dict[str, Any]) -> str | dict[str, Any] | None:
    """Adapter-neutral ``tool_choice`` → GLM Chat Completions wire shape.

    GLM is OpenAI-compatible (Chat Completions nested ``function`` shape).
    Reuses the GLM helper in :func:`core.llm.tool_choice.normalize` to
    accept the AgenticLoop's Anthropic-shape dicts (``{"type": "auto"}``
    etc.).
    """
    from core.llm.tool_choice import normalize

    return normalize("glm", tc)


__all__ = ["GlmPaygAdapter"]

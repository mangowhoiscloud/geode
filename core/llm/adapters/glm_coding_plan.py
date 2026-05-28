"""GlmCodingPlanAdapter — Coding Plan (api/coding/paas/v4) subscription endpoint.

Layer 3 adapter for the ``glm`` provider, source=subscription. ZhipuAI's
Coding Plan binds an API key to a subscription that gets routed to the
``api.z.ai/api/coding/paas/v4`` endpoint (distinct from PAYG's
``/api/paas/v4``). Calling a Coding Plan key against the PAYG endpoint
silently bypasses the subscription quota and incurs metered billing —
that's why the picker / adapter source must be honoured.

The bound Plan API key is resolved via
:func:`core.llm.providers.glm._resolve_glm_endpoint` which checks the
GEODE ``ProfileStore`` for a ``glm-coding-*`` Plan registered via
``/login``. PAYG fallback explicitly excluded — the picker source
``subscription`` means subscription, not "best effort".

Codex MCP A2 (v0.99.44) Follow-up F.
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
    SOURCE_SUBSCRIPTION,
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

log = logging.getLogger(__name__)


@dataclass
class GlmCodingPlanAdapter:
    """Subscription-routed GLM adapter (Coding Plan endpoint).

    Forces the Coding Plan binding from the ProfileStore — if no Plan
    is registered (only PAYG api_key set), raises so the operator can't
    silently fall back to PAYG when the picker resolved ``subscription``.
    """

    name: str = "glm-coding-plan"
    provider: str = "glm"
    source: str = SOURCE_SUBSCRIPTION
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION
    # PR-ADAPTER-PATTERN-UNIFICATION — Coding Plan subscription endpoint
    # speaks the same Chat Completions wire shape as the PAYG endpoint, so
    # web_search + text_completion both work. The frontier audit
    # (2026-05-28) did not directly confirm Coding Plan web_search support,
    # but z.ai's Coding Plan terms state full PAYG-API parity; we advertise
    # both capabilities and let the dispatch fallback chain skip on actual
    # 400 / 1113 errors if support diverges.
    supports_web_search: bool = True
    supports_text_completion: bool = True
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key, base_url = _resolve_coding_plan_endpoint()
        if not api_key:
            raise RuntimeError(
                "GlmCodingPlanAdapter: no GLM Coding Plan profile registered. "
                "Run ``/login glm-coding-pro`` (or the matching Plan slug) inside "
                "GEODE, or use the glm-payg adapter for the metered PAYG path."
            )
        self._client = build_async_openai_client(api_key, base_url=base_url)
        return self._client

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
            from core.llm.tool_choice import normalize

            translated = [translate_tool(t) for t in req.tools]
            kwargs["tools"] = cap_tools(translated, model=req.model, adapter_name="glm-coding-plan")
            tc = normalize("glm", req.tool_choice)
            if tc is not None:
                kwargs["tool_choice"] = tc
        if req.stop_sequences:
            kwargs["stop"] = list(req.stop_sequences)
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._last_error = exc
            log.warning(
                "glm-coding-plan: chat.completions.create failed model=%s err=%s",
                req.model,
                exc,
            )
            raise
        return translate_chat_response(response)

    async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
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
        api_key, base_url = _resolve_coding_plan_endpoint()
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("glm_coding_plan_profile", "missing"),),
                hints=(
                    "Register a Coding Plan via ``/login glm-coding-pro`` inside GEODE.",
                    "Or use glm-payg (PAYG api/paas/v4 endpoint).",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(
                ("glm_coding_plan_profile", f"key ({len(api_key)} chars)"),
                ("endpoint", base_url),
            ),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import GLM_FALLBACK_CHAIN, GLM_PRIMARY

        ids = [GLM_PRIMARY, *GLM_FALLBACK_CHAIN]
        seen: set[str] = set()
        models: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            models.append(
                ModelSpec(
                    id=mid,
                    label=f"{mid} (via Coding Plan)",
                    context_tokens=128_000,
                    supports_thinking=False,
                    supports_tools=True,
                )
            )
        return models

    def get_quota_windows(self) -> QuotaWindows | None:
        # GLM Coding Plan does not expose a programmatic quota surface yet.
        return None

    def detect_credential(self) -> CredentialDetection | None:
        api_key, base_url = _resolve_coding_plan_endpoint()
        if not api_key:
            return None
        from core.config import GLM_PRIMARY

        return CredentialDetection(
            model=GLM_PRIMARY,
            provider=self.provider,
            source_path=f"ProfileStore (glm-coding-*) → {base_url}",
        )


def _resolve_coding_plan_endpoint() -> tuple[str, str]:
    """Return ``(api_key, base_url)`` for the registered Coding Plan, else
    ``("", "")``.

    Walks :func:`core.llm.strategies.plan_registry.resolve_routing` for the
    ``glm-coding-*`` Plan (the same path :func:`core.llm.providers.glm._resolve_glm_endpoint`
    uses). If no Plan is bound, returns empty strings so the adapter
    refuses rather than silently falling back to PAYG.
    """
    try:
        from core.llm.strategies.plan_registry import resolve_routing

        target = resolve_routing("glm-5.1")
        if target is not None and target.profile.key:
            return target.profile.key, target.base_url
    except Exception:
        log.debug("glm-coding-plan: ProfileStore lookup failed", exc_info=True)
    return "", ""


__all__ = ["GlmCodingPlanAdapter"]

"""Persisted GLM Coding Plan route, subject to the provider's tool policy.

As of 2026-09-24 GEODE is absent from Z.AI's supported-tools list. Keep
credential resolution separate, but reject execution before client creation.
Existing subscription profiles never fall through to metered API billing.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.config.policy_source import PolicySourcePaths
from core.llm.adapters._openai_common import (
    build_async_openai_client,
    translate_chat_response,
)
from core.llm.adapters.base import (
    SOURCE_SUBSCRIPTION,
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
    # Subscription search is a distinct MCP server, not PAYG native search.
    supports_web_search: bool = False
    supports_text_completion: bool = True
    routing_sources: PolicySourcePaths | None = field(default=None, repr=False)
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop
    # (see core/llm/loop_affinity.py).
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("glm-coding-plan"), init=False, repr=False
    )

    def _get_client(self, model: str = "") -> Any:
        from core.config import GLM_PRIMARY
        from core.llm.model_catalog import require_model_source_available

        require_model_source_available(
            model or GLM_PRIMARY, provider=self.provider, source=self.source
        )
        api_key, base_url = _resolve_coding_plan_endpoint(self.routing_sources, model=model)
        if not api_key:
            raise RuntimeError(
                "GlmCodingPlanAdapter: no GLM Coding Plan profile registered. "
                "Run ``/login glm-coding-pro`` (or the matching Plan slug) inside "
                "GEODE, or use the glm-payg adapter for the metered PAYG path."
            )
        return self._clients.get(lambda: build_async_openai_client(api_key, base_url=base_url))

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        kwargs = build_glm_chat_kwargs(req, adapter_name=self.name, source=self.source)
        client = self._get_client(req.model)
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._last_error = exc
            log.warning(
                "glm-coding-plan: chat.completions.create failed model=%s error_type=%s",
                req.model,
                type(exc).__name__,
            )
            raise
        return translate_chat_response(
            response, provider=self.provider, adapter_name=self.name, model=req.model
        )

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult:
        raise NotImplementedError(
            "GLM Coding Plan native web search is not supported. Z.AI documents "
            "subscription search through its separate Web Search MCP server."
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

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        kwargs = build_glm_chat_kwargs(req, adapter_name=self.name, source=self.source, stream=True)
        client = self._get_client(req.model)
        chunks = await client.chat.completions.create(**kwargs)
        async for event in translate_glm_stream(chunks):
            yield event

    def test_environment(self) -> EnvironmentReport:
        from core.config import GLM_PRIMARY
        from core.llm.model_catalog import model_source_unavailable_reason

        reason = model_source_unavailable_reason(
            GLM_PRIMARY, provider=self.provider, source=self.source
        )
        if reason:
            return EnvironmentReport(
                ok=False,
                checks=(("glm_coding_plan_policy", "unsupported_tool"),),
                hints=(reason,),
            )
        api_key, base_url = _resolve_coding_plan_endpoint(self.routing_sources)
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
        from core.llm.model_catalog import model_ids_for_source, model_spec_for_adapter

        return [
            model_spec_for_adapter(mid, label=f"{mid} (via Coding Plan)", provider=self.provider)
            for mid in model_ids_for_source(
                provider=self.provider,
                source=self.source,
                configured=(GLM_PRIMARY, *GLM_FALLBACK_CHAIN),
            )
        ]

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import GLM_PRIMARY
        from core.llm.model_catalog import model_source_unavailable_reason

        if model_source_unavailable_reason(GLM_PRIMARY, provider=self.provider, source=self.source):
            return None
        api_key, base_url = _resolve_coding_plan_endpoint(self.routing_sources)
        if not api_key:
            return None
        return CredentialDetection(
            model=GLM_PRIMARY,
            provider=self.provider,
            source_path=f"ProfileStore (glm-coding-*) → {base_url}",
        )


def _resolve_coding_plan_endpoint(
    routing_sources: PolicySourcePaths | None = None, *, model: str = ""
) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` for the registered Coding Plan, else
    ``("", "")``.

    Validates the PlanRegistry selection against this adapter's provider/source
    before detection, diagnostics, or client creation can consume it.
    """
    try:
        from core.config import GLM_PRIMARY
        from core.llm.registry import get_provider_spec
        from core.llm.routing import resolve_routing
        from core.llm.strategies.plans import PlanKind

        target = resolve_routing(
            model or GLM_PRIMARY, provider="glm", source="subscription", sources=routing_sources
        )
        if target is None or not target.profile.key:
            return "", ""
        spec = get_provider_spec(target.plan.provider)
        if (
            target.plan.kind is not PlanKind.SUBSCRIPTION
            or spec is None
            or spec.profile.provider != "glm"
            or spec.credential.source != SOURCE_SUBSCRIPTION
            or target.profile.provider != spec.credential.account_provider
        ):
            return "", ""
        return target.profile.key, target.base_url
    except Exception:
        log.debug("glm-coding-plan: ProfileStore lookup failed", exc_info=True)
    return "", ""


__all__ = ["GlmCodingPlanAdapter"]

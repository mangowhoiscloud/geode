"""AnthropicPaygAdapter — PAYG (API-key) path to Anthropic models.

Layer 3 adapter (paperclip ``ServerAdapterModule`` shape). Calls the Anthropic
SDK with a same-endpoint API-key/PAYG profile or the existing settings key,
never another credential type from the legacy global priority. This adapter
owns its client via :func:`_anthropic_common.build_async_anthropic_client`.
This is the only built-in Anthropic execution path.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from core.llm.adapters._anthropic_common import (
    anthropic_effort_kwargs,
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
    StreamEvent,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.errors import LLMResponseValidationError
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.strategies.plan_registry import resolve_payg_profile
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

    def _credential(self) -> tuple[str, str, str]:
        """Read the selected PAYG key, endpoint and non-secret provenance."""
        from core.config import settings
        from core.llm.registry import get_provider_spec

        spec = get_provider_spec(self.provider)
        if spec is None:
            raise RuntimeError("PAYG provider composition is not registered")
        base_url = os.environ.get("ANTHROPIC_BASE_URL") or spec.default_base_url
        profile = resolve_payg_profile(self.provider, base_url=base_url)
        if profile is not None:
            return profile.key, base_url, f"auth profile:{profile.name}"
        return settings.anthropic_api_key, base_url, "settings.anthropic_api_key"

    def _get_client(self) -> Any:
        api_key, base_url, _ = self._credential()
        if not api_key:
            raise RuntimeError(
                "AnthropicPaygAdapter: ANTHROPIC_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``anthropic_api_key`` in settings."
            )
        return self._clients.get(
            lambda: build_async_anthropic_client(api_key),
            identity=hashlib.sha256(f"{base_url}\0{api_key}".encode()).hexdigest(),
        )

    def _require_model_allowed(self, model: str, *, base_url: str) -> None:
        from core.llm.model_catalog import require_model_source_available

        require_model_source_available(
            model, provider=self.provider, source=self.source, base_url=base_url
        )

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        anthropic_effort_kwargs(req.model, req.effort)
        client = self._get_client()
        self._require_model_allowed(req.model, base_url=str(client.base_url))
        # The API-key path has its own concurrency lane.
        lane_key = f"anthropic-payg:{req.model}"
        async with acquire_anthropic_api_lane_async(lane_key):
            try:
                response = await client.messages.create(
                    **build_create_kwargs(req, base_url=str(client.base_url))
                )
                return translate_response(response)
            except Exception as exc:
                self._last_error = exc
                log.warning(
                    "anthropic-payg: completion failed model=%s error_type=%s",
                    req.model,
                    type(exc).__name__,
                )
                raise

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = "", effort: str | None = None
    ) -> WebSearchResult:
        """Anthropic hosted web search via the PAYG endpoint.

        ``model`` is the session's resolved model — honoured when in the
        documented support set, else escalated to ANTHROPIC_PRIMARY
        (PR-WEB-SEARCH-MODEL-HINT, 2026-06-12).
        """
        from core.llm.adapters._capability_impls import (
            anthropic_web_search,
            resolve_web_search_model,
        )

        # The actual (possibly cached) SDK endpoint owns the lifecycle policy;
        # do not project Anthropic API retirements onto a custom host.
        search_model = resolve_web_search_model(model)
        anthropic_effort_kwargs(search_model, effort)
        client = self._get_client()
        # Reject before web-search capability routing can replace the choice.
        if model:
            self._require_model_allowed(model, base_url=str(client.base_url))
        self._require_model_allowed(search_model, base_url=str(client.base_url))
        return await anthropic_web_search(
            client,
            query=query,
            max_results=max_results,
            model=search_model,
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
        """Single-turn ``messages.create`` — used by compaction / extraction."""
        from core.config import ANTHROPIC_PRIMARY
        from core.llm.adapters._capability_impls import anthropic_complete_text

        completion_model = model or ANTHROPIC_PRIMARY
        anthropic_effort_kwargs(completion_model, effort)
        client = self._get_client()
        self._require_model_allowed(completion_model, base_url=str(client.base_url))
        return await anthropic_complete_text(
            client,
            prompt=prompt,
            system=system,
            model=completion_model,
            max_tokens=max_tokens,
            effort=effort,
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        anthropic_effort_kwargs(req.model, req.effort)
        client = self._get_client()
        self._require_model_allowed(req.model, base_url=str(client.base_url))
        kwargs = build_stream_kwargs(req, base_url=str(client.base_url))
        edits = kwargs.get("extra_body", {}).get("context_management", {}).get("edits", [])
        messages_api = (
            client.beta.messages
            if any(edit.get("type") == "compact_20260112" for edit in edits)
            else client.messages
        )
        async with messages_api.stream(**kwargs) as stream:
            async for text_chunk in stream.text_stream:
                yield StreamEvent(kind="text", payload={"text": text_chunk})
            final = await stream.get_final_message()
            try:
                result = translate_response(final)
            except LLMResponseValidationError as exc:
                yield StreamEvent(kind="usage", payload=asdict(exc.completed_result.usage))
                raise
            for block in result.anthropic_content:
                if block.get("type") == "thinking":
                    yield StreamEvent(
                        kind="thinking",
                        payload={
                            "text": block.get("thinking", ""),
                            "signature": block["signature"],
                        },
                    )
            for tool_use in result.tool_uses:
                yield StreamEvent(kind="tool_use", payload=tool_use)
            usage = asdict(result.usage)
            yield StreamEvent(kind="usage", payload=usage)
            yield StreamEvent(
                kind="stop",
                payload={
                    "stop_reason": result.stop_reason,
                    "usage": usage,
                    "anthropic_content": result.anthropic_content,
                    "stop_details": result.stop_details,
                },
            )

    def test_environment(self) -> EnvironmentReport:
        api_key, _, _ = self._credential()
        if not api_key:
            return EnvironmentReport(
                ok=False,
                checks=(("anthropic_api_key", "missing"),),
                hints=(
                    "Set ``ANTHROPIC_API_KEY`` in your environment or in ~/.geode/config.toml.",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("anthropic_api_key", f"set ({len(api_key)} chars)"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY
        from core.llm.model_catalog import model_ids_for_source, model_spec_for_adapter

        return [
            model_spec_for_adapter(mid, provider=self.provider)
            for mid in model_ids_for_source(
                self.provider,
                self.source,
                configured=(ANTHROPIC_PRIMARY, *ANTHROPIC_FALLBACK_CHAIN),
            )
        ]

    def detect_credential(self) -> CredentialDetection | None:
        from core.config import ANTHROPIC_PRIMARY

        api_key, _, source_path = self._credential()
        if not api_key:
            return None
        return CredentialDetection(
            model=ANTHROPIC_PRIMARY,
            provider=self.provider,
            source_path=source_path,
        )


__all__ = ["AnthropicPaygAdapter"]

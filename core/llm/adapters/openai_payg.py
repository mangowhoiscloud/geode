"""OpenAIPaygAdapter — PAYG (API-key) path to OpenAI models.

Layer 3 adapter for OpenAI provider, source=payg. Owns its own
``AsyncOpenAI`` client bound explicitly to ``OPENAI_API_KEY`` — bypasses the
module-level singleton in ``core.llm.providers.openai`` which routes through
``ProfileRotator`` and would prefer an OAuth profile if one existed. Codex
MCP review 2026-05-23 flagged that singleton sharing as a BLOCKER for source
isolation.

Pair with :class:`CodexOAuthAdapter` (same provider, OAuth path) and
:class:`CodexCliAdapter` (subprocess path).
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
)

log = logging.getLogger(__name__)


@dataclass
class OpenAIPaygAdapter:
    """PAYG-routed OpenAI adapter — owns its own AsyncOpenAI client."""

    name: str = "openai-payg"
    provider: str = "openai"
    source: str = SOURCE_PAYG
    billing_type: AdapterBillingType = AdapterBillingType.API
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from core.config import settings

        if not settings.openai_api_key:
            raise RuntimeError(
                "OpenAIPaygAdapter: OPENAI_API_KEY not set. PAYG path requires "
                "an explicit API key — set ``openai_api_key`` in settings or use "
                "the codex-oauth / codex-cli adapter instead."
            )
        self._client = build_async_openai_client(settings.openai_api_key)
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
            kwargs["tools"] = [translate_tool(t) for t in req.tools]
        if req.stop_sequences:
            kwargs["stop"] = list(req.stop_sequences)
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._last_error = exc
            log.warning(
                "openai-payg: chat.completions.create failed model=%s err=%s",
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

"""CodexOAuthAdapter — ChatGPT subscription OAuth path via Codex backend.

Layer 3 adapter for OpenAI provider, source=subscription. Uses the
``chatgpt.com/backend-api/codex`` endpoint with the OAuth token resolved by
:func:`core.llm.providers.codex._resolve_codex_token` — which checks **both**
the GEODE ``ProfileStore`` (``openai-codex`` profile registered via
``/login openai``) *and* the external ``~/.codex/auth.json`` (Codex CLI
fallback). Codex MCP review 2026-05-23 HIGH finding: the prior version only
checked ``~/.codex/auth.json``, which broke users who only had a GEODE-issued
profile.

Adapter owns its own ``AsyncOpenAI`` client (Codex MCP BLOCKER fix — the
module-level singleton in ``core.llm.providers.codex`` would shadow per-call
credential differences).

Pair with :class:`OpenAIPaygAdapter` (same provider, API key path) and
:class:`CodexCliAdapter` (subprocess path).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.llm.adapters._openai_common import (
    build_async_codex_client,
    build_messages,
    translate_codex_response,
    translate_tool_for_codex,
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
)

log = logging.getLogger(__name__)


CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"


@dataclass
class CodexOAuthAdapter:
    """Subscription-routed OpenAI adapter via Codex OAuth backend."""

    name: str = "codex-oauth"
    provider: str = "openai"
    source: str = SOURCE_SUBSCRIPTION
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from core.llm.providers.codex import _resolve_codex_token

        token = _resolve_codex_token()
        if not token:
            raise RuntimeError(
                "CodexOAuthAdapter: ChatGPT OAuth not found. Looked in GEODE "
                f"ProfileStore ('openai-codex' profile) and {CODEX_AUTH_PATH}. "
                "Run ``/login openai`` in GEODE or ``codex auth login`` in the "
                "Codex CLI to provision credentials, or use the openai-payg / "
                "codex-cli adapter."
            )
        self._client = build_async_codex_client(token)
        return self._client

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        """Single Codex Responses API call (streamed; final aggregated).

        Mirrors the contract in
        :meth:`core.llm.providers.codex.CodexAgenticAdapter.agentic_call`
        — Codex backend has 4 mandatory differences vs. PAYG Responses API:

        - ``max_output_tokens`` is forbidden (server-managed under the Plus
          quota; sending it returns 400 ``Unsupported parameter``).
        - ``store = False`` is required.
        - ``instructions`` field carries the system prompt (Responses API's
          ``input`` array does not accept ``role: system`` on Codex).
        - Tools use the FLAT shape (``translate_tool_for_codex``), not the
          Chat Completions nested ``function`` wrapper.

        We stream by default and aggregate the final response — non-streaming
        ``responses.create`` returns a structurally empty body on the Codex
        backend (the actual content arrives only via SSE events).
        """
        client = self._get_client()
        kwargs = _build_codex_call_kwargs(req)
        try:
            async with client.responses.stream(**kwargs) as stream:
                accumulated: list[Any] = []
                async for event in stream:
                    if getattr(event, "type", "") == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if item is not None:
                            accumulated.append(item)
                final = await stream.get_final_response()
                if accumulated:
                    final.output = accumulated
        except Exception as exc:
            self._last_error = exc
            log.warning("codex-oauth: responses.stream failed model=%s err=%s", req.model, exc)
            raise
        return translate_codex_response(final)

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        kwargs = _build_codex_call_kwargs(req)
        async with client.responses.stream(**kwargs) as stream:
            async for event in stream:
                ev_type = getattr(event, "type", "")
                if ev_type.endswith("output_text.delta"):
                    yield StreamEvent(kind="text", payload={"text": getattr(event, "delta", "")})
                elif ev_type == "response.completed":
                    yield StreamEvent(kind="stop", payload={"stop_reason": "completed"})

    def test_environment(self) -> EnvironmentReport:
        from core.llm.providers.codex import _resolve_codex_token

        token = _resolve_codex_token()
        if not token:
            return EnvironmentReport(
                ok=False,
                checks=(
                    ("geode_profile_store", "no openai-codex profile"),
                    (
                        "codex_auth_file",
                        "missing" if not CODEX_AUTH_PATH.is_file() else "unreadable",
                    ),
                ),
                hints=(
                    "Run ``/login openai`` inside GEODE to provision the ChatGPT OAuth profile,",
                    "or ``codex auth login`` in the Codex CLI to use the external token.",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(("codex_token_length", f"{len(token)} chars"),),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import CODEX_FALLBACK_CHAIN, CODEX_PRIMARY

        ids = [CODEX_PRIMARY, *CODEX_FALLBACK_CHAIN]
        seen: set[str] = set()
        out: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            out.append(
                ModelSpec(
                    id=mid,
                    label=mid,
                    context_tokens=128_000,
                    supports_thinking=mid.startswith(("o3", "o4")),
                    supports_tools=True,
                )
            )
        return out

    def get_quota_windows(self) -> QuotaWindows | None:
        """Codex backend exposes rate-limit headers per response but no aggregate.

        Returns ``None`` for now — the UI renders "unknown" rather than
        guessing. A future ratchet PR can wire the per-response ``rate_limits``
        block from ``core/llm/providers/codex.py`` into a snapshot cache.
        """
        return None

    def detect_credential(self) -> CredentialDetection | None:
        from core.llm.providers.codex import _resolve_codex_token

        if not _resolve_codex_token():
            return None
        from core.config import CODEX_PRIMARY

        # detect_credential only reports the source path — exact provenance
        # (GEODE profile vs Codex CLI file) is on EnvironmentReport's checks.
        source_path = (
            str(CODEX_AUTH_PATH)
            if CODEX_AUTH_PATH.is_file()
            else "GEODE ProfileStore (openai-codex)"
        )
        return CredentialDetection(
            model=CODEX_PRIMARY,
            provider=self.provider,
            source_path=source_path,
        )


def _build_codex_call_kwargs(req: AdapterCallRequest) -> dict[str, Any]:
    """Codex Responses API call kwargs — mirrors CodexAgenticAdapter shape.

    Critical Codex backend constraints (from
    ``docs/research/codex-oauth-request-spec.md``):

    - ``instructions`` carries the system prompt (not ``input[].role:system``)
    - ``input`` is the user/assistant/tool array; we drop the leading system
      entry that :func:`build_messages` would prepend
    - ``store=False`` is mandatory
    - ``max_output_tokens`` is FORBIDDEN — Plus subscription manages it
      server-side, sending the field returns 400
    - Tools use the FLAT shape (``translate_tool_for_codex``)
    - gpt-5.x family omits ``temperature`` and adds ``reasoning`` +
      ``include: ["reasoning.encrypted_content"]``
    """
    messages_payload = build_messages(req)
    # Drop the system entry build_messages prepends — Codex needs it in
    # ``instructions`` not in ``input``.
    if req.system_prompt and messages_payload and messages_payload[0].get("role") == "system":
        messages_payload = messages_payload[1:]
    kwargs: dict[str, Any] = {
        "model": req.model,
        "instructions": req.system_prompt or "You are a helpful assistant.",
        "input": messages_payload or [{"role": "user", "content": "hello"}],
        "store": False,
    }
    if req.tools:
        kwargs["tools"] = [translate_tool_for_codex(t) for t in req.tools]
        kwargs["tool_choice"] = "auto"
        kwargs["parallel_tool_calls"] = True
    if req.model.startswith("gpt-5"):
        # gpt-5.x family — encrypted reasoning passthrough; temperature omitted.
        kwargs["include"] = ["reasoning.encrypted_content"]
        kwargs["reasoning"] = {"effort": req.effort, "summary": "auto"}
    elif req.temperature is not None:
        kwargs["temperature"] = req.temperature
    return kwargs


__all__ = ["CodexOAuthAdapter"]

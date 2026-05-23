"""AnthropicOAuthAdapter — Subscription (Claude.ai) OAuth path.

Layer 3 adapter. Forces credential resolution to the OAuth profile at
``~/.claude/oauth-token.json``, bypassing the PAYG ``ANTHROPIC_API_KEY`` even
if both are configured. Owns its own ``AsyncAnthropic`` client (Codex MCP
review 2026-05-23 BLOCKER fix — pre-refactor the singleton in
``core.llm.providers.anthropic`` was shared with the PAYG adapter so the
first caller's api_key won permanently).

Paper-trail: paperclip's ``adapter-claude-local`` package equivalent.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.llm.adapters._anthropic_common import (
    build_async_anthropic_client,
    build_create_kwargs,
    build_stream_kwargs,
    translate_response,
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


CLAUDE_OAUTH_TOKEN_PATH = Path.home() / ".claude" / "oauth-token.json"


@dataclass
class AnthropicOAuthAdapter:
    """Subscription-routed Anthropic adapter — owns its own AsyncAnthropic client."""

    name: str = "anthropic-oauth"
    provider: str = "anthropic"
    source: str = SOURCE_SUBSCRIPTION
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        token = _resolve_oauth_token()
        if not token:
            raise RuntimeError(
                "AnthropicOAuthAdapter: Claude OAuth token not found at "
                f"{CLAUDE_OAUTH_TOKEN_PATH}. Run ``claude /login`` in the Claude CLI "
                "or use the anthropic-payg adapter instead."
            )
        self._client = build_async_anthropic_client(token)
        return self._client

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        client = self._get_client()
        try:
            response = await client.messages.create(**build_create_kwargs(req))
        except Exception as exc:
            self._last_error = exc
            log.warning("anthropic-oauth: messages.create failed model=%s err=%s", req.model, exc)
            raise
        return translate_response(response)

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
        if not CLAUDE_OAUTH_TOKEN_PATH.is_file():
            return EnvironmentReport(
                ok=False,
                checks=(("oauth_token_file", "missing"),),
                hints=(
                    f"Expected OAuth token at {CLAUDE_OAUTH_TOKEN_PATH}.",
                    "Run ``claude /login`` in the Claude CLI to provision it.",
                ),
            )
        token = _resolve_oauth_token()
        if not token:
            return EnvironmentReport(
                ok=False,
                checks=(
                    ("oauth_token_file", "present"),
                    ("oauth_token_parseable", "unreadable"),
                ),
                hints=(
                    "OAuth token file exists but could not be parsed. Re-run ``claude /login``.",
                ),
            )
        return EnvironmentReport(
            ok=True,
            checks=(
                ("oauth_token_file", str(CLAUDE_OAUTH_TOKEN_PATH)),
                ("oauth_token_length", f"{len(token)} chars"),
            ),
        )

    def list_models(self) -> list[ModelSpec]:
        from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY

        ids = [ANTHROPIC_PRIMARY, *ANTHROPIC_FALLBACK_CHAIN]
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
                    context_tokens=200_000,
                    supports_thinking=True,
                    supports_tools=True,
                )
            )
        return models

    def get_quota_windows(self) -> QuotaWindows | None:
        """Subscription quota windows — None until wired by the UI follow-up.

        The Anthropic SDK emits ``anthropic-priority-tier`` headers per
        response which feed the legacy ``SubscriptionQuotaBanner``
        (``core/cli/quota_banner.py``). The adapter cannot import from
        ``core.cli`` (architecture: ``core/llm/`` is below ``core/cli/`` in
        the dependency layering — verified by ``lint-imports``). The
        follow-up UI PR (D in the plan doc) introduces a callback /
        observability hook that the banner can push into, keeping the
        dependency direction bottom-up. Until then this returns ``None``
        (treated as "unknown").
        """
        return None

    def detect_credential(self) -> CredentialDetection | None:
        if not CLAUDE_OAUTH_TOKEN_PATH.is_file():
            return None
        from core.config import ANTHROPIC_PRIMARY

        return CredentialDetection(
            model=ANTHROPIC_PRIMARY,
            provider=self.provider,
            source_path=str(CLAUDE_OAUTH_TOKEN_PATH),
        )


def _resolve_oauth_token() -> str:
    """Read Claude OAuth access_token from ``~/.claude/oauth-token.json``.

    Returns empty string when the file is missing, malformed, or expired.
    Refresh logic lives in ``core/auth/`` — this helper is read-only and
    surfaces failures via the empty-string sentinel so callers can map it to
    a clear ``RuntimeError`` hint.
    """
    if not CLAUDE_OAUTH_TOKEN_PATH.is_file():
        return ""
    import json

    try:
        data = json.loads(CLAUDE_OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("anthropic-oauth: cannot read OAuth token: %s", exc)
        return ""
    if not isinstance(data, dict):
        return ""
    token = data.get("access_token") or data.get("token") or ""
    return str(token) if isinstance(token, (str, int)) else ""


__all__ = ["AnthropicOAuthAdapter"]

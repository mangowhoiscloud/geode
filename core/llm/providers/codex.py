"""OpenAI Codex provider — subscription quota via chatgpt.com/backend-api/codex.

Uses Codex OAuth token (from ~/.codex/auth.json) to call OpenAI models
through ChatGPT's backend API, consuming subscription quota instead
of API billing.

Requires:
- Streaming (store=False, stream=True)
- instructions parameter
- ChatGPT-Account-ID + originator headers
- Responses API (client.responses.stream)

Grounded from: Hermes Agent (runtime_provider.py, auxiliary_client.py)
and OpenClaw (openai-codex-provider.ts).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.auth.jwt_claims import decode_jwt_claims

if TYPE_CHECKING:
    from core.config.policy_source import PolicySourcePaths
    from core.llm.routing import RoutingTarget

log = logging.getLogger(__name__)

# H11-tail: DEFAULT_CODEX_MODEL / CODEX_FALLBACK_MODELS were dead module
# aliases (boot-frozen copies of CODEX_PRIMARY / CODEX_FALLBACK_CHAIN) with no
# consumer. Removed; live values come from ``core.config`` via function-local
# imports so a routing.toml reload is seen without a restart.

# 2026-07-29: this module no longer owns any SDK client. ``CodexOAuthAdapter``
# builds and caches its own (``build_async_codex_client`` + a loop-affine
# cache invalidated on token rotation); what remains here is token resolution.


@dataclass(frozen=True)
class _ResolvedCodexToken:
    """Runtime Codex OAuth token plus cache identity metadata."""

    token: str
    source: str
    expires_at: float = 0.0

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]

    @property
    def has_expired(self) -> bool:
        return self.expires_at > 0 and time.time() >= self.expires_at


def _extract_account_id(token: str) -> str:
    """Extract chatgpt_account_id from Codex OAuth JWT."""
    auth_claim = decode_jwt_claims(token).get("https://api.openai.com/auth", {})
    return str(auth_claim.get("chatgpt_account_id", "")) if isinstance(auth_claim, dict) else ""


def get_codex_oauth_metadata() -> dict[str, object] | None:
    """Return plan/account metadata from the currently resolved Codex JWT."""
    try:
        token = resolve_codex_token()
    except Exception:
        return None
    payload = decode_jwt_claims(token)
    if not payload:
        return None
    auth_claim = payload.get("https://api.openai.com/auth", {})
    if not isinstance(auth_claim, dict):
        auth_claim = {}
    return {
        "plan_type": auth_claim.get("chatgpt_plan_type"),
        "account_id": auth_claim.get("chatgpt_account_id"),
        "user_id": auth_claim.get("chatgpt_user_id"),
        "expires_at": payload.get("exp"),
    }


def is_codex_oauth_available() -> bool:
    """Return whether the Codex OAuth source currently resolves."""
    try:
        return bool(resolve_codex_token())
    except Exception:
        return False


def build_codex_oauth_headers(token: str) -> dict[str, str]:
    """Build the headers Codex OAuth requires on every Responses-API call.

    The Codex backend (``chatgpt.com/backend-api/codex``) rejects requests
    without the ``originator: codex_cli_rs`` marker and the
    ``ChatGPT-Account-ID`` extracted from the OAuth JWT. Returning a fresh
    dict (rather than caching) keeps the helper safe across threads — the
    caller mutates the dict's lifetime as it pleases.
    """
    account_id = _extract_account_id(token)
    headers: dict[str, str] = {"originator": "codex_cli_rs"}
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def _resolve_codex_routing(
    *,
    force_refresh: bool = False,
    model: str = "",
    sources: PolicySourcePaths | None = None,
    allow_refreshable: bool = False,
) -> RoutingTarget | None:
    """Hydrate the managed owner, then admit one subscription route."""
    from core.auth.codex_cli_oauth import sync_codex_cli_profile
    from core.config import CODEX_BASE_URL
    from core.llm.routing import resolve_routing
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()
    sync_codex_cli_profile(store, force_refresh=force_refresh)
    target = resolve_routing(
        model,
        provider="openai",
        source="subscription",
        sources=sources,
        allow_refreshable=allow_refreshable,
    )
    if target is not None and target.base_url.rstrip("/") != CODEX_BASE_URL.rstrip("/"):
        raise RuntimeError("Codex plan endpoint does not match the subscription backend")
    return target


def _resolve_codex_token_info(
    *,
    force_refresh: bool = False,
    model: str = "",
    sources: PolicySourcePaths | None = None,
) -> _ResolvedCodexToken | None:
    """Resolve only an eligible request token, never a refreshable expired token."""
    target = _resolve_codex_routing(force_refresh=force_refresh, model=model, sources=sources)
    if target is None:
        return None
    return _ResolvedCodexToken(
        token=target.profile.key,
        source=f"profile:{target.profile.name}",
        expires_at=float(target.profile.expires_at or 0.0),
    )


def resolve_codex_token() -> str:
    """Resolve Codex OAuth token."""
    resolved = _resolve_codex_token_info(force_refresh=True)
    return resolved.token if resolved else ""

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
import threading
import time
from dataclasses import dataclass
from typing import Any

from core.auth.jwt_claims import decode_jwt_claims
from core.config import CODEX_BASE_URL

log = logging.getLogger(__name__)

# H11-tail: DEFAULT_CODEX_MODEL / CODEX_FALLBACK_MODELS were dead module
# aliases (boot-frozen copies of CODEX_PRIMARY / CODEX_FALLBACK_CHAIN) with no
# consumer. Removed; live values come from ``core.config`` via function-local
# imports so a routing.toml reload is seen without a restart.

_codex_client: Any = None
_codex_client_fingerprint = ""
_codex_lock = threading.Lock()
_async_codex_client: Any = None
_async_codex_client_fingerprint = ""
_async_codex_lock = threading.Lock()


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


def _resolve_codex_token_info(*, force_refresh: bool = False) -> _ResolvedCodexToken | None:
    """Resolve Codex OAuth token with cache metadata.

    v0.52.4 — checks two sources, GEODE-issued first:
      1. ProfileStore for an ``openai-codex`` profile (the one created
         by ``/login openai`` device flow). This is the token the
         user just registered through GEODE.
      2. ~/.codex/auth.json (external Codex CLI store) — fallback for
         users who only have Codex CLI logged in.

    Without (1) the geode-registered ``openai-codex-geode`` plan would
    be invisible to the actual LLM call path and the OAuth login wizard
    would do nothing for users who don't also run Codex CLI.

    v0.99.x — returns token identity metadata so SDK clients can be
    rebuilt when Codex CLI refreshes ``~/.codex/auth.json`` after the
    daemon has already cached a client. This mirrors Hermes' credential
    pool resync pattern: when the backing auth store changes, stale
    runtime entries are replaced instead of kept until process restart.
    """
    try:
        from core.wiring.container import get_profile_store

        store = get_profile_store()
        if store is not None:
            # v0.52.5 — two passes so a GEODE-issued OAuth token
            # (managed_by="") wins over a borrowed Codex CLI token
            # (managed_by="codex-cli"). Pre-fix the iteration was
            # insertion-order — and ``build_auth`` adds external CLIs
            # *before* reading auth.toml, so an active Codex CLI session
            # silently shadowed the geode token.
            for profile in store.list_all():
                if (
                    profile.provider == "openai-codex"
                    and profile.is_available
                    and profile.key
                    and not profile.managed_by
                ):
                    return _ResolvedCodexToken(
                        token=profile.key,
                        source=f"profile:{profile.name}",
                        expires_at=float(profile.expires_at or 0.0),
                    )
            for profile in store.list_all():
                if profile.provider == "openai-codex" and profile.is_available and profile.key:
                    return _ResolvedCodexToken(
                        token=profile.key,
                        source=f"profile:{profile.name}",
                        expires_at=float(profile.expires_at or 0.0),
                    )
    except Exception:
        log.debug("GEODE openai-codex profile lookup failed", exc_info=True)

    try:
        from core.auth.codex_cli_oauth import read_codex_cli_credentials

        creds = read_codex_cli_credentials(force_refresh=force_refresh)
        if creds:
            resolved = _ResolvedCodexToken(
                token=creds["access_token"],
                source="codex-cli:~/.codex/auth.json",
                expires_at=float(creds.get("expires_at", 0.0) or 0.0),
            )
            if resolved.has_expired:
                log.warning("Codex CLI OAuth token is expired; refusing stale runtime token")
                return None
            return resolved
    except Exception:
        log.debug("Codex CLI token resolution failed", exc_info=True)
    return None


def _resolve_codex_token() -> str:
    """Resolve Codex OAuth token."""
    resolved = _resolve_codex_token_info(force_refresh=True)
    return resolved.token if resolved else ""


def _get_codex_client() -> Any:
    """Lazy import and return cached Codex client (thread-safe)."""
    global _codex_client, _codex_client_fingerprint
    resolved = _resolve_codex_token_info(force_refresh=True)
    if not resolved:
        log.warning("Codex OAuth token not available")
        return None
    with _codex_lock:
        if _codex_client is not None and _codex_client_fingerprint == resolved.fingerprint:
            return _codex_client

        import openai

        _codex_client = openai.OpenAI(
            api_key=resolved.token,
            base_url=CODEX_BASE_URL,
            default_headers=build_codex_oauth_headers(resolved.token),
            max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
        )
        _codex_client_fingerprint = resolved.fingerprint
        log.info(
            "Codex OAuth client rebuilt from %s token=%s",
            resolved.source,
            resolved.fingerprint,
        )
    return _codex_client


def _get_async_codex_client() -> Any:
    """Lazy import and return cached async Codex client (thread-safe)."""
    global _async_codex_client, _async_codex_client_fingerprint
    resolved = _resolve_codex_token_info(force_refresh=True)
    if not resolved:
        log.warning("Codex OAuth token not available")
        return None
    with _async_codex_lock:
        if (
            _async_codex_client is not None
            and _async_codex_client_fingerprint == resolved.fingerprint
        ):
            return _async_codex_client

        import openai

        # PR-CODEX-OUTPUT-NULL (2026-05-28) — mirror the adapter
        # builder: install the parse_response workaround so the
        # legacy provider path is also safe on openai >= 2.26.
        from core.llm.adapters._codex_sdk_workaround import install as _install

        _install()

        _async_codex_client = openai.AsyncOpenAI(
            api_key=resolved.token,
            base_url=CODEX_BASE_URL,
            default_headers=build_codex_oauth_headers(resolved.token),
            max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
        )
        _async_codex_client_fingerprint = resolved.fingerprint
        log.info(
            "Async Codex OAuth client rebuilt from %s token=%s",
            resolved.source,
            resolved.fingerprint,
        )
    return _async_codex_client


def reset_codex_client() -> None:
    """Reset cached client (e.g. after token refresh)."""
    global _async_codex_client, _async_codex_client_fingerprint, _codex_client
    global _codex_client_fingerprint
    with _codex_lock:
        _codex_client = None
        _codex_client_fingerprint = ""
    with _async_codex_lock:
        _async_codex_client = None
        _async_codex_client_fingerprint = ""

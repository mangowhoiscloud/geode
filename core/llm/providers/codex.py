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

import json
import logging
import threading
from typing import Any

from core.config import CODEX_BASE_URL, CODEX_FALLBACK_CHAIN, CODEX_PRIMARY

log = logging.getLogger(__name__)

DEFAULT_CODEX_MODEL = CODEX_PRIMARY
CODEX_FALLBACK_MODELS = CODEX_FALLBACK_CHAIN

_codex_client: Any = None
_codex_lock = threading.Lock()
_async_codex_client: Any = None
_async_codex_lock = threading.Lock()


def _extract_account_id(token: str) -> str:
    """Extract chatgpt_account_id from Codex OAuth JWT."""
    import base64

    parts = token.split(".")
    if len(parts) < 2:
        return ""
    try:
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        auth_claim = payload.get("https://api.openai.com/auth", {})
        result: str = auth_claim.get("chatgpt_account_id", "")
        return result
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return ""


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


def _resolve_codex_token() -> str:
    """Resolve Codex OAuth token.

    v0.52.4 — checks two sources, GEODE-issued first:
      1. ProfileStore for an ``openai-codex`` profile (the one created
         by ``/login openai`` device flow). This is the token the
         user just registered through GEODE.
      2. ~/.codex/auth.json (external Codex CLI store) — fallback for
         users who only have Codex CLI logged in.

    Without (1) the geode-registered ``openai-codex-geode`` plan would
    be invisible to the actual LLM call path and the OAuth login wizard
    would do nothing for users who don't also run Codex CLI.
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
                    return profile.key
            for profile in store.list_all():
                if profile.provider == "openai-codex" and profile.is_available and profile.key:
                    return profile.key
    except Exception:
        log.debug("GEODE openai-codex profile lookup failed", exc_info=True)

    try:
        from core.auth.codex_cli_oauth import read_codex_cli_credentials

        creds = read_codex_cli_credentials()
        if creds:
            return creds["access_token"]
    except Exception:
        log.debug("Codex CLI token resolution failed", exc_info=True)
    return ""


def _get_codex_client() -> Any:
    """Lazy import and return cached Codex client (thread-safe)."""
    global _codex_client
    if _codex_client is None:
        with _codex_lock:
            if _codex_client is None:
                import openai

                token = _resolve_codex_token()
                if not token:
                    log.warning("Codex OAuth token not available")
                    return None

                _codex_client = openai.OpenAI(
                    api_key=token,
                    base_url=CODEX_BASE_URL,
                    default_headers=build_codex_oauth_headers(token),
                    max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
                )
    return _codex_client


def _get_async_codex_client() -> Any:
    """Lazy import and return cached async Codex client (thread-safe)."""
    global _async_codex_client
    if _async_codex_client is None:
        with _async_codex_lock:
            if _async_codex_client is None:
                import openai

                token = _resolve_codex_token()
                if not token:
                    log.warning("Codex OAuth token not available")
                    return None

                # PR-CODEX-OUTPUT-NULL (2026-05-28) — mirror the adapter
                # builder: install the parse_response workaround so the
                # legacy provider path is also safe on openai >= 2.26.
                from core.llm.adapters._codex_sdk_workaround import install as _install

                _install()

                _async_codex_client = openai.AsyncOpenAI(
                    api_key=token,
                    base_url=CODEX_BASE_URL,
                    default_headers=build_codex_oauth_headers(token),
                    max_retries=0,  # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION
                )
    return _async_codex_client


def reset_codex_client() -> None:
    """Reset cached client (e.g. after token refresh)."""
    global _async_codex_client, _codex_client
    with _codex_lock:
        _codex_client = None
    with _async_codex_lock:
        _async_codex_client = None

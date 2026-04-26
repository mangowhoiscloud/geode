"""OpenAI Codex provider — Plus quota via chatgpt.com/backend-api/codex.

Uses Codex OAuth token (from ~/.codex/auth.json) to call OpenAI models
through ChatGPT's backend API, consuming Plus subscription quota instead
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
from core.llm.fallback import CircuitBreaker

log = logging.getLogger(__name__)

DEFAULT_CODEX_MODEL = CODEX_PRIMARY
CODEX_FALLBACK_MODELS = CODEX_FALLBACK_CHAIN

_codex_client: Any = None
_codex_lock = threading.Lock()
_codex_circuit_breaker = CircuitBreaker()


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


def _resolve_codex_token() -> str:
    """Resolve Codex OAuth token.

    v0.52.4 — checks two sources, GEODE-issued first:
      1. ProfileStore for an ``openai-codex`` profile (the one created
         by ``/login oauth openai`` device flow). This is the token the
         user just registered through GEODE.
      2. ~/.codex/auth.json (external Codex CLI store) — fallback for
         users who only have Codex CLI logged in.

    Without (1) the geode-registered ``openai-codex-geode`` plan would
    be invisible to the actual LLM call path and the OAuth login wizard
    would do nothing for users who don't also run Codex CLI.
    """
    try:
        from core.lifecycle.container import get_profile_store

        store = get_profile_store()
        if store is not None:
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

                account_id = _extract_account_id(token)
                headers: dict[str, str] = {
                    "originator": "codex_cli_rs",
                }
                if account_id:
                    headers["ChatGPT-Account-ID"] = account_id

                _codex_client = openai.OpenAI(
                    api_key=token,
                    base_url=CODEX_BASE_URL,
                    default_headers=headers,
                )
    return _codex_client


def reset_codex_client() -> None:
    """Reset cached client (e.g. after token refresh)."""
    global _codex_client
    with _codex_lock:
        _codex_client = None


def get_circuit_breaker() -> CircuitBreaker:
    """Return the module-level Codex circuit breaker."""
    return _codex_circuit_breaker


# ---------------------------------------------------------------------------
# CodexAgenticAdapter — Responses API streaming adapter
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from core.llm.errors import UserCancelledError  # noqa: E402
from core.llm.providers.openai import (  # noqa: E402
    OpenAIAgenticAdapter,
    _convert_messages_to_openai,
)
from core.llm.router import call_with_failover  # noqa: E402


class CodexAgenticAdapter(OpenAIAgenticAdapter):
    """OpenAI Codex adapter — Plus quota via Responses API streaming.

    Uses chatgpt.com/backend-api/codex with Codex OAuth token.
    """

    @property
    def provider_name(self) -> str:
        return "openai-codex"

    @property
    def fallback_chain(self) -> list[str]:
        return list(CODEX_FALLBACK_CHAIN)

    def _resolve_config(self, model: str) -> tuple[str, str | None]:
        token = _resolve_codex_token()
        return token, CODEX_BASE_URL

    async def agentic_call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, str] | str,
        max_tokens: int,
        temperature: float,
        thinking_budget: int = 0,
        effort: str = "high",
    ) -> Any | None:
        """Codex agentic call via Responses API streaming."""
        client = _get_codex_client()
        if client is None:
            self.last_error = ValueError("Codex OAuth token not configured")
            log.warning("No Codex OAuth token for agentic loop")
            return None

        if not _codex_circuit_breaker.can_execute():
            self.last_error = RuntimeError("Codex circuit breaker is OPEN")
            log.warning("Codex circuit breaker is OPEN, skipping call")
            return None

        # Build Responses API input from messages
        oai_messages = _convert_messages_to_openai(system, messages)
        # Convert to Responses API input format
        resp_input: list[dict[str, Any]] = []
        for msg in oai_messages:
            if msg.get("role") == "system":
                continue  # instructions parameter handles this
            resp_input.append(msg)

        failover_models = [model] + [m for m in self.fallback_chain if m != model]

        async def _do_call(m: str) -> Any:
            def _sync_call() -> Any:
                with client.responses.stream(
                    model=m,
                    instructions=system or "You are a helpful assistant.",
                    input=resp_input or [{"role": "user", "content": "hello"}],
                    store=False,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ) as stream:
                    for _event in stream:
                        pass
                    return stream.get_final_response()

            return await asyncio.to_thread(_sync_call)

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except Exception as exc:
            self.last_error = exc
            log.warning("Codex agentic LLM call failed", exc_info=True)
            _codex_circuit_breaker.record_failure()
            return None

        if response is None:
            _codex_circuit_breaker.record_failure()
            return None

        _codex_circuit_breaker.record_success()

        # Track token usage
        if hasattr(response, "usage") and response.usage:
            from core.llm.token_tracker import get_tracker

            actual_model = used_model or model
            in_tok = response.usage.input_tokens or 0
            out_tok = response.usage.output_tokens or 0
            get_tracker().record(actual_model, in_tok, out_tok)

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        # Normalize Responses API output to standard format
        return _normalize_responses_api(response)


def _normalize_responses_api(response: Any) -> dict[str, Any]:
    """Convert Responses API response to normalized format for agentic loop."""
    out_text = ""
    tool_calls: list[dict[str, Any]] = []

    for block in response.output:
        if hasattr(block, "content"):
            for c in block.content:
                if hasattr(c, "text"):
                    out_text += c.text
        if hasattr(block, "type") and block.type == "function_call":
            tool_calls.append(
                {
                    "id": getattr(block, "call_id", getattr(block, "id", "")),
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": block.arguments,
                    },
                }
            )

    result: dict[str, Any] = {
        "role": "assistant",
        "content": out_text,
        "model": response.model,
        "stop_reason": "end_turn" if not tool_calls else "tool_use",
    }
    if tool_calls:
        result["tool_calls"] = tool_calls

    usage = response.usage
    if usage:
        result["usage"] = {
            "input_tokens": usage.input_tokens or 0,
            "output_tokens": usage.output_tokens or 0,
        }

    return result

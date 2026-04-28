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
    _convert_messages_to_responses,
    _tools_to_openai,
)
from core.llm.router import call_with_failover  # noqa: E402


# v0.52.7 — gpt-5.x family supports reasoning + omits temperature on Codex
# backend. Pattern from Hermes ``_fixed_temperature_for_model`` (which returns
# OMIT for these models) + Codex Rust ``Reasoning`` field on ResponsesApiRequest.
# All current Codex-routed models (gpt-5.5, gpt-5.4, gpt-5.4-mini,
# gpt-5.3-codex) are gpt-5.x — we gate by prefix so future spec additions
# (gpt-5.6, gpt-5.x-codex-spark, etc.) inherit the same handling.
def _is_codex_reasoning_model(model: str) -> bool:
    """Return True for Codex models that accept ``reasoning`` + omit temperature."""
    return model.startswith("gpt-5")


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

        # v0.53.3 — use the Responses-API converter (was previously the
        # Chat-Completions converter ``_convert_messages_to_openai``,
        # which produced ``{role:"assistant", content:None,
        # tool_calls:[...]}`` shapes that Codex Plus rejects with
        # ``input[i].content must be array or string, got null``). The
        # Responses API expects per-item-type wire shapes:
        # function_call (no content field), function_call_output
        # (output not content), message (content always string/array,
        # never null). OpenAI PAYG already used this converter
        # (``openai.py:496``); Codex Plus inherits the same behaviour
        # now. Spec-grounded against openai-python TypedDicts
        # ResponseFunctionToolCallParam / FunctionCallOutput /
        # ResponseOutputMessageParam.
        oai_messages = _convert_messages_to_responses(system, messages)
        resp_input: list[dict[str, Any]] = []
        for msg in oai_messages:
            if msg.get("role") == "system":
                continue  # ``instructions`` kwarg below handles system prompt
            resp_input.append(msg)

        # v0.53.3 — pre-send observability. Logs one structured line so
        # any future ``input[i].content == null`` (or other shape regressions)
        # surface in the daemon log without needing a wire trace. Per-item
        # summary: index, role|type, content type/length (or "<absent>"),
        # extra keys. Single line, capped at first 30 items.
        if log.isEnabledFor(logging.DEBUG) or any(
            (msg.get("content") is None) for msg in resp_input[:30]
        ):
            _shape: list[str] = []
            for _i, _m in enumerate(resp_input[:30]):
                _kind = _m.get("type") or _m.get("role") or "<unknown>"
                if "content" in _m:
                    _c = _m["content"]
                    _ct = (
                        "None"
                        if _c is None
                        else f"str({len(_c)})"
                        if isinstance(_c, str)
                        else f"list({len(_c)})"
                        if isinstance(_c, list)
                        else type(_c).__name__
                    )
                    _shape.append(f"[{_i}]{_kind} content={_ct}")
                elif "output" in _m:
                    _o = _m["output"]
                    _ot = (
                        "None"
                        if _o is None
                        else f"str({len(_o)})"
                        if isinstance(_o, str)
                        else f"list({len(_o)})"
                        if isinstance(_o, list)
                        else type(_o).__name__
                    )
                    _shape.append(f"[{_i}]{_kind} output={_ot}")
                else:
                    _shape.append(f"[{_i}]{_kind} keys={sorted(_m.keys())}")
            log.warning("Codex resp_input shape: %s", " | ".join(_shape))

        failover_models = [model] + [m for m in self.fallback_chain if m != model]

        # v0.52.7 — build kwargs to match Codex Rust ``ResponsesApiRequest``
        # struct + Hermes ``agent/transports/codex.py`` shape. Spec doc:
        # ``docs/research/codex-oauth-request-spec.md`` (3-codebase grounded).
        oai_tools = _tools_to_openai(tools)
        tc_val = tool_choice.get("type", "auto") if isinstance(tool_choice, dict) else tool_choice
        is_reasoning = _is_codex_reasoning_model(model)

        async def _do_call(m: str) -> Any:
            def _sync_call() -> Any:
                # v0.52.6 hotfix — chatgpt.com/backend-api/codex/responses
                # rejects ``max_output_tokens`` with 400 ("Unsupported
                # parameter"). The Plus subscription manages output limits
                # server-side; client cap is forbidden. PAYG
                # ``OpenAIAgenticAdapter`` still sends it for api.openai.com.
                kwargs: dict[str, Any] = {
                    "model": m,
                    "instructions": system or "You are a helpful assistant.",
                    "input": resp_input or [{"role": "user", "content": "hello"}],
                    "store": False,
                }
                # v0.52.7 — function-calling parity with Hermes / Codex Rust.
                # Pre-fix ``tools`` was dropped silently → Codex agentic loop
                # had no way to invoke any tool, breaking the entire native
                # tool dispatch path on Plus subscriptions.
                if oai_tools:
                    kwargs["tools"] = oai_tools
                    kwargs["tool_choice"] = tc_val or "auto"
                    # Hermes default; Codex Rust forwards prompt setting.
                    kwargs["parallel_tool_calls"] = True
                # v0.52.7 — encrypted reasoning passthrough. Without
                # ``include`` + ``reasoning`` the gpt-5.x-codex models lose
                # their reasoning state across turns (Codex backend strips
                # the encrypted block from non-include responses).
                if is_reasoning:
                    kwargs["include"] = ["reasoning.encrypted_content"]
                    kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
                    # gpt-5.x-codex omits temperature per Hermes
                    # ``_fixed_temperature_for_model``.
                else:
                    kwargs["temperature"] = temperature
                # v0.53.3 — Codex Rust pattern: accumulate output items
                # from ``response.output_item.done`` events as they arrive.
                # The Codex Plus backend (chatgpt.com/backend-api/codex)
                # omits the ``output`` field from its
                # ``response.completed`` event payload (verified against
                # codex-rs ``ResponseCompleted`` struct in
                # ``codex-api/src/sse/responses.rs:120-128`` which has no
                # ``output`` field at all). The OpenAI Python SDK's
                # ``stream.get_final_response()`` therefore returns
                # ``response.output == []`` even though the model
                # generated visible text (proven by ``usage.output_tokens
                # > usage.output_tokens_details.reasoning_tokens``).
                # We mirror the Rust client: trust ``output_item.done``
                # events for the conversation items and use
                # ``get_final_response()`` only as a shell for usage /
                # status / response_id.
                with client.responses.stream(**kwargs) as stream:
                    accumulated_items: list[Any] = []
                    for event in stream:
                        if getattr(event, "type", "") == "response.output_item.done":
                            item = getattr(event, "item", None)
                            if item is not None:
                                accumulated_items.append(item)
                    final = stream.get_final_response()
                    # Always overwrite — never trust SDK's reconstructed
                    # output for Codex Plus (it's structurally empty per
                    # the backend's SSE contract).
                    if accumulated_items:
                        final.output = accumulated_items
                    return final

            return await asyncio.to_thread(_sync_call)

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except Exception as exc:
            # v0.53.2 — preserve BillingError propagation so AgenticLoop
            # renders the quota_exhausted IPC panel. Pre-fix the generic
            # Exception catch swallowed BillingError into self.last_error
            # and returned None, breaking the v0.53.0 fail-fast governance
            # for Codex Plus quota exhaustion.
            from core.llm.errors import BillingError

            if isinstance(exc, BillingError):
                _codex_circuit_breaker.record_failure()
                raise
            self.last_error = exc
            log.warning("Codex agentic LLM call failed", exc_info=True)
            _codex_circuit_breaker.record_failure()
            return None

        if response is None:
            _codex_circuit_breaker.record_failure()
            return None

        _codex_circuit_breaker.record_success()

        # Track token usage at the provider layer for the per-provider
        # cost ledger. The agentic loop's _track_usage runs separately on
        # the normalized AgenticResponse below; both paths read the same
        # underlying response.usage so the numbers match.
        if hasattr(response, "usage") and response.usage:
            from core.llm.token_tracker import get_tracker

            actual_model = used_model or model
            in_tok = response.usage.input_tokens or 0
            out_tok = response.usage.output_tokens or 0
            get_tracker().record(actual_model, in_tok, out_tok)

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        # v0.53.1 — return the standard AgenticResponse dataclass so the
        # agentic loop's _track_usage (response.usage attribute access)
        # works for Codex too. Pre-fix this adapter returned a raw dict
        # via _normalize_responses_api → loop crashed with
        # ``'dict' object has no attribute 'usage'`` on first /model
        # claude-* → gpt-5.5 switch (production incident 2026-04-27).
        # The Anthropic + OpenAI PAYG adapters already use the standard
        # normaliser; this brings Codex into parity.
        from core.llm.agentic_response import normalize_openai_responses

        return normalize_openai_responses(response)

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
                )
    return _async_codex_client


def reset_codex_client() -> None:
    """Reset cached client (e.g. after token refresh)."""
    global _async_codex_client, _codex_client
    with _codex_lock:
        _codex_client = None
    with _async_codex_lock:
        _async_codex_client = None


# ---------------------------------------------------------------------------
# CodexAgenticAdapter — Responses API streaming adapter
# ---------------------------------------------------------------------------

from core.llm.errors import UserCancelledError  # noqa: E402
from core.llm.providers.openai import (  # noqa: E402
    OpenAIAgenticAdapter,
    _convert_messages_to_responses,
    _tools_to_openai,
)
from core.llm.router import call_with_failover  # noqa: E402


# PR-DRIFT-CUT (2026-05-24) — replaced the v0.52.7 ``startswith("gpt-5")``
# prefix heuristic with the explicit per-model registry in
# :mod:`core.llm.adapters._openai_common`. A reasoning model is one whose
# spec exposes a ``reasoning_effort_values`` tuple — that flag is the
# single source of truth for "accepts ``reasoning`` + omits ``temperature``".
# Adding a new Codex model only requires registering its spec; no string
# matching needs to chase the catalog. Future ``gpt-5.x-codex-spark``,
# ``gpt-5.6``, ``o5`` etc. inherit the right behaviour the moment they
# appear in the registry.
def _is_codex_reasoning_model(model: str) -> bool:
    """Return True for Codex models that accept ``reasoning`` + omit temperature."""
    from core.llm.adapters._openai_common import get_openai_model_spec

    return get_openai_model_spec(model).reasoning_effort_values is not None


class CodexAgenticAdapter(OpenAIAgenticAdapter):
    """OpenAI Codex adapter — subscription quota via Responses API streaming.

    Uses chatgpt.com/backend-api/codex with Codex OAuth token.
    """

    @property
    def provider_name(self) -> str:
        return "openai-codex"

    @property
    def fallback_chain(self) -> list[str]:
        """**DEPRECATED — returns ``[]`` (PR-DRIFT-CUT, 2026-05-24).**

        See :func:`core.llm.provider_dispatch._get_fallback_chain` for
        rationale.
        """
        return []

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
        client = _get_async_codex_client()
        if client is None:
            self.last_error = ValueError("Codex OAuth token not configured")
            log.warning("No Codex OAuth token for agentic loop")
            return None

        # v0.53.3 — use the Responses-API converter (was previously the
        # Chat-Completions converter ``_convert_messages_to_openai``,
        # which produced ``{role:"assistant", content:None,
        # tool_calls:[...]}`` shapes that Codex subscription rejects with
        # ``input[i].content must be array or string, got null``). The
        # Responses API expects per-item-type wire shapes:
        # function_call (no content field), function_call_output
        # (output not content), message (content always string/array,
        # never null). OpenAI PAYG already used this converter
        # (``openai.py:496``); Codex subscription inherits the same behaviour
        # now. Spec-grounded against openai-python TypedDicts
        # ResponseFunctionToolCallParam / FunctionCallOutput /
        # ResponseOutputMessageParam.
        oai_messages = _convert_messages_to_responses(system, messages)
        # v0.55.0 — Codex multi-turn encrypted reasoning replay.
        # v0.60.0 — extracted to shared helper so PAYG OpenAI Responses
        # adapter can reuse the same walker (R3-mini parity).
        from core.llm.agentic_response import inject_reasoning_replay

        resp_input = inject_reasoning_replay(oai_messages, messages)

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
        # PR-B fix-up #1 — route through the cross-provider normaliser
        # so canonical ``"any"`` → OpenAI/Responses ``"required"`` and
        # ``{"type": "tool", "name": "X"}`` → ``{"type": "function",
        # "name": "X"}`` translate correctly. Pre-fix the codex adapter
        # only grabbed ``tool_choice.get("type")`` which silently passed
        # the literal ``"any"`` or ``"tool"`` string straight through —
        # values the Responses API rejects, so any forced-tool caller
        # (e.g. ``core.agent.loop._reflection.reflect_async``) hit
        # silent no-ops on the ``openai-codex`` provider.
        from core.llm.tool_choice import normalize as _normalize_tool_choice

        tc_val: Any = _normalize_tool_choice("openai", tool_choice) or "auto"
        is_reasoning = _is_codex_reasoning_model(model)

        async def _do_call(m: str) -> Any:
            # v0.52.6 hotfix — chatgpt.com/backend-api/codex/responses
            # rejects ``max_output_tokens`` with 400 ("Unsupported
            # parameter"). The subscription manages output limits
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
            # tool dispatch path on subscriptions.
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
            # v0.53.3 — Codex Rust pattern: accumulate output items from
            # ``response.output_item.done`` events as they arrive.
            async with client.responses.stream(**kwargs) as stream:
                accumulated_items: list[Any] = []
                async for event in stream:
                    if getattr(event, "type", "") == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if item is not None:
                            accumulated_items.append(item)
                final = await stream.get_final_response()
                # Always overwrite — never trust SDK's reconstructed output
                # for Codex subscription (it's structurally empty per the backend's
                # SSE contract).
                if accumulated_items:
                    final.output = accumulated_items
                return final

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except Exception as exc:
            # v0.53.2 — preserve BillingError propagation so AgenticLoop
            # renders the quota_exhausted IPC panel. Pre-fix the generic
            # Exception catch swallowed BillingError into self.last_error
            # and returned None, breaking the v0.53.0 fail-fast governance
            # for Codex subscription quota exhaustion.
            from core.llm.errors import BillingError

            if isinstance(exc, BillingError):
                raise
            self.last_error = exc
            log.warning("Codex agentic LLM call failed", exc_info=True)
            return None

        if response is None:
            return None

        # Token usage is recorded once by the agentic loop's ``_track_usage``
        # on the normalized AgenticResponse below — recording here as well
        # double-counted every codex call into ``~/.geode/usage/*.jsonl``
        # (gpt-5.5: 50.5 % paired duplicates, gpt-5.3-codex: 64 %).  The
        # agent loop reads the same ``response.usage`` so the numbers
        # match without the second persist write.

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

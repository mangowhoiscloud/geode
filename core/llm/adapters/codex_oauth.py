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
    build_codex_input,
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

        - ``max_output_tokens`` is forbidden (server-managed under the subscription
          quota; sending it returns 400 ``Unsupported parameter``).
        - ``store = False`` is required.
        - ``instructions`` field carries the system prompt (Responses API's
          ``input`` array does not accept ``role: system`` on Codex).
        - Tools use the FLAT shape (``translate_tool_for_codex``), not the
          Chat Completions nested ``function`` wrapper.

        We stream by default and aggregate the final response — non-streaming
        ``responses.create`` returns a structurally empty body on the Codex
        backend (the actual content arrives only via SSE events).

        A2 (v0.99.44): the SSE accumulator now also captures ``type:
        reasoning`` typed items (encrypted_content + summary) — Codex
        gpt-5.x models lose their chain of thought on the next turn
        unless those items are replayed in the next ``input`` array
        (``store=False`` makes server-side resolution by id impossible).
        :func:`translate_codex_response` surfaces them on
        :attr:`AdapterCallResult.reasoning_items` and the legacy bridge
        forwards them to :attr:`AgenticResponse.codex_reasoning_items`.
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
        except Exception as exc:
            self._last_error = exc
            log.warning("codex-oauth: responses.stream failed model=%s err=%s", req.model, exc)
            raise
        result = translate_codex_response(final, accumulated_items=accumulated)
        # PR-CODEX-OAUTH-EMPTY-TEXT-DUMP (2026-05-25) — Codex sometimes
        # returns ``output_text=""`` while emitting reasoning-only items
        # (gpt-5.x reasoning mode skipping the visible-answer block).
        # The downstream worker treats empty text as failure
        # (``worker.py:_persist_outcome: success = bool(text)``), and
        # the user only sees ``summary="termination_reason=natural"``
        # with no clue why. Smoke 11/12/13 vote-m000-openai.openai-codex
        # all failed in this pattern (10s elapsed, $0.04 billed, zero
        # assistant_message events). Dump a postmortem so the operator
        # can recover the (usage / reasoning_items / reasoning_summaries
        # / stop_reason) without re-running the cycle, and log the dump
        # path on the warning line that surfaces alongside the
        # worker-level failure.
        if not result.text:
            dump_path = _dump_empty_text_postmortem(model=req.model, result=result)
            log.warning(
                "codex-oauth: empty output_text model=%s "
                "reasoning_items=%d reasoning_summaries=%d stop_reason=%s dump=%s",
                req.model,
                len(result.reasoning_items),
                len(result.reasoning_summaries),
                result.stop_reason,
                dump_path or "<dump failed>",
            )
        return result

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
    - ``input`` is the user/assistant/tool array — built via
      :func:`build_codex_input` which re-encodes Anthropic content blocks
      into Codex typed items (``function_call`` / ``function_call_output``)
    - ``store=False`` is mandatory
    - ``max_output_tokens`` is FORBIDDEN — Subscription manages it
      server-side, sending the field returns 400
    - Tools use the FLAT shape (``translate_tool_for_codex``)
    - Reasoning models (per
      :func:`core.llm.adapters._openai_common.get_openai_model_spec`)
      omit ``temperature`` and add ``reasoning`` + ``include:
      ["reasoning.encrypted_content"]``
    - A2 (v0.99.44): previous-turn reasoning items replay inline via
      :func:`build_codex_input` — each assistant :class:`Message` carries
      its own ``codex_reasoning_items`` (populated by the bridge from the
      Anthropic-shape assistant message dict's ``codex_reasoning_items``
      key) and ``build_codex_input`` prepends those entries at the
      correct ordinal position. The legacy whole-input prepend approach
      lost per-turn association for multi-assistant histories — Codex
      MCP A2 BLOCKER 3.
    - PR-DRIFT-CUT (2026-05-24): replaced ``req.model.startswith("gpt-5")``
      heuristic with explicit registry lookup so o3 / o4-mini / new
      reasoning models go through the same branch automatically.
    """
    from core.llm.adapters._openai_common import cap_tools, get_openai_model_spec

    spec = get_openai_model_spec(req.model)
    resp_input = build_codex_input(req)
    kwargs: dict[str, Any] = {
        "model": req.model,
        "instructions": req.system_prompt or "You are a helpful assistant.",
        "input": resp_input or [{"role": "user", "content": "hello"}],
        "store": False,
    }
    if req.tools:
        translated = [translate_tool_for_codex(t) for t in req.tools]
        kwargs["tools"] = cap_tools(translated, model=req.model, adapter_name="codex-oauth")
        kwargs["tool_choice"] = _translate_codex_tool_choice(req.tool_choice)
        kwargs["parallel_tool_calls"] = True
    if spec.reasoning_effort_values is not None:
        # Reasoning-model branch — encrypted reasoning passthrough +
        # reasoning effort. Temperature is dropped per spec.
        kwargs["include"] = ["reasoning.encrypted_content"]
        kwargs["reasoning"] = {"effort": req.effort, "summary": "auto"}
    elif req.temperature is not None and spec.accepts_temperature:
        kwargs["temperature"] = req.temperature
    # PR-CODEX-OAUTH-RESPONSE-SCHEMA (2026-05-25) — Responses API
    # structured-output enforcement. PR-JSON-WIRE (#79) routed
    # ``req.response_schema`` through claude-cli (--json-schema) and
    # codex-cli (--output-schema <FILE>) but silently dropped the
    # codex-oauth path. Without API-level schema enforcement, gpt-5.x
    # reasoning models can return ``stop_reason=completed`` with the
    # entire output budget spent on encrypted reasoning items + empty
    # ``output_text`` (smoke 17: 20+ codex-oauth-empty-text dumps,
    # ~10 per match). Adding ``text.format = {type:"json_schema", ...}``
    # forwards the schema for server-side enforcement. Spec: OpenAI
    # Responses API ``text.format`` (replaces Chat Completions
    # ``response_format``).
    #
    # Codex MCP review of PR #1687: ``strict: True`` requires the schema
    # to satisfy OpenAI's Structured Outputs subset (all object schemas
    # set ``additionalProperties: false`` AND every property listed in
    # ``required``). GEODE's seed-generation schemas in
    # ``plugins/seed_generation/json_schemas.py`` intentionally use the
    # additive helper that omits both, so unconditional strict=True would
    # cause the server to **reject the request** (400) before generation
    # — a worse retry storm than the empty-text path. Auto-detect strict
    # compatibility per schema and fall through to ``strict: False`` for
    # non-compatible schemas (still forwards the shape as a strong hint,
    # but server treats it as informational rather than gated).
    if req.response_schema is not None:
        schema_name = str(req.response_schema.get("title") or "response")
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": _is_strict_compatible(req.response_schema),
                "schema": req.response_schema,
            }
        }
    return kwargs


def _is_strict_compatible(schema: Any) -> bool:
    """Check whether ``schema`` satisfies OpenAI's strict Structured Outputs subset.

    Per the public Responses API docs, ``strict: True`` requires that
    every ``type: "object"`` subschema:

    - sets ``additionalProperties: false`` (typed-additional or True is rejected)
    - lists ALL declared property keys in ``required``

    Plus array ``items`` and nested objects must satisfy the same recursively.
    Anything else (``oneOf`` / ``anyOf`` with mixed types, ``allOf``,
    pattern-only schemas, unconstrained ``object``) is conservatively
    treated as non-strict.

    Returns ``True`` when the schema is safe to send with ``strict: True``;
    ``False`` when ``strict: False`` should be used instead. This keeps
    legacy GEODE schemas (designed for additive-output tolerance) from
    causing 400 rejections while still forwarding the schema shape as a
    server hint.
    """
    if not isinstance(schema, dict):
        return True
    schema_type = schema.get("type")
    if schema_type == "object":
        if schema.get("additionalProperties") is not False:
            return False
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if set(properties.keys()) != required:
            return False
        for prop_schema in properties.values():
            if not _is_strict_compatible(prop_schema):
                return False
    if "items" in schema and not _is_strict_compatible(schema["items"]):
        return False
    for combinator_key in ("oneOf", "anyOf", "allOf"):
        # Combinators are accepted only when every branch is strict-compatible.
        branches = schema.get(combinator_key)
        if isinstance(branches, list):
            for branch in branches:
                if not _is_strict_compatible(branch):
                    return False
    return True


def _translate_codex_tool_choice(tc: str | dict[str, Any]) -> str | dict[str, Any]:
    """Adapter-neutral ``tool_choice`` → Codex Responses API wire shape.

    Routes through :func:`core.llm.tool_choice.normalize` with
    ``provider="openai"`` — Responses API uses the FLAT shape
    ``{"type": "function", "name": "..."}`` (not the Chat nested
    ``function`` wrapper). The legacy helper accepts the Anthropic-shape
    dicts the AgenticLoop emits (``{"type": "auto"}`` / ``{"type":
    "none"}`` / ``{"type": "any"}`` / ``{"type": "tool", "name": "..."}``)
    and returns the Codex-correct payload (Codex MCP A2 BLOCKER 2).
    """
    from core.llm.tool_choice import normalize

    normalised = normalize("openai", tc)
    return normalised if normalised is not None else "auto"


def _dump_empty_text_postmortem(
    *,
    model: str,
    result: AdapterCallResult,
) -> str | None:
    """Persist a JSON post-mortem for every codex-oauth empty-text
    response so operators can diagnose without re-running the cycle.
    Returns the dump path (str) on success, ``None`` on any I/O error
    (best-effort — diagnostic, not correctness-critical). Mirrors
    ``claude_cli._dump_transient_postmortem`` shape so the same
    operator's ``diagnostics tar-up`` workflow catches both.

    PR-CODEX-OAUTH-EMPTY-TEXT-DUMP (2026-05-25) — Codex gpt-5.x
    sometimes returns reasoning items with no visible-answer text;
    the worker treats that as failure with no actionable surface.
    The dump records the four diagnostic dimensions:

    (1) ``usage`` — input/output token counts the upstream billed
    (2) ``reasoning_items`` — typed encrypted_content blobs (raw)
    (3) ``reasoning_summaries`` — the model's plain-text chain of thought
    (4) ``stop_reason`` — Codex backend's terminal status

    Future ratchet: if a category of empty-text responses turns out
    to be recoverable (e.g. ``reasoning_summaries`` carries the
    actual answer in a parseable shape), add a text fallback inside
    ``acomplete`` keyed on the dump's payload shape.
    """
    import json
    import time

    from core.paths import GLOBAL_DIAGNOSTICS_DIR

    try:
        postmortem_dir = GLOBAL_DIAGNOSTICS_DIR / "codex-oauth-empty-text"
        postmortem_dir.mkdir(parents=True, exist_ok=True)
        hit_ts = int(time.time())
        postmortem_path = postmortem_dir / f"{hit_ts}-{model}.json"
        payload: dict[str, Any] = {
            "ts": hit_ts,
            "model": model,
            "stop_reason": result.stop_reason,
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            },
            "reasoning_items_count": len(result.reasoning_items),
            "reasoning_summaries_count": len(result.reasoning_summaries),
            "reasoning_items": list(result.reasoning_items),
            "reasoning_summaries": list(result.reasoning_summaries),
        }
        postmortem_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(postmortem_path)
    except OSError as exc:
        log.debug("codex-oauth: postmortem dump write failed: %s", exc)
        return None


__all__ = ["CodexOAuthAdapter"]

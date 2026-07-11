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
import os
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from core.auth.codex_cli_oauth import codex_auth_path
from core.llm.adapters._openai_common import (
    build_async_codex_client,
    build_responses_kwargs,
    translate_codex_response,
)
from core.llm.adapters.base import (
    SOURCE_SUBSCRIPTION,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EmptyModelOutputError,
    EnvironmentReport,
    Message,
    ModelSpec,
    QuotaWindows,
    StreamEvent,
    TextCompletionResult,
    WebSearchResult,
)
from core.llm.loop_affinity import LoopAffineClientCache
from core.orchestration.openai_api_lane import acquire_openai_api_lane_async

log = logging.getLogger(__name__)


@dataclass
class CodexOAuthAdapter:
    """Subscription-routed OpenAI adapter via Codex OAuth backend."""

    name: str = "codex-oauth"
    provider: str = "openai"
    source: str = SOURCE_SUBSCRIPTION
    billing_type: AdapterBillingType = AdapterBillingType.SUBSCRIPTION
    # PR-NO-FALLBACK (2026-05-28) — web_search re-enabled.
    # PR-CODEX-INSTRUCTIONS-FIX (2026-05-28) — **verified live**: the
    # Codex backend (``chatgpt.com/backend-api/codex/responses``) returns
    # 200 OK to ``{"type": "web_search"}`` with real web search results
    # (OpenAI help-center URLs etc.), confirmed via direct adapter call
    # at 2026-05-28 14:50 KST (11.2s response). The live test revealed
    # two backend-specific constraints that PAYG Responses API does NOT
    # enforce — both now enforced in :meth:`aweb_search`:
    #
    #   1. ``instructions`` field mandatory — Codex backend returns 400
    #      ``Instructions are required`` without it (PAYG treats it as
    #      optional).
    #   2. ``input`` must be a typed-item list, not a plain string —
    #      Codex backend returns 400 ``Input must be a list`` for the
    #      string form (PAYG accepts both shapes).
    #
    # SDK-contract evidence (workflow §4d doc-attestation): openai-python
    # ``ToolParam`` Union (``openai/types/responses/tool_param.py``)
    # accepts ``{"type": "web_search"}``; Codex CLI Responses endpoint
    # accepts ``tools: array`` per ``codex-rs/codex-api/README.md::POST
    # /responses``. SDK contract was the necessary upstream check; the
    # two 400 responses + 200 OK after fixing proved the backend
    # actually exposes the tool.
    supports_web_search: bool = True
    supports_text_completion: bool = True
    # ComputerUseCapable — structurally satisfied, but the ChatGPT-subscription
    # Codex backend live-REJECTS the GA ``{type: "computer"}`` tool with
    # ``400 Unsupported tool type: computer`` (2026-06-17 live E2E,
    # operator-authorized). The ctx7 GA docs cover the OpenAI *Platform* API,
    # not this subscription backend. So this adapter advertises NO computer-use:
    # ``supports_computer_use=False`` + ``computer_tool_param`` returns ``None``,
    # mirroring the live path which now excludes ``backend="codex"`` from
    # ``_openai_common._maybe_inject_openai_computer_use`` (no drift). The
    # web_search live test above does NOT generalise to the computer tool.
    supports_computer_use: bool = False
    _last_error: Exception | None = field(default=None, init=False, repr=False)
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — one client per owning event loop
    # (see core/llm/loop_affinity.py).
    _clients: LoopAffineClientCache = field(
        default_factory=lambda: LoopAffineClientCache("codex-oauth"), init=False, repr=False
    )
    _token_fingerprint: str = field(default="", init=False, repr=False)
    _token_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def computer_tool_param(
        self, *, display_width: int, display_height: int
    ) -> dict[str, Any] | None:
        """ComputerUseCapable — returns ``None``: the Codex subscription backend
        does not accept the GA ``{type: "computer"}`` tool.

        Live E2E (2026-06-17, operator-authorized) proved the backend rejects it
        with ``400 Unsupported tool type: computer``. The enumerable contract
        must mirror the live request path, which now excludes ``backend="codex"``
        from ``_openai_common._maybe_inject_openai_computer_use`` — so this
        returns ``None`` (cannot inject), keeping the contract and the wire
        payload in lock-step. The GA tool is platform-only (``OpenAIPaygAdapter``).
        """
        del display_width, display_height  # backend rejects the GA computer tool
        return None

    def _get_client(self) -> Any:
        from core.llm.providers.codex import _resolve_codex_token_info

        resolved = _resolve_codex_token_info(force_refresh=True)
        if not resolved:
            raise RuntimeError(
                "CodexOAuthAdapter: ChatGPT OAuth not found. Looked in GEODE "
                f"ProfileStore ('openai-codex' profile) and {codex_auth_path()}. "
                "Run ``/login openai`` in GEODE or ``codex auth login`` in the "
                "Codex CLI to provision credentials, or use the openai-payg / "
                "codex-cli adapter."
            )
        with self._token_lock:
            if self._token_fingerprint != resolved.fingerprint:
                if self._token_fingerprint:
                    log.info(
                        "codex-oauth: token changed (%s -> %s); invalidating clients",
                        self._token_fingerprint,
                        resolved.fingerprint,
                    )
                self._clients.invalidate()
                self._token_fingerprint = resolved.fingerprint
        return self._clients.get(lambda: build_async_codex_client(resolved.token))

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
        kwargs = build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
        # PR-LEGACY-PROVIDER-REMOVAL (2026-05-28) — pre-send input-shape
        # diagnostic backfilled from the now-deleted
        # ``CodexAgenticAdapter.agentic_call``. The Codex backend rejects
        # ``input[i].content == null`` with 400 ``"input[i].content must be
        # array or string, got null"``; surfacing a structured per-item
        # shape line at WARN whenever any prefix entry has ``content=None``
        # makes that regression debuggable from the daemon log without
        # needing a wire trace. Capped at first 30 entries.
        _log_codex_input_shape(kwargs.get("input"))
        # PR-OAUTH-API-LANES (2026-05-26) — gate concurrent API calls
        # through the shared openai-api lane so PR-RANKER-PARALLEL's
        # 177-call burst stays under the per-account 429 floor. The
        # CLI subprocess flow has its own ``codex_cli_lane``; this
        # lane covers the direct Responses API path.
        lane_key = f"codex-oauth:{req.model}"
        async with acquire_openai_api_lane_async(lane_key):
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
                log.warning(
                    "codex-oauth: responses.stream failed model=%s err=%s",
                    req.model,
                    exc,
                )
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
        if not result.text and not result.tool_uses:
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
            if _fail_on_empty_text_enabled():
                raise EmptyModelOutputError(
                    "codex-oauth: empty output_text "
                    f"model={req.model} stop_reason={result.stop_reason} "
                    f"dump={dump_path or '<dump failed>'}",
                    mark_recovered=lambda: _mark_empty_text_recovered(dump_path),
                    mark_actionable=lambda: _mark_empty_text_actionable(dump_path),
                )
        return result

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
    ) -> TextCompletionResult:
        """Single-turn text completion via the Codex subscription Responses
        endpoint.

        Route through :meth:`acomplete` so compaction / dreaming text calls
        use the same Codex backend shape as agent turns: typed ``input`` list,
        ``instructions`` for system text, ``store=False``, no
        ``max_output_tokens``, and streaming aggregation.
        """
        from core.config import CODEX_PRIMARY

        result = await self.acomplete(
            AdapterCallRequest(
                model=model or CODEX_PRIMARY,
                messages=(Message(role="user", content=prompt),),
                system_prompt=system,
                max_tokens=max_tokens,
            )
        )
        return TextCompletionResult(
            text=result.text,
            usage=result.usage,
            adapter_name=self.name,
            adapter_provider=self.provider,
            adapter_source=self.source,
        )

    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult:
        """Codex-subscription web_search via Responses API ``web_search``
        hosted tool.

        ``model`` hint intentionally unused — the Codex backend's
        per-model web_search support matrix is unverified
        (doc-before-behaviour, CLAUDE.md §4d); CODEX_PRIMARY stays the
        search model.

        Codex backend requires ``store=False`` (same constraint as
        :meth:`acomplete` — backend reject 400 without it) and uses the
        ``responses.stream`` event-driven aggregation path because
        non-streaming ``responses.create`` returns structurally empty
        bodies on this endpoint. We mirror that pattern instead of
        reusing the PAYG-only :func:`openai_web_search` helper which
        targets the standard Responses endpoint.

        Codex MCP audit catch (2026-05-28) — the prior version delegated
        to ``openai_web_search`` directly, which would fail on Codex
        OAuth with ``Unsupported parameter`` or empty output, and the
        dispatch layer would surface a confusing ``BillingError``
        (because :func:`is_billing_fatal` doesn't match shape errors)
        even though the real issue is the call shape mismatch.
        """
        del model
        from core.config import CODEX_PRIMARY

        client = self._get_client()
        text_parts: list[str] = []
        source_urls: list[str] = []
        # PR-CODEX-INSTRUCTIONS-FIX (2026-05-28) — live test progression:
        #
        # 1st attempt (PR-NO-FALLBACK initial) → 400 ``Instructions are
        #    required``. Codex backend enforces ``instructions`` field
        #    mandatory on every Responses request (mirrors :meth:`acomplete`
        #    which threads the loop's system prompt into it).
        # 2nd attempt (instructions added as string ``input``) → 400
        #    ``Input must be a list``. Codex backend ALSO requires
        #    ``input`` to be a typed-item array, same as :meth:`acomplete`
        #    via :func:`build_codex_input`. The standard Responses API
        #    accepts a plain string; Codex backend tightens the contract.
        #
        # Final shape — single user message wrapped in the typed-item array
        # the backend expects (``{"role": "user", "content": "..."}`` is a
        # valid entry per ``_convert_user_msg_to_responses``).
        user_prompt = (
            f"Search the web for: {query}. Return up to {max_results} relevant "
            "results with titles, URLs, and brief summaries."
        )
        kwargs = {
            "model": CODEX_PRIMARY,
            "instructions": (
                "Use the web_search tool to find current information. "
                "Return up to the requested number of relevant results with "
                "titles, URLs, and brief summaries."
            ),
            "input": [{"role": "user", "content": user_prompt}],
            "tools": [{"type": "web_search"}],
            "store": False,
        }
        async with client.responses.stream(**kwargs) as stream:
            async for event in stream:
                ev_type = getattr(event, "type", "")
                if ev_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if item is None:
                        continue
                    if getattr(item, "type", "") == "message":
                        for sub in getattr(item, "content", []) or []:
                            if getattr(sub, "type", "") == "output_text":
                                sub_text = getattr(sub, "text", "")
                                if sub_text:
                                    text_parts.append(sub_text)
                    if getattr(item, "type", "") == "web_search_call":
                        for entry in getattr(item, "results", []) or []:
                            url = getattr(entry, "url", None)
                            if url:
                                source_urls.append(url)
            await stream.get_final_response()
        if not text_parts:
            raise RuntimeError(
                "codex-oauth web_search: empty output_text — Codex backend "
                "may have rejected the web_search tool for this account. "
                "Try /login source payg to use openai-payg instead."
            )
        return WebSearchResult(
            query=query,
            text="\n".join(text_parts),
            source_urls=tuple(source_urls),
            adapter_name=self.name,
        )

    async def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        kwargs = build_responses_kwargs(req, backend="codex", adapter_name="codex-oauth")
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
                        "missing" if not codex_auth_path().is_file() else "unreadable",
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
        from core.llm.model_catalog import model_spec_for_adapter

        ids = [CODEX_PRIMARY, *CODEX_FALLBACK_CHAIN]
        seen: set[str] = set()
        out: list[ModelSpec] = []
        for mid in ids:
            if mid in seen:
                continue
            seen.add(mid)
            out.append(model_spec_for_adapter(mid, provider=self.provider))
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
            str(codex_auth_path())
            if codex_auth_path().is_file()
            else "GEODE ProfileStore (openai-codex)"
        )
        return CredentialDetection(
            model=CODEX_PRIMARY,
            provider=self.provider,
            source_path=source_path,
        )


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
            "codex_output_items_count": len(result.codex_output_items),
            "codex_output_item_types": [
                str(item.get("type", "<missing>"))
                for item in result.codex_output_items
                if isinstance(item, dict)
            ],
            "codex_output_items": list(result.codex_output_items),
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


def _fail_on_empty_text_enabled() -> bool:
    raw = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _mark_empty_text_recovered(dump_path: str | None) -> None:
    """Create an append-only marker only after the identical retry succeeds."""

    if dump_path is None:
        raise RuntimeError("cannot attest empty-output recovery without its diagnostic dump")
    from pathlib import Path

    Path(f"{dump_path}.recovered").touch(exist_ok=False)


def _mark_empty_text_actionable(dump_path: str | None) -> None:
    """Attest that an earlier tool action made the empty continuation usable."""

    if dump_path is None:
        raise RuntimeError("cannot attest actionable empty output without its diagnostic dump")
    from pathlib import Path

    Path(f"{dump_path}.actionable").touch(exist_ok=False)


def _log_codex_input_shape(resp_input: Any, *, cap: int = 30) -> None:
    """Backfilled from legacy ``CodexAgenticAdapter.agentic_call`` (v0.53.3).

    Emit a per-item shape line whenever the prefix carries any
    ``content=None`` entry, or unconditionally at DEBUG. The Codex backend
    rejects ``input[i].content == null`` with 400 ``"input[i].content must
    be array or string, got null"`` and the resulting body-less exception
    is hard to triage without seeing which item misbehaved.
    """
    if not isinstance(resp_input, list) or not resp_input:
        return
    has_null = any(isinstance(m, dict) and m.get("content") is None for m in resp_input[:cap])
    if not (has_null or log.isEnabledFor(logging.DEBUG)):
        return
    shape_parts: list[str] = []
    for idx, item in enumerate(resp_input[:cap]):
        if not isinstance(item, dict):
            shape_parts.append(f"[{idx}]{type(item).__name__}")
            continue
        kind = item.get("type") or item.get("role") or "<unknown>"
        if "content" in item:
            content = item["content"]
            ctype = (
                "None"
                if content is None
                else f"str({len(content)})"
                if isinstance(content, str)
                else f"list({len(content)})"
                if isinstance(content, list)
                else type(content).__name__
            )
            shape_parts.append(f"[{idx}]{kind} content={ctype}")
        elif "output" in item:
            output = item["output"]
            otype = (
                "None"
                if output is None
                else f"str({len(output)})"
                if isinstance(output, str)
                else f"list({len(output)})"
                if isinstance(output, list)
                else type(output).__name__
            )
            shape_parts.append(f"[{idx}]{kind} output={otype}")
        else:
            shape_parts.append(f"[{idx}]{kind} keys={sorted(item.keys())}")
    log.warning("codex-oauth resp_input shape: %s", " | ".join(shape_parts))


__all__ = ["CodexOAuthAdapter"]

"""Codex backend payload invariants — Codex MCP review 2026-05-23 BLOCKER pin.

The Codex backend (``chatgpt.com/backend-api/codex``) has 4 mandatory
differences from PAYG OpenAI Responses API. The first follow-up review caught
that the adapter was using the PAYG-style call kwargs. These tests guard
against regression.

References:
- ``docs/research/codex-oauth-request-spec.md``
- ``core/llm/providers/codex.py::CodexAgenticAdapter.agentic_call`` (canonical)
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.llm.adapters._openai_common import _prompt_cache_key, build_responses_kwargs
from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    ToolSpec,
    UsageSummary,
)


def _wire_image(data: str, call_id: str = "synthetic-call") -> dict:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": [{"type": "input_image", "image_url": f"data:image/png;base64,{data}"}],
    }


def test_request_image_receipt_counts_wire_order_without_deduplicating_or_leaking() -> None:
    from core.llm.adapters._openai_common import build_request_image_receipt
    from core.tools.computer_observation import screenshot_digest

    wire = [
        {"type": "reasoning", "encrypted_content": "SYNTHETIC_PRIVATE_REASONING"},
        {"role": "user", "content": "SYNTHETIC_PRIVATE_TEXT input_image"},
        _wire_image("AAAA", "private synthetic call-id"),
        _wire_image("BBBB", "another synthetic call-id"),
        _wire_image("AAAA", "private synthetic call-id"),
    ]
    before = copy.deepcopy(wire)
    receipt = build_request_image_receipt(wire)
    assert receipt is not None
    assert receipt["scope"] == "responses-input-images"
    assert receipt["image_count"] == 3 and receipt["encoded_image_bytes"] == 12
    assert receipt["complete"] is True and receipt["rows_omitted"] == 0
    assert [row["sha256"] for row in receipt["refs"]] == [
        screenshot_digest(data) for data in ("AAAA", "BBBB", "AAAA")
    ]
    assert (
        receipt["refs"][0]["call_sha256"]
        == hashlib.sha256(b"private synthetic call-id").hexdigest()
    )
    encoded = json.dumps(receipt)
    assert all(
        word not in encoded
        for word in (
            "SYNTHETIC_PRIVATE",
            "private synthetic",
            "data:image",
            "AAAA",
            "BBBB",
        )
    )
    assert wire == before


@pytest.mark.parametrize("wire", [[], [{"role": "user", "content": "ordinary text"}]])
def test_request_image_receipt_observed_zero_is_not_missing(wire) -> None:
    from core.llm.adapters._openai_common import build_request_image_receipt

    receipt = build_request_image_receipt(wire)
    assert receipt == {
        "scope": "responses-input-images",
        "image_count": 0,
        "encoded_image_bytes": 0,
        "complete": True,
        "rows_omitted": 0,
        "refs": [],
    }
    assert build_request_image_receipt(None) is None
    assert (
        AdapterCallResult(
            text="ok", usage=UsageSummary(), stop_reason="completed"
        ).request_image_receipt
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://invalid.example/synthetic-private.png",
        "data:image/png;base64,not-valid-base64!",
        "data:image/png;base64," + "A" * (7 * 1024 * 1024 + 4),
    ],
)
def test_request_image_receipt_unknown_or_oversized_image_stays_incomplete(url) -> None:
    from core.llm.adapters._openai_common import build_request_image_receipt

    wire = _wire_image("AAAA")
    wire["output"][0]["image_url"] = url
    receipt = build_request_image_receipt([wire])
    assert receipt is not None
    assert receipt["image_count"] == receipt["rows_omitted"] == 1
    assert receipt["complete"] is False and receipt["refs"] == []
    assert receipt["encoded_image_bytes"] == (
        None if url.startswith("https:") else len(url.split(",", 1)[1])
    )
    assert url not in json.dumps(receipt)


def test_request_image_receipt_caps_references_and_survives_existing_event_bounds() -> None:
    from core.llm.adapters._openai_common import build_request_image_receipt
    from core.observability.activity import LLMRequestImageReceiptDetails
    from core.observability.event_store import bound_event_payload

    receipt = build_request_image_receipt([_wire_image("AAAA", f"call-{i}") for i in range(25)])
    assert receipt is not None
    assert receipt["image_count"] == 25 and len(receipt["refs"]) == 24
    assert receipt["rows_omitted"] == 1 and receipt["complete"] is False
    assert len(json.dumps(receipt, separators=(",", ":")).encode()) <= 4096
    validated = LLMRequestImageReceiptDetails.model_validate(receipt).model_dump()
    assert bound_event_payload({"request_image_receipt": validated}) == {
        "request_image_receipt": receipt,
    }


def test_request_image_receipt_includes_direct_and_computer_images_without_fake_tool_join() -> None:
    from core.llm.adapters._openai_common import build_request_image_receipt

    receipt = build_request_image_receipt(
        [
            {"role": "user", "content": _wire_image("AAAA")["output"]},
            {
                "type": "computer_call_output",
                "call_id": "computer-call",
                "output": {
                    "type": "computer_screenshot",
                    "image_url": "data:image/jpeg;base64,BBBB",
                },
            },
        ]
    )
    assert receipt is not None
    assert receipt["image_count"] == 2 and receipt["complete"] is True
    assert receipt["refs"][0]["call_sha256"] is None
    assert receipt["refs"][1]["call_sha256"] == hashlib.sha256(b"computer-call").hexdigest()


@pytest.mark.parametrize("cancel", [False, True])
def test_codex_receipt_tracks_post_middleware_wire_and_completed_event(
    monkeypatch,
    tmp_path,
    cancel,
) -> None:
    from dataclasses import replace

    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.hooks import HookEvent, HookSystem, LlmCallRequest, MiddlewareRegistry
    from core.llm.adapters._openai_common import build_request_image_receipt
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.tools.computer_observation import screenshot_digest

    captured = {}
    ended = []

    class Stream:
        async def __aenter__(self):
            if cancel:
                raise asyncio.CancelledError
            return self

        async def __aexit__(self, *_args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_final_response(self):
            return None

    def stream(**kwargs):
        captured.update(copy.deepcopy(kwargs))
        return Stream()

    client = SimpleNamespace(responses=SimpleNamespace(stream=stream))
    monkeypatch.setattr(CodexOAuthAdapter, "_get_client", lambda _self: client)
    monkeypatch.setattr(
        "core.llm.adapters.codex_oauth.translate_codex_response",
        lambda *_args, **_kwargs: AdapterCallResult(
            text="done",
            usage=UsageSummary(input_tokens=1, output_tokens=1),
            stop_reason="completed",
        ),
    )

    class RewriteImages:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            messages = copy.deepcopy(list(request.request.messages))
            messages[-1].content[0]["content"] = messages[-1].content[0]["content"][-1:]
            return request.with_request(
                replace(
                    request.request,
                    messages=messages,
                    metadata={"cache_invalidation_reason": "synthetic image selection"},
                )
            )

    middleware = MiddlewareRegistry()
    middleware.register_llm_request(
        RewriteImages(), name="image-selection", allow_cache_invalidation=True
    )
    hooks = HookSystem()
    hooks.register(
        HookEvent.LLM_CALL_ENDED, lambda _e, data: ended.append(dict(data)), name="receipt"
    )
    store = HookEventStore(tmp_path / "receipt-events.db")
    hooks.register_sink(
        HookPersistenceSink(store, session_key="synthetic-session", run_id="receipt-test"),
        name="receipt-persistence",
    )
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(middleware_registry=middleware),
        config=AgenticLoopConfig(source="codex-oauth", disable_settings_drift=True),
        model="gpt-5.6-sol",
        provider="openai",
        hooks=hooks,
        quiet=True,
    )
    images = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
        for data in ("AAAA", "BBBB")
    ]
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "image-call",
                    "name": "read_document",
                    "input": {"file_path": "/synthetic/private.png"},
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "image-call", "content": images}],
        },
    ]
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(loop._call_llm("Synthetic judge", messages, allow_tools=False))
        assert "request_image_receipt" not in ended[-1]
        assert "usage" not in ended[-1]
    else:
        asyncio.run(loop._call_llm("Synthetic judge", messages, allow_tools=False))
        receipt = ended[-1]["request_image_receipt"]
        assert receipt == build_request_image_receipt(captured["input"])
        assert receipt["image_count"] == 1 and receipt["encoded_image_bytes"] == 4
        assert receipt["refs"][0]["sha256"] == screenshot_digest("BBBB")
        assert ended[-1]["usage"]["input_tokens"] == 1
    row = store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)[0]
    assert row.llm_attempt_id == ended[-1]["llm_attempt_id"]
    assert row.payload["request_image_receipt"] == ended[-1].get("request_image_receipt")
    assert row.payload["usage"] == ended[-1].get("usage")
    assert row.payload["activity_schema_version"] == 9
    assert "private.png" not in json.dumps(row.payload)
    assert len(images) == 2
    hooks.close()


def _req(model: str = "gpt-5.5", **kw: object) -> AdapterCallRequest:
    base: dict[str, object] = {
        "model": model,
        "messages": [Message(role="user", content="hello")],
        "system_prompt": "be brief",
        "max_tokens": 1024,
    }
    base.update(kw)
    return AdapterCallRequest(**base)  # type: ignore[arg-type]


def test_codex_kwargs_does_not_send_max_output_tokens() -> None:
    """Codex backend rejects ``max_output_tokens`` with 400 — must not be sent."""
    kwargs = build_responses_kwargs(
        _req(max_tokens=2048), backend="codex", adapter_name="codex-oauth"
    )
    assert "max_output_tokens" not in kwargs
    assert "max_tokens" not in kwargs


def test_codex_text_completion_reuses_agent_turn_wire_shape(monkeypatch) -> None:
    """Compaction text calls must not use PAYG string-input Responses shape."""
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    captured: AdapterCallRequest | None = None

    async def fake_acomplete(self: CodexOAuthAdapter, req: AdapterCallRequest) -> AdapterCallResult:
        nonlocal captured
        captured = req
        return AdapterCallResult(
            text="ok",
            usage=UsageSummary(input_tokens=1, output_tokens=1),
            stop_reason="completed",
        )

    monkeypatch.setattr(CodexOAuthAdapter, "acomplete", fake_acomplete)

    result = asyncio.run(
        CodexOAuthAdapter().acomplete_text(
            "summarize", system="compact", model="gpt-5.5", max_tokens=77
        )
    )

    assert result.text == "ok"
    assert result.adapter_name == "codex-oauth"
    assert captured is not None
    assert captured.messages == (Message(role="user", content="summarize"),)
    assert captured.system_prompt == "compact"
    assert captured.max_tokens == 77


def test_codex_web_search_honors_frozen_model_hint(monkeypatch) -> None:
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    captured: dict[str, object] = {}

    class Stream:
        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def __aiter__(self) -> Stream:
            return self

        async def __anext__(self) -> object:
            if captured.get("yielded"):
                raise StopAsyncIteration
            captured["yielded"] = True
            return SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text="searched")],
                ),
            )

        async def get_final_response(self) -> object:
            return SimpleNamespace(output=[])

    class Responses:
        def stream(self, **kwargs: object) -> Stream:
            captured.update(kwargs)
            return Stream()

    client = SimpleNamespace(responses=Responses())
    adapter = CodexOAuthAdapter()
    monkeypatch.setattr(adapter, "_get_client", lambda: client)

    result = asyncio.run(adapter.aweb_search("query", model="gpt-5.6-sol"))

    assert captured["model"] == "gpt-5.6-sol"
    assert result.model == "gpt-5.6-sol"


def test_codex_kwargs_sets_store_false() -> None:
    """``store = False`` is required on Codex backend (Plus subscription policy)."""
    kwargs = build_responses_kwargs(_req(), backend="codex", adapter_name="codex-oauth")
    assert kwargs["store"] is False


def test_codex_kwargs_lifts_system_prompt_to_instructions() -> None:
    """System prompt belongs in ``instructions``, not in ``input[].role=system``."""
    kwargs = build_responses_kwargs(
        _req(system_prompt="audit only"), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["instructions"] == "audit only"
    roles_in_input = [m.get("role") for m in kwargs["input"]]
    assert "system" not in roles_in_input


def test_codex_kwargs_instructions_default_when_empty() -> None:
    """Empty system_prompt still produces a non-empty instructions string."""
    kwargs = build_responses_kwargs(
        _req(system_prompt=""), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["instructions"]  # non-empty fallback


def test_codex_kwargs_gpt5_omits_temperature_adds_reasoning() -> None:
    """gpt-5.x family omits ``temperature`` and adds ``reasoning`` block."""
    kwargs = build_responses_kwargs(
        _req(model="gpt-5.5", temperature=0.7), backend="codex", adapter_name="codex-oauth"
    )
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]


def test_codex_kwargs_o_series_also_omits_temperature() -> None:
    """PR-DRIFT-CUT (2026-05-24) — registry-driven reasoning detection.

    Pre-PR the codex branch keyed on ``startswith("gpt-5")``, so o3 /
    o4-mini fell into the "keep temperature" path. The registry now
    treats every model with a ``reasoning_effort_values`` tuple as a
    reasoning model — o3 and o4-mini included — so they correctly
    omit ``temperature`` and add the ``reasoning`` block. Verified
    2026-05-24 against OpenAI reasoning-models guide.
    """
    kwargs = build_responses_kwargs(
        _req(model="o3", temperature=0.3), backend="codex", adapter_name="codex-oauth"
    )
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]


def test_codex_kwargs_legacy_model_keeps_temperature() -> None:
    """Models NOT in the registry fall back to legacy gpt-4.x defaults.

    Those defaults accept temperature, so the legacy branch is still
    exercised — we just no longer reach it via prefix-heuristic. An
    unknown model id (e.g. ``gpt-4o`` until it's registered) keeps
    the temperature path.
    """
    kwargs = build_responses_kwargs(
        _req(model="gpt-4o-legacy", temperature=0.3), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["temperature"] == 0.3
    assert "reasoning" not in kwargs


def test_codex_kwargs_tools_use_flat_responses_shape() -> None:
    """Codex Responses API requires the FLAT tool shape (not nested ``function``)."""
    tool = ToolSpec(name="search", description="web search", input_schema={"type": "object"})
    kwargs = build_responses_kwargs(_req(tools=[tool]), backend="codex", adapter_name="codex-oauth")
    assert kwargs["tools"] == [
        {
            "type": "function",
            "name": "search",
            "description": "web search",
            "parameters": {"type": "object"},
        }
    ]
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["parallel_tool_calls"] is True


def test_codex_kwargs_no_tools_when_none_provided() -> None:
    kwargs = build_responses_kwargs(_req(), backend="codex", adapter_name="codex-oauth")
    assert "tools" not in kwargs
    assert "parallel_tool_calls" not in kwargs


# --- PR-CODEX-OAUTH-RESPONSE-SCHEMA (2026-05-25) ---------------------------


_VOTE_SCHEMA: dict[str, object] = {
    "title": "vote",
    "type": "object",
    "properties": {
        "match_id": {"type": "string"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string"},
    },
    "required": ["match_id", "winner", "rationale"],
}


def test_codex_kwargs_omits_text_format_when_no_response_schema() -> None:
    """Back-compat: callers that don't pin a schema keep the pre-fix shape."""
    kwargs = build_responses_kwargs(_req(), backend="codex", adapter_name="codex-oauth")
    assert "text" not in kwargs


def test_codex_kwargs_wires_response_schema_to_text_format() -> None:
    """Responses API structured output: ``text.format = {type:"json_schema", ...}``.

    PR-CODEX-OAUTH-RESPONSE-SCHEMA — codex-oauth was the only PR-JSON-WIRE
    adapter that silently dropped ``req.response_schema``. Smoke 17
    evidence: 20+ ``codex-oauth-empty-text`` dumps because gpt-5.5
    burned the output budget on encrypted reasoning with no API-level
    JSON enforcement. This test pins the wire-through.

    Note: ``_VOTE_SCHEMA`` is NOT strict-compatible (no
    ``additionalProperties: false``) so ``strict`` is auto-detected to
    ``False``. Strict=True is exercised by
    ``test_codex_kwargs_text_format_strict_true_for_strict_compat_schema``.
    """
    kwargs = build_responses_kwargs(
        _req(response_schema=_VOTE_SCHEMA), backend="codex", adapter_name="codex-oauth"
    )
    assert "text" in kwargs, "text.format missing — codex-oauth silently dropped response_schema"
    text = kwargs["text"]
    assert isinstance(text, dict)
    fmt = text["format"]
    assert fmt["type"] == "json_schema"
    # Auto-detect: VOTE_SCHEMA lacks additionalProperties:false → strict=False.
    assert fmt["strict"] is False
    assert fmt["schema"] == _VOTE_SCHEMA
    # Name derived from schema title when present.
    assert fmt["name"] == "vote"


def test_codex_kwargs_text_format_name_fallback_when_no_title() -> None:
    """Schemas without ``title`` get a generic ``response`` name."""
    untitled = {k: v for k, v in _VOTE_SCHEMA.items() if k != "title"}
    kwargs = build_responses_kwargs(
        _req(response_schema=untitled), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["name"] == "response"


def test_codex_kwargs_text_format_coexists_with_reasoning() -> None:
    """Voter call shape: gpt-5.5 reasoning model + structured output.

    The fix must not regress the reasoning kwargs — both blocks coexist.
    """
    kwargs = build_responses_kwargs(
        _req(response_schema=_VOTE_SCHEMA), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]
    assert kwargs["text"]["format"]["type"] == "json_schema"


# --- Strict-mode auto-detection (Codex MCP review of PR #1687) -------------


_STRICT_COMPAT_SCHEMA: dict[str, object] = {
    "title": "strict_person",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "number"},
    },
    "required": ["name", "age"],
    "additionalProperties": False,
}


def test_codex_kwargs_text_format_strict_true_for_strict_compat_schema() -> None:
    """Strict mode enabled when schema satisfies the OpenAI subset.

    Codex MCP review of PR #1687 caught that unconditional strict=True
    would cause the server to reject GEODE's seed-generation schemas
    (which lack ``additionalProperties: false``). The adapter
    auto-detects strict compatibility and passes ``strict: True`` only
    when the schema meets the constraints. ctx7 spec (Responses API
    docs): every object schema must set ``additionalProperties: false``
    AND list every property in ``required``.
    """
    kwargs = build_responses_kwargs(
        _req(response_schema=_STRICT_COMPAT_SCHEMA), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["strict"] is True


def test_codex_kwargs_text_format_strict_false_when_additional_properties_open() -> None:
    """GEODE's ``_additive`` schemas omit ``additionalProperties: false``
    so they cannot ride strict mode without being rewritten."""
    open_schema = {
        "title": "open",
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
        # NB: no additionalProperties → not strict-compatible
    }
    kwargs = build_responses_kwargs(
        _req(response_schema=open_schema), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["strict"] is False


def test_codex_kwargs_text_format_strict_false_when_required_misses_property() -> None:
    """Strict mode requires every property listed in ``required``."""
    partial_required = {
        "title": "partial",
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string"},
        },
        "required": ["a"],  # b missing
        "additionalProperties": False,
    }
    kwargs = build_responses_kwargs(
        _req(response_schema=partial_required), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["strict"] is False


def test_codex_kwargs_text_format_strict_false_when_typed_additional_properties() -> None:
    """``additionalProperties: {"type": "number"}`` (typed extra) is NOT
    the same as ``false`` — strict mode rejects typed extras.

    META_REVIEW_SCHEMA uses this shape for sparse per-dim coverage
    dictionaries — auto-detect must catch and fall back to non-strict.
    """
    typed_extra = {
        "title": "typed_extra",
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["scores"],
        "additionalProperties": False,
    }
    kwargs = build_responses_kwargs(
        _req(response_schema=typed_extra), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["strict"] is False


def test_codex_kwargs_text_format_strict_recurses_into_array_items() -> None:
    """Array ``items`` schemas must also be strict-compatible."""
    array_of_open = {
        "title": "array_of_open",
        "type": "object",
        "properties": {
            "list": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                    # items lack additionalProperties → not strict
                },
            },
        },
        "required": ["list"],
        "additionalProperties": False,
    }
    kwargs = build_responses_kwargs(
        _req(response_schema=array_of_open), backend="codex", adapter_name="codex-oauth"
    )
    assert kwargs["text"]["format"]["strict"] is False


# --- PR-OPENAI-CACHE-KEY (2026-06-23) — prompt_cache_key routing hint -------


def test_prompt_cache_key_set_on_both_backends() -> None:
    """Both the Codex subscription backend (live-verified 2026-06-23) and the
    platform Responses API carry the cache-routing key."""
    for backend in ("codex", "platform"):
        kwargs = build_responses_kwargs(
            _req(system_prompt="stable instructions"), backend=backend, adapter_name="x"
        )
        assert kwargs["prompt_cache_key"].startswith("geode-")


def test_prompt_cache_key_stable_across_dynamic_suffix() -> None:
    """Keyed on the STATIC prefix (before <dynamic_context>) so a changing
    dynamic suffix (date / recalled memory) does not perturb the routing key —
    the whole point of a stable per-session key."""
    static = "you are geode"
    a = _prompt_cache_key(f"{static}{PROMPT_CACHE_BOUNDARY}date: monday\nmemory: x")
    b = _prompt_cache_key(f"{static}{PROMPT_CACHE_BOUNDARY}date: tuesday\nmemory: y")
    assert a == b
    assert a.startswith("geode-")


def test_prompt_cache_key_differs_on_static_change() -> None:
    assert _prompt_cache_key("agent A instructions") != _prompt_cache_key("agent B instructions")


def test_prompt_cache_key_empty_system_prompt_yields_no_key() -> None:
    assert _prompt_cache_key("") == ""
    kwargs = build_responses_kwargs(_req(system_prompt=""), backend="codex", adapter_name="x")
    assert "prompt_cache_key" not in kwargs


def test_prompt_cache_key_kill_switch_omits_key(monkeypatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "prompt_cache_key_enabled", False, raising=False)
    kwargs = build_responses_kwargs(_req(system_prompt="x"), backend="codex", adapter_name="x")
    assert "prompt_cache_key" not in kwargs

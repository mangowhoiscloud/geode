"""v0.53.1 hotfix — Codex adapter must return AgenticResponse, not dict.

Production incident 2026-04-27 (immediately after v0.53.0 ship): user
ran ``/model claude-opus-4-7 → gpt-5.5`` (which routes to ``openai-codex``
per v0.53.0 _CODEX_ONLY_MODELS) and got::

    'dict' object has no attribute 'usage'
    File "core/agent/loop.py", line 1565, in _track_usage
        if not response.usage:
                        ^^^^^

Root cause: ``CodexAgenticAdapter.agentic_call`` returned a raw dict via
the local ``_normalize_responses_api`` helper, while the agentic loop's
``_track_usage`` reads ``response.usage`` (attribute access). Anthropic
+ OpenAI PAYG adapters already use the standard
``core.llm.agentic_response.normalize_openai_responses`` which returns
the ``AgenticResponse`` dataclass (with ``.usage`` attribute). v0.52.7's
Codex parity refactor introduced tools/reasoning but missed this last
contract.

This invariant pins the parity: every agentic adapter MUST return an
``AgenticResponse`` (or ``None``), never a raw dict.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import core.llm.providers.codex as _codex_mod
from core.llm.agentic_response import AgenticResponse

# ---------------------------------------------------------------------------
# Contract 1 — source-level: Codex adapter calls the standard normaliser
# ---------------------------------------------------------------------------


def test_codex_agentic_call_uses_standard_normaliser() -> None:
    """Source-level: ``CodexAgenticAdapter.agentic_call`` must call
    ``normalize_openai_responses`` from ``core.llm.agentic_response``.
    Pre-fix it called a local ``_normalize_responses_api`` that returned
    a dict — incompatible with ``AgenticLoop._track_usage`` (attr access).
    """
    src = inspect.getsource(_codex_mod.CodexAgenticAdapter.agentic_call)
    assert "normalize_openai_responses(response)" in src, (
        "Codex adapter must call normalize_openai_responses(response) — "
        "without it the loop crashes on response.usage attribute access. "
        "This is the same normaliser the OpenAI PAYG adapter uses."
    )
    # The broken local helper must NOT be invoked (text inside docstrings/
    # comments is fine; we check for an actual call site).
    assert "_normalize_responses_api(response)" not in src, (
        "Local _normalize_responses_api(response) call must be removed "
        "from agentic_call — it shadowed the AgenticResponse path"
    )


def test_local_dict_normaliser_removed() -> None:
    """The legacy module-level ``_normalize_responses_api`` function
    that returned a raw dict must be removed entirely so no future call
    site can re-introduce the bug."""
    module_src = inspect.getsource(_codex_mod)
    assert "def _normalize_responses_api(" not in module_src, (
        "Legacy _normalize_responses_api(response) → dict definition "
        "must be removed; use normalize_openai_responses (returns "
        "AgenticResponse dataclass)"
    )


# ---------------------------------------------------------------------------
# Contract 2 — functional: agentic_call returns AgenticResponse end-to-end
# ---------------------------------------------------------------------------


def _build_fake_responses_api_response() -> Any:
    """Build a minimal OpenAI Responses API-shaped object with .output,
    .usage, .model — enough for normalize_openai_responses to consume."""
    response = MagicMock()
    # output[0] = a "message" with one text sub-block
    msg_block = MagicMock()
    msg_block.type = "message"
    text_sub = MagicMock()
    text_sub.type = "output_text"
    text_sub.text = "Hello from gpt-5.5"
    msg_block.content = [text_sub]
    response.output = [msg_block]
    response.model = "gpt-5.5"
    # usage shape — Responses API uses input_tokens / output_tokens
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 25
    response.usage.output_tokens_details = MagicMock(reasoning_tokens=10)
    return response


def test_codex_agentic_call_returns_agentic_response(monkeypatch) -> None:
    """End-to-end: invoke agentic_call with a fake SDK + assert the
    return type. Pre-fix returned dict → loop crashed."""
    import asyncio

    from core.llm.providers.codex import CodexAgenticAdapter

    fake_response = _build_fake_responses_api_response()

    # Mock the streaming Responses API client. ``stream`` (the result of
    # __enter__) must be both iterable (the loop iterates events) and
    # carry get_final_response().
    class _FakeStream:
        def __iter__(self):
            return iter([])

        def get_final_response(self):
            return fake_response

    fake_stream_inner = _FakeStream()
    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__ = MagicMock(return_value=fake_stream_inner)
    fake_stream_ctx.__exit__ = MagicMock(return_value=False)
    fake_client = MagicMock()
    fake_client.responses.stream = MagicMock(return_value=fake_stream_ctx)

    monkeypatch.setattr("core.llm.providers.codex._get_codex_client", lambda: fake_client)
    monkeypatch.setattr(
        "core.llm.providers.codex._codex_circuit_breaker",
        MagicMock(
            can_execute=lambda: True, record_success=lambda: None, record_failure=lambda: None
        ),
    )

    async def _direct(failover_models: list[str], do_call: Any) -> tuple[Any, str]:
        result = await do_call(failover_models[0])
        return result, failover_models[0]

    async def _run() -> Any:
        adapter = CodexAgenticAdapter()
        with patch("core.llm.providers.codex.call_with_failover", _direct):
            return await adapter.agentic_call(
                model="gpt-5.5",
                system="hi",
                messages=[{"role": "user", "content": "test"}],
                tools=[],
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.7,
                effort="high",
            )

    result = asyncio.run(_run())

    # The critical contract: AgenticResponse, not dict.
    assert isinstance(result, AgenticResponse), (
        f"Codex adapter returned {type(result).__name__} ({result!r}); "
        "must return AgenticResponse so loop._track_usage attribute "
        "access works"
    )
    # And usage is the dataclass form (attribute access works).
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 25
    assert result.usage.thinking_tokens == 10  # from reasoning_tokens
    # Content roundtrip.
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Hello from gpt-5.5"
    assert result.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# Contract 3 — _track_usage works on the returned AgenticResponse
# ---------------------------------------------------------------------------


def test_track_usage_accepts_agentic_response_from_codex(monkeypatch) -> None:
    """End-to-end: _track_usage(codex_result) must NOT raise. Pre-fix
    it raised AttributeError on dict.usage."""
    import core.agent.loop as _loop_mod

    fake_response = _build_fake_responses_api_response()
    from core.llm.agentic_response import normalize_openai_responses

    normalized = normalize_openai_responses(fake_response)
    assert isinstance(normalized, AgenticResponse)

    # Build a stub loop and bind the real _track_usage.
    stub = MagicMock()
    stub.model = "gpt-5.5"
    stub._quiet = True
    stub._track_usage = _loop_mod.AgenticLoop._track_usage.__get__(stub)
    # Must not raise.
    stub._track_usage(normalized)

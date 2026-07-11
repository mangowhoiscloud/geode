"""PR-CODEX-OAUTH-RESPONSE-SCHEMA (2026-05-25) — retry-edge regression pins.

Smoke 17 captured ~10 ``codex-oauth-empty-text`` dumps per ranker match.
The retry edge case unfolds at the adapter boundary as:

    1. AgenticLoop calls ``CodexOAuthAdapter.acomplete(req)``.
    2. Codex Responses SDK returns ``stop_reason=completed`` with empty
       ``output_text`` (gpt-5.5 reasoning-budget hijack — encrypted
       reasoning items emitted, visible answer block skipped).
    3. Adapter writes a postmortem dump + WARN, **returns the empty
       result** (no raise).
    4. Caller treats empty text as failure → classify_llm_error returns
       ``unknown`` → AgenticLoop retries with identical prompt + effort.
    5. Steps 2-4 repeat 5× → 5 dump files per voter.
    6. Ranker panel has 2× codex voters → ~10 dumps per match × N matches.

These tests pin the *adapter half* of the cycle:

- The empty-text dump fires when ``output_text == ""`` and the response
  contains no tool calls, regardless of whether ``response_schema`` was wired
  (PR-CODEX-OAUTH-EMPTY-TEXT-DUMP #78 forensic surface preserved).
- The request kwargs **shape changes** when ``response_schema`` is
  wired — the new ``text.format`` block forces the server to enforce
  the schema (PR-CODEX-OAUTH-RESPONSE-SCHEMA — this PR).

Together they document the exact request → response shape pair that
produced the smoke-17 dump pile-up, so a regression that reverts the
``text.format`` wire-through (or alters the dump-on-empty contract)
fails these tests instead of silently re-introducing the retry storm.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, EmptyModelOutputError, Message
from core.llm.adapters.codex_oauth import CodexOAuthAdapter

_VOTE_SCHEMA: dict[str, Any] = {
    "title": "vote",
    "type": "object",
    "properties": {
        "match_id": {"type": "string"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string"},
    },
    "required": ["match_id", "winner", "rationale"],
}


def _voter_req(*, schema: dict[str, Any] | None = None) -> AdapterCallRequest:
    """Build a voter-shape AdapterCallRequest (matches ranker.py:285)."""
    return AdapterCallRequest(
        model="gpt-5.5",
        messages=[Message(role="user", content="Judge match A vs B")],
        system_prompt="Role: ranker voter.",
        max_tokens=1024,
        response_schema=schema,
    )


class _MockStream:
    """Async-context-manager mock that mirrors ``client.responses.stream``."""

    def __init__(self, final_response: Any) -> None:
        self._final = final_response

    async def __aenter__(self) -> _MockStream:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    def __aiter__(self) -> _MockStream:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration

    async def get_final_response(self) -> Any:
        return self._final


def _build_mock_codex_client_empty_response() -> Any:
    """Mock client whose ``responses.stream(...)`` yields an empty-text final.

    Mirrors the exact SDK shape codex_oauth.acomplete consumes:
    ``responses.stream`` returns an async-context-manager that exposes
    ``get_final_response()`` returning an object with the Codex Responses
    API fields. Empty-text path: ``output_text=""`` + non-zero usage +
    reasoning_items present (gpt-5.5 reasoning-budget hijack).
    """
    final = SimpleNamespace(
        output_text="",
        output=[],
        usage=SimpleNamespace(input_tokens=1292, output_tokens=515),
        stop_reason="completed",
    )
    stream = _MockStream(final)

    def _create_stream(**_kwargs: Any) -> _MockStream:
        # Record kwargs on the mock for assertion.
        _create_stream.last_kwargs = _kwargs  # type: ignore[attr-defined]
        return stream

    client = MagicMock()
    client.responses.stream = MagicMock(side_effect=_create_stream)
    return client, _create_stream


# --- Edge case 1: empty response WITHOUT schema (smoke-17 reproduction) ------


def test_acomplete_empty_response_no_schema_dumps_and_returns_empty(
    tmp_path: Path,
) -> None:
    """Smoke-17 reproduction at the adapter boundary.

    No ``response_schema`` set → kwargs lack ``text.format`` → server
    free to return empty output_text. Adapter dumps + returns empty,
    triggering the upstream retry storm that this PR fixes.
    """
    client, capture = _build_mock_codex_client_empty_response()
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign] # bypass OAuth probe

    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        result = asyncio.run(adapter.acomplete(_voter_req(schema=None)))

    # Result is empty (the failure mode caller sees).
    assert result.text == ""
    # Dump fired — operator has forensic evidence.
    dumps = list((tmp_path / "codex-oauth-empty-text").glob("*-gpt-5.5.json"))
    assert len(dumps) == 1, f"expected 1 dump, got {len(dumps)}"
    payload = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert payload["stop_reason"] == "completed"
    assert payload["usage"]["output_tokens"] == 515
    # No text.format was sent — kwargs reflect the smoke-17 SOURCE shape.
    assert "text" not in capture.last_kwargs, (
        "Pre-fix kwargs shape: no text.format → server could return empty. "
        "If this assertion fails, the no-schema path acquired a text.format "
        "block somehow — investigate, because the smoke-17 reproduction is "
        "broken."
    )


def test_acomplete_empty_response_env_fail_fast_still_dumps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Benchmark routes can opt into treating empty output_text as infra failure."""
    client, _capture = _build_mock_codex_client_empty_response()
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "1")

    with (
        patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path),
        pytest.raises(EmptyModelOutputError, match="empty output_text") as error,
    ):
        asyncio.run(adapter.acomplete(_voter_req(schema=None)))

    dumps = list((tmp_path / "codex-oauth-empty-text").glob("*-gpt-5.5.json"))
    assert len(dumps) == 1
    error.value.mark_recovered()
    assert Path(f"{dumps[0]}.recovered").is_file()


def test_acomplete_empty_response_can_attest_actionable_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _capture = _build_mock_codex_client_empty_response()
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "1")

    with (
        patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path),
        pytest.raises(EmptyModelOutputError) as error,
    ):
        asyncio.run(adapter.acomplete(_voter_req(schema=None)))

    dump = next((tmp_path / "codex-oauth-empty-text").glob("*-gpt-5.5.json"))
    error.value.mark_actionable()
    assert Path(f"{dump}.actionable").is_file()


def test_acomplete_empty_response_cannot_attest_without_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _capture = _build_mock_codex_client_empty_response()
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "1")

    with (
        patch(
            "core.llm.adapters.codex_oauth._dump_empty_text_postmortem",
            return_value=None,
        ),
        pytest.raises(EmptyModelOutputError) as error,
    ):
        asyncio.run(adapter.acomplete(_voter_req(schema=None)))

    with pytest.raises(RuntimeError, match="without its diagnostic dump"):
        error.value.mark_recovered()
    with pytest.raises(RuntimeError, match="without its diagnostic dump"):
        error.value.mark_actionable()


def test_acomplete_empty_text_with_function_call_is_not_empty_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Responses tool-use turns usually have empty visible text.

    Crucible readiness runs caught a false positive where Codex returned a
    valid ``function_call`` item with ``output_text=""`` and the adapter raised
    the empty-text infra gate before AgenticLoop could execute the tool.
    """
    final = SimpleNamespace(
        output_text="",
        output=[
            SimpleNamespace(
                type="function_call",
                id="fc_1",
                call_id="call_1",
                name="get_customer_by_phone",
                arguments='{"phone_number":"555-123-2002"}',
                status="completed",
            )
        ],
        usage=SimpleNamespace(input_tokens=1292, output_tokens=26),
        status="completed",
    )

    def _create_stream(**_kwargs: Any) -> _MockStream:
        return _MockStream(final)

    client = MagicMock()
    client.responses.stream = MagicMock(side_effect=_create_stream)
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "1")

    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        result = asyncio.run(adapter.acomplete(_voter_req(schema=None)))

    assert result.text == ""
    assert len(result.tool_uses) == 1
    assert result.tool_uses[0]["name"] == "get_customer_by_phone"
    dump_dir = tmp_path / "codex-oauth-empty-text"
    assert not dump_dir.exists() or list(dump_dir.glob("*.json")) == []


# --- Edge case 2: empty response WITH schema (defense in depth) -------------


def test_acomplete_empty_response_with_schema_still_dumps(tmp_path: Path) -> None:
    """Defense in depth.

    Even with ``text.format`` set (strict=true), the server *might*
    still return empty in edge cases (server bug, model hard refusal,
    transient state). The dump must still fire so operators see the
    schema was attempted but still produced empty — without this the
    fix-correctness story is opaque. The kwargs assert the schema was
    in flight.
    """
    client, capture = _build_mock_codex_client_empty_response()
    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]

    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        result = asyncio.run(adapter.acomplete(_voter_req(schema=_VOTE_SCHEMA)))

    assert result.text == ""
    dumps = list((tmp_path / "codex-oauth-empty-text").glob("*-gpt-5.5.json"))
    assert len(dumps) == 1
    # text.format WAS sent — proves the fix path is exercised even on
    # this edge-case empty response. A future operator inspecting the
    # dump can correlate by checking the kwargs path.
    assert "text" in capture.last_kwargs
    assert capture.last_kwargs["text"]["format"]["type"] == "json_schema"
    # ``_VOTE_SCHEMA`` is not strict-compatible (no
    # ``additionalProperties: false``) so the adapter falls back to
    # ``strict: False`` — schema still forwarded as a server hint but
    # without the request-side rejection that strict=True triggers on
    # GEODE schemas. The strict=True path is exercised separately by
    # ``test_codex_kwargs_text_format_strict_true_for_strict_compat_schema``
    # in test_codex_oauth_backend_invariants.py.
    assert capture.last_kwargs["text"]["format"]["strict"] is False
    assert capture.last_kwargs["text"]["format"]["schema"] == _VOTE_SCHEMA


# --- Edge case 3: non-empty response WITH schema (happy path) ---------------


def test_acomplete_non_empty_response_with_schema_no_dump(tmp_path: Path) -> None:
    """Happy path — schema set, server returns a valid JSON answer.

    No dump fires (the dump-on-empty contract only triggers on empty
    text). Validates the post-fix outcome the smoke 17 ranker should
    reach for every codex voter call once the server-side enforcement
    actually rejects reasoning-only responses.
    """
    json_text = '{"match_id":"m000","winner":"A","rationale":"clearer rationale"}'
    final = SimpleNamespace(
        output_text=json_text,
        output=[],
        usage=SimpleNamespace(input_tokens=1292, output_tokens=120),
        stop_reason="completed",
    )

    def _create_stream(**_kwargs: Any) -> _MockStream:
        return _MockStream(final)

    client = MagicMock()
    client.responses.stream = MagicMock(side_effect=_create_stream)

    adapter = CodexOAuthAdapter()
    adapter._get_client = lambda: client  # type: ignore[method-assign]

    with patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path):
        result = asyncio.run(adapter.acomplete(_voter_req(schema=_VOTE_SCHEMA)))

    assert result.text == json_text
    # Zero dumps — no retry edge fires.
    dump_dir = tmp_path / "codex-oauth-empty-text"
    assert not dump_dir.exists() or list(dump_dir.glob("*.json")) == []


# --- Edge case 4: kwargs invariant — fix didn't drop pre-existing fields ---


def test_acomplete_with_schema_preserves_codex_backend_invariants() -> None:
    """The fix adds ``text.format`` but must NOT drop existing Codex
    backend invariants (store=False, instructions, no max_output_tokens,
    reasoning block for gpt-5.x). Pre-existing invariants from
    test_codex_oauth_backend_invariants.py are re-validated here in the
    presence of a schema so a regression that "fixes" one block by
    dropping another (e.g. an over-eager refactor that overwrites kwargs)
    is caught.
    """
    kwargs = build_responses_kwargs(
        _voter_req(schema=_VOTE_SCHEMA), backend="codex", adapter_name="codex-oauth"
    )
    # Pre-PR invariants (must coexist with the new text block).
    assert kwargs["store"] is False
    assert kwargs["instructions"] == "Role: ranker voter."
    assert "max_output_tokens" not in kwargs
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs  # gpt-5.5 reasoning model
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]
    # New PR field.
    assert kwargs["text"]["format"]["type"] == "json_schema"


# --- Edge case 5: pre-fix vs post-fix kwargs diff (regression sentinel) -----


def test_kwargs_text_format_is_the_only_schema_difference() -> None:
    """Sentinel: the only kwargs shape change between
    ``response_schema=None`` and ``response_schema=VOTE_SCHEMA`` must be
    the presence of ``text.format``. If a future change to
    ``_build_codex_call_kwargs`` quietly diverges other fields based on
    schema presence, this test catches it before it lands in production.
    """
    no_schema = build_responses_kwargs(
        _voter_req(schema=None), backend="codex", adapter_name="codex-oauth"
    )
    with_schema = build_responses_kwargs(
        _voter_req(schema=_VOTE_SCHEMA), backend="codex", adapter_name="codex-oauth"
    )

    # Drop the differing field and assert the rest is identical.
    with_schema_pruned = {k: v for k, v in with_schema.items() if k != "text"}
    assert no_schema == with_schema_pruned
    assert "text" not in no_schema
    assert "text" in with_schema


# Silence the AsyncMock import (kept for future tests that mock SDK
# methods that ARE async; current tests use sync MagicMock + sentinel
# objects which is sufficient for ``responses.stream``).
_ = AsyncMock

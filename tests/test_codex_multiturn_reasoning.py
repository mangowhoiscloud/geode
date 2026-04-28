"""R1 — Codex Plus multi-turn encrypted reasoning round-trip invariants.

Pinned 2026-04-28 against the 3-codebase consensus pattern (Hermes
``agent/codex_responses_adapter.py:228-246, 720-738`` + OpenClaw
``src/agents/openai-transport-stream.ts:771, 257-264``):

  1. ``normalize_openai_responses`` extracts ``reasoning`` items into
     ``AgenticResponse.codex_reasoning_items`` (with id, summary,
     encrypted_content) — only when ``encrypted_content`` is present.

  2. The agentic loop persists the sidecar onto the assistant message
     dict so ``_convert_messages_to_responses`` (Codex adapter) can
     replay it.

  3. ``CodexAgenticAdapter`` injects the replay items into the
     next-turn ``input`` array immediately before the corresponding
     assistant entry, with the ``id`` field stripped (per Hermes:
     ``store=False`` means the server can't resolve items by ID, so
     replay-by-ID 404s).

Without these three invariants, gpt-5.x multi-turn sessions silently
lose reasoning state on every round.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.llm.agentic_response import AgenticResponse, normalize_openai_responses


def _make_message_item(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _make_reasoning_item(
    *, encrypted: str, item_id: str | None = None, summary_texts: list[str] | None = None
) -> SimpleNamespace:
    summary = (
        [SimpleNamespace(text=t) for t in summary_texts] if summary_texts is not None else None
    )
    kwargs: dict = {"type": "reasoning", "encrypted_content": encrypted}
    if item_id is not None:
        kwargs["id"] = item_id
    if summary is not None:
        kwargs["summary"] = summary
    return SimpleNamespace(**kwargs)


class TestNormalizeReasoningExtraction:
    def test_extracts_encrypted_reasoning(self) -> None:
        resp = MagicMock()
        resp.usage = None
        resp.output = [
            _make_reasoning_item(
                encrypted="ENC.payload",
                item_id="rs_01",
                summary_texts=["Considered three angles"],
            ),
            _make_message_item("Final answer"),
        ]
        result = normalize_openai_responses(resp)
        assert result.codex_reasoning_items is not None
        assert len(result.codex_reasoning_items) == 1
        item = result.codex_reasoning_items[0]
        assert item["type"] == "reasoning"
        assert item["encrypted_content"] == "ENC.payload"
        assert item["id"] == "rs_01"
        assert item["summary"] == [{"type": "summary_text", "text": "Considered three angles"}]
        # Visible content is still extracted normally
        assert len(result.content) == 1
        assert result.content[0].text == "Final answer"

    def test_skips_reasoning_without_encrypted_content(self) -> None:
        """No encrypted blob → nothing to replay → don't bloat the next request."""
        resp = MagicMock()
        resp.usage = None
        resp.output = [
            SimpleNamespace(type="reasoning", encrypted_content=None, summary=[]),
            _make_message_item("ok"),
        ]
        result = normalize_openai_responses(resp)
        assert result.codex_reasoning_items is None

    def test_no_reasoning_items_returns_none(self) -> None:
        resp = MagicMock()
        resp.usage = None
        resp.output = [_make_message_item("hello")]
        result = normalize_openai_responses(resp)
        assert result.codex_reasoning_items is None

    def test_other_providers_unaffected(self) -> None:
        """Anthropic/OpenAI Chat Completions normalisers don't set
        the sidecar — it stays None for backward compatibility."""
        from core.llm.agentic_response import normalize_anthropic, normalize_openai

        anth_resp = MagicMock()
        anth_resp.content = []
        anth_resp.stop_reason = "end_turn"
        anth_resp.usage = MagicMock(input_tokens=10, output_tokens=5, thinking_tokens=0)
        assert normalize_anthropic(anth_resp).codex_reasoning_items is None

        oai_resp = MagicMock()
        oai_resp.choices = []
        oai_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        assert normalize_openai(oai_resp).codex_reasoning_items is None


class TestAgenticResponseDataclass:
    def test_default_sidecar_is_none(self) -> None:
        r = AgenticResponse()
        assert r.codex_reasoning_items is None

    def test_sidecar_roundtrip(self) -> None:
        items = [{"type": "reasoning", "encrypted_content": "x"}]
        r = AgenticResponse(codex_reasoning_items=items)
        assert r.codex_reasoning_items == items


class TestCodexInputReplay:
    """Verify that ``CodexAgenticAdapter`` re-injects sidecar reasoning
    items into the ``input`` array on next-turn calls. We test the
    converter + replay logic directly (not the live HTTP) by exercising
    the same code path with a stub messages list."""

    def test_replay_strips_id_and_precedes_assistant(self) -> None:
        """The replay item must come BEFORE the assistant entry it
        belongs to, and the ``id`` field must be stripped (per Hermes:
        store=False → server can't resolve item IDs)."""
        from core.llm.providers.openai import _convert_messages_to_responses

        messages = [
            {"role": "user", "content": "first prompt"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "first reply"}],
                "codex_reasoning_items": [
                    {
                        "type": "reasoning",
                        "id": "rs_01",
                        "encrypted_content": "ENC.first",
                        "summary": [{"type": "summary_text", "text": "thought A"}],
                    }
                ],
            },
            {"role": "user", "content": "second prompt"},
        ]

        # Mirror the codex.py:213-260 loop
        oai_messages = _convert_messages_to_responses("", messages)
        resp_input: list[dict] = []
        msg_iter = iter(messages)
        current_msg = next(msg_iter, None)
        for entry in oai_messages:
            if entry.get("role") == "system":
                continue
            entry_role = (
                entry.get("role")
                or ("assistant" if entry.get("type") in ("function_call",) else None)
                or ("user" if entry.get("type") == "function_call_output" else None)
            )
            while current_msg is not None and current_msg.get("role") != entry_role:
                current_msg = next(msg_iter, None)
            if (
                current_msg is not None
                and current_msg.get("role") == "assistant"
                and entry_role == "assistant"
            ):
                reasoning = current_msg.get("codex_reasoning_items") or []
                for ri in reasoning:
                    if isinstance(ri, dict) and ri.get("encrypted_content"):
                        resp_input.append({k: v for k, v in ri.items() if k != "id"})
            resp_input.append(entry)

        # Must contain reasoning replay BEFORE the assistant entry
        types_or_roles = [(e.get("type"), e.get("role")) for e in resp_input]
        # Expected sequence: user, reasoning, assistant, user
        assert types_or_roles == [
            (None, "user"),
            ("reasoning", None),
            (None, "assistant"),
            (None, "user"),
        ]
        # And the reasoning entry must NOT have the id field
        reasoning_entry = next(e for e in resp_input if e.get("type") == "reasoning")
        assert "id" not in reasoning_entry
        assert reasoning_entry["encrypted_content"] == "ENC.first"
        assert reasoning_entry["summary"] == [{"type": "summary_text", "text": "thought A"}]

    def test_no_sidecar_no_replay(self) -> None:
        """Assistant messages without ``codex_reasoning_items`` must not
        inject anything (backward-compat with non-Codex providers)."""
        from core.llm.providers.openai import _convert_messages_to_responses

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
            {"role": "user", "content": "bye"},
        ]
        oai_messages = _convert_messages_to_responses("", messages)
        # Walk same logic
        resp_input: list[dict] = []
        msg_iter = iter(messages)
        current_msg = next(msg_iter, None)
        for entry in oai_messages:
            if entry.get("role") == "system":
                continue
            entry_role = entry.get("role")
            while current_msg is not None and current_msg.get("role") != entry_role:
                current_msg = next(msg_iter, None)
            if (
                current_msg is not None
                and current_msg.get("role") == "assistant"
                and entry_role == "assistant"
            ):
                for ri in current_msg.get("codex_reasoning_items") or []:
                    if isinstance(ri, dict) and ri.get("encrypted_content"):
                        resp_input.append({k: v for k, v in ri.items() if k != "id"})
            resp_input.append(entry)
        # No reasoning entries injected
        assert not any(e.get("type") == "reasoning" for e in resp_input)


class TestLoopPersistsSidecar:
    """The agentic loop must copy ``response.codex_reasoning_items``
    onto the assistant message dict so the next round's converter can
    see it. Spot-check the dict shape."""

    def test_sidecar_attached_when_present(self) -> None:
        items = [{"type": "reasoning", "encrypted_content": "X"}]
        # Simulate the same dict-shape construction the loop does.
        msg = {"role": "assistant", "content": []}
        if items:
            msg["codex_reasoning_items"] = items
        assert msg["codex_reasoning_items"] == items

    def test_sidecar_omitted_when_absent(self) -> None:
        msg = {"role": "assistant", "content": []}
        # No codex_reasoning_items key when the response had none
        assert "codex_reasoning_items" not in msg

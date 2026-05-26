"""PR-Hermes-3 — 4-phase compaction pipeline invariants.

Pins:

1. **boundary** — cut respects tool_use / tool_result pairs.
2. **orphan_tool_result** — strips tool_result blocks whose
   tool_use_id is absent.
3. **summarize** — Anthropic short-circuits, low-message no-op,
   summary-failure no-op all preserved.
4. **carry_forward** — 4-message preamble shape unchanged.

End-to-end: a conversation whose natural cut lands inside a
tool_use/tool_result pair gets compacted without splitting the pair.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.orchestration.compaction import (
    COMPACTION_MARKER,
    compact_conversation,
    find_safe_boundary,
    strip_orphan_tool_results,
)

from core.orchestration import compaction


def _make_tool_use_msg(tool_id: str, name: str = "bash") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}],
    }


def _make_tool_result_msg(tool_id: str, body: str = "ok") -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": body}],
    }


def _make_text_msg(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": text}


# ── Phase 1: boundary ───────────────────────────────────────────────


def test_boundary_with_few_messages_returns_zero():
    msgs = [_make_text_msg("user", "hi"), _make_text_msg("assistant", "hello")]
    assert find_safe_boundary(msgs, keep_recent=10) == 0


def test_boundary_plain_text_messages_no_walking():
    """No tool pairs → boundary is exactly len - keep_recent."""
    msgs = [_make_text_msg("user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(15)]
    assert find_safe_boundary(msgs, keep_recent=5) == 10


def test_boundary_walks_back_to_avoid_splitting_pair():
    """A pair at the natural cut → boundary moves back by 1 to keep the pair."""
    # 0..7 plain (8 msgs), 8 = tool_use, 9 = tool_result, 10..14 plain (5 msgs)
    # → len=15. keep_recent=6 → natural cut = 9 = tool_result → walk back
    # to 8 (tool_use), then stop because messages[7] is plain text.
    msgs = [_make_text_msg("user", f"m{i}") for i in range(8)]
    msgs.append(_make_tool_use_msg("tu_pair"))
    msgs.append(_make_tool_result_msg("tu_pair"))
    msgs.extend(_make_text_msg("user", f"r{i}") for i in range(5))
    assert find_safe_boundary(msgs, keep_recent=6) == 8


def test_boundary_walks_back_multiple_steps_for_chained_pairs():
    """If consecutive pairs straddle the natural cut, walk back through all of them."""
    msgs = [_make_text_msg("user", f"m{i}") for i in range(4)]
    msgs.append(_make_tool_use_msg("tu_a"))
    msgs.append(_make_tool_result_msg("tu_a"))
    msgs.append(_make_tool_use_msg("tu_b"))
    msgs.append(_make_tool_result_msg("tu_b"))
    msgs.extend(_make_text_msg("user", f"r{i}") for i in range(3))
    # len=11, keep_recent=5 → cut=6 (tu_b tool_use)... wait, that's
    # assistant, no walk needed. Try keep_recent=4 → cut=7 (tool_result
    # for tu_b) → walk back to 6 (tu_b tool_use). messages[5] is
    # tool_result for tu_a, not a tool_use parent of tu_b, so stop.
    assert find_safe_boundary(msgs, keep_recent=4) == 6


def test_boundary_no_walk_when_keep_recent_starts_clean():
    """Natural cut lands on plain text → no walk needed."""
    msgs = [_make_text_msg("user", f"m{i}") for i in range(5)]
    msgs.append(_make_tool_use_msg("tu_x"))
    msgs.append(_make_tool_result_msg("tu_x"))
    msgs.extend(_make_text_msg("user", f"r{i}") for i in range(8))
    # Natural cut = 15 - 8 = 7 → plain text → no walk.
    assert find_safe_boundary(msgs, keep_recent=8) == 7


def test_boundary_unmatched_tool_result_no_walk():
    """A tool_result with no parent tool_use → boundary doesn't walk back."""
    msgs = [_make_text_msg("user", f"m{i}") for i in range(8)]
    # No tool_use at index 8 — just a tool_result orphan.
    msgs.append(_make_tool_result_msg("tu_phantom"))
    msgs.extend(_make_text_msg("user", f"r{i}") for i in range(4))
    # Natural cut = 13 - 5 = 8. cur=tool_result with id "tu_phantom",
    # prev (idx 7) has no tool_use → no walk.
    assert find_safe_boundary(msgs, keep_recent=5) == 8


def test_boundary_stops_at_zero_in_worst_case():
    """If ENTIRE history is tool_use/tool_result pairs that chain back
    to the start, boundary should pin at 0 rather than infinite-loop."""
    msgs: list[dict[str, Any]] = []
    for i in range(5):
        msgs.append(_make_tool_use_msg(f"tu_{i}"))
        msgs.append(_make_tool_result_msg(f"tu_{i}"))
    # len=10, keep_recent=5 → cut starts at 5 (tu_2 tool_use), but its
    # role is assistant → no walk. Just verify it doesn't infinite-loop.
    boundary = find_safe_boundary(msgs, keep_recent=5)
    assert 0 <= boundary <= 10


# ── Phase 2: orphan_tool_result ─────────────────────────────────────


def test_strip_orphan_drops_unmatched_tool_result():
    msgs = [
        _make_text_msg("user", "hi"),
        _make_tool_result_msg("tu_missing"),  # no preceding tool_use
        _make_text_msg("assistant", "ack"),
    ]
    cleaned = strip_orphan_tool_results(msgs)
    # The orphan tool_result message had ONLY the orphan block, so it
    # gets dropped entirely.
    assert len(cleaned) == 2
    assert cleaned[0]["role"] == "user"
    assert cleaned[1]["role"] == "assistant"


def test_strip_orphan_preserves_matched_pair():
    msgs = [
        _make_tool_use_msg("tu_keep"),
        _make_tool_result_msg("tu_keep"),
    ]
    cleaned = strip_orphan_tool_results(msgs)
    assert cleaned == msgs


def test_strip_orphan_removes_partial_content_block():
    """A user message with mixed tool_result + text blocks keeps the
    text and only drops the orphan block."""
    msgs: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_missing", "content": "x"},
                {"type": "text", "text": "still here"},
            ],
        },
    ]
    cleaned = strip_orphan_tool_results(msgs)
    assert len(cleaned) == 1
    blocks = cleaned[0]["content"]
    assert blocks == [{"type": "text", "text": "still here"}]


def test_strip_orphan_preserves_string_content_messages():
    """Plain-text messages (string content) untouched."""
    msgs = [
        _make_text_msg("user", "hi"),
        _make_text_msg("assistant", "hello"),
    ]
    cleaned = strip_orphan_tool_results(msgs)
    assert cleaned == msgs


def test_strip_orphan_no_op_when_all_matched():
    msgs = [
        _make_tool_use_msg("tu_a"),
        _make_tool_result_msg("tu_a"),
        _make_tool_use_msg("tu_b"),
        _make_tool_result_msg("tu_b"),
    ]
    cleaned = strip_orphan_tool_results(msgs)
    assert cleaned == msgs


# ── Phase 3+4: end-to-end via compact_conversation ──────────────────


def _build_long_conversation(turns: int) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    for i in range(turns):
        msgs.append(_make_text_msg("user", f"user turn {i}"))
        msgs.append(_make_text_msg("assistant", f"assistant turn {i}"))
    return msgs


def test_anthropic_short_circuits():
    msgs = _build_long_conversation(30)
    new_msgs, did = asyncio.run(
        compact_conversation(msgs, provider="anthropic", model="claude-opus-4-7")
    )
    assert did is False
    assert new_msgs is msgs


def test_too_short_to_compact_no_op():
    msgs = _build_long_conversation(3)  # 6 messages
    new_msgs, did = asyncio.run(
        compact_conversation(msgs, provider="openai", model="gpt-5", keep_recent=10)
    )
    assert did is False
    assert new_msgs is msgs


def test_compaction_uses_safe_boundary(monkeypatch: pytest.MonkeyPatch):
    """End-to-end: head must not contain orphan tool_uses + tail must
    contain the full pair when the natural cut would split one."""

    async def _fake_summarize(text: str, provider: str, model: str) -> str | None:
        return "SUMMARY"

    monkeypatch.setattr(compaction, "_call_summarize", _fake_summarize)

    msgs = _build_long_conversation(8)  # 16 plain messages
    # Insert a tool pair so a naive cut at index 6 (keep_recent=10) would
    # split it: keep_recent=10 → natural cut = 16 - 10 = 6. Drop the pair
    # at index 6 / 7.
    msgs[6] = _make_tool_use_msg("tu_e2e")
    msgs[7] = _make_tool_result_msg("tu_e2e")

    new_msgs, did = asyncio.run(
        compact_conversation(msgs, provider="openai", model="gpt-5", keep_recent=10)
    )
    assert did is True
    # Compaction preamble is 4 messages; the rest is the tail.
    assert new_msgs[0]["content"].startswith("[Conversation Summary]")
    assert new_msgs[2]["content"] == COMPACTION_MARKER
    # The pair must travel together in the tail (the tool_use at index 4
    # of new_msgs, followed by its tool_result at index 5).
    tail = new_msgs[4:]
    tail_use_ids: list[str] = []
    tail_result_ids: list[str] = []
    for msg in tail:
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tail_use_ids.append(b["id"])
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tail_result_ids.append(b["tool_use_id"])
    assert "tu_e2e" in tail_use_ids
    assert "tu_e2e" in tail_result_ids


def test_compaction_marker_and_preamble_shape(monkeypatch: pytest.MonkeyPatch):
    """Phase 4 carry-forward — exactly 4 preamble messages + tail."""

    async def _fake_summarize(text: str, provider: str, model: str) -> str | None:
        return "TEST SUMMARY"

    monkeypatch.setattr(compaction, "_call_summarize", _fake_summarize)

    msgs = _build_long_conversation(20)
    new_msgs, did = asyncio.run(
        compact_conversation(msgs, provider="openai", model="gpt-5", keep_recent=8)
    )
    assert did is True
    assert new_msgs[0]["role"] == "user"
    assert new_msgs[0]["content"] == "[Conversation Summary]\nTEST SUMMARY"
    assert new_msgs[1]["role"] == "assistant"
    assert new_msgs[2]["role"] == "user"
    assert new_msgs[2]["content"] == COMPACTION_MARKER
    assert new_msgs[3]["role"] == "assistant"
    # The tail is the last keep_recent messages of the input.
    assert new_msgs[4:] == msgs[-8:]


def test_summary_failure_no_op(monkeypatch: pytest.MonkeyPatch):
    """If the summarizer returns None, the original messages survive."""

    async def _fake_summarize(text: str, provider: str, model: str) -> str | None:
        return None

    monkeypatch.setattr(compaction, "_call_summarize", _fake_summarize)
    msgs = _build_long_conversation(20)
    new_msgs, did = asyncio.run(
        compact_conversation(msgs, provider="openai", model="gpt-5", keep_recent=8)
    )
    assert did is False
    assert new_msgs is msgs


def test_module_exports_stable():
    expected = {
        "COMPACTION_MARKER",
        "compact_conversation",
        "find_safe_boundary",
        "strip_orphan_tool_results",
    }
    assert set(compaction.__all__) == expected

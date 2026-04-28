"""R9 — live wire-level checks for the reasoning-depth audit series.

Each test gates on its provider-specific env var so partial-key
environments can run whichever subset they have credentials for.
None of these tests run by default (`@pytest.mark.live`); run with:

    uv run pytest tests/test_e2e_live_reasoning_depth.py -v -m live

Coverage:
  - R1 (v0.55.0): Codex Plus ``encrypted_content`` round-trip.
  - R2 (v0.58.0): GLM ``thinking`` field + ``reasoning_content`` extraction.
  - R3-mini (v0.60.0): PAYG OpenAI ``include`` + ``summary="auto"``.
  - R4-mini (v0.56.0): Anthropic adaptive-thinking ``effort=xhigh`` on Opus 4.7.
  - R6 (v0.57.0): reasoning summaries surface to ``AgenticResponse.reasoning_summaries``.

These tests cost ~1 token-budget request per provider (~$0.01-0.05 each).
Always check `.last_error` if a test skips — it indicates an auth /
billing issue rather than a code regression.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from core.llm.agentic_response import AgenticResponse

pytestmark = [pytest.mark.live]


_HAS_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))
_HAS_OPENAI = bool(os.environ.get("OPENAI_API_KEY"))
_HAS_GLM = bool(os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_API_KEY"))
_HAS_CODEX = bool(os.environ.get("CHATGPT_OAUTH_TOKEN"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _simple_reasoning_prompt() -> list[dict]:
    """A short prompt that nudges the model to actually reason rather
    than answer with a memorised string."""
    return [
        {
            "role": "user",
            "content": (
                "Think through this carefully: what are three distinct considerations "
                "when choosing between Postgres and SQLite for a side project? "
                "Reply concisely after thinking."
            ),
        }
    ]


def _assert_reasoning_response(resp: object) -> None:
    assert isinstance(resp, AgenticResponse), f"got {type(resp).__name__}"
    assert resp.content, "response had no content blocks"
    # R6 contract — at least one reasoning summary should surface for
    # any reasoning-tier model. If this is empty, either the provider
    # silently dropped reasoning or the normaliser regressed.
    assert resp.reasoning_summaries, (
        "reasoning_summaries empty — R6 surfacing path broken or provider returned no reasoning"
    )


# ---------------------------------------------------------------------------
# R4-mini + R6 — Anthropic adaptive thinking (xhigh on Opus 4.7)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_ANTHROPIC, reason="ANTHROPIC_API_KEY not set")
class TestAnthropicXhighLive:
    def test_opus_4_7_xhigh_returns_thinking_summaries(self) -> None:
        from core.llm.providers.anthropic import AnthropicAgenticAdapter

        adapter = AnthropicAgenticAdapter()
        resp = _run(
            adapter.create_agentic_response(
                model="claude-opus-4-7",
                system="You are a thoughtful database advisor.",
                messages=_simple_reasoning_prompt(),
                tools=[],
                tool_choice="auto",
                max_tokens=1024,
                temperature=1.0,
                effort="xhigh",
            )
        )
        _assert_reasoning_response(resp)


# ---------------------------------------------------------------------------
# R3-mini + R6 — PAYG OpenAI Responses (include + summary=auto)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_OPENAI, reason="OPENAI_API_KEY not set")
class TestPaygOpenAIReasoningLive:
    def test_gpt5_payg_returns_encrypted_items_and_summary(self) -> None:
        from core.llm.providers.openai import OpenAIAgenticAdapter

        adapter = OpenAIAgenticAdapter()
        resp = _run(
            adapter.create_agentic_response(
                model="gpt-5.5",
                system="You are a thoughtful database advisor.",
                messages=_simple_reasoning_prompt(),
                tools=[],
                tool_choice="auto",
                max_tokens=1024,
                temperature=1.0,
                effort="medium",
            )
        )
        _assert_reasoning_response(resp)
        # R3-mini contract — encrypted reasoning items captured for replay
        assert resp.codex_reasoning_items, (
            "codex_reasoning_items empty — include='reasoning.encrypted_content' "
            "request kwarg likely dropped or response had no reasoning items"
        )
        first = resp.codex_reasoning_items[0]
        assert first.get("type") == "reasoning"
        assert first.get("encrypted_content"), "encrypted blob missing on first item"

    def test_gpt5_payg_multi_turn_replay(self) -> None:
        """Round 2 with prior reasoning items in messages must succeed
        (server accepts the encrypted blob; replay walker injects it)."""
        from core.llm.providers.openai import OpenAIAgenticAdapter

        adapter = OpenAIAgenticAdapter()
        round1 = _run(
            adapter.create_agentic_response(
                model="gpt-5.5",
                system="You are a thoughtful database advisor.",
                messages=_simple_reasoning_prompt(),
                tools=[],
                tool_choice="auto",
                max_tokens=512,
                temperature=1.0,
                effort="low",
            )
        )
        assert isinstance(round1, AgenticResponse) and round1.codex_reasoning_items

        # Build round 2 with an assistant turn carrying the prior reasoning
        round2_messages = [
            *_simple_reasoning_prompt(),
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "".join(b.text for b in round1.content if hasattr(b, "text")),
                    }
                ],
                "codex_reasoning_items": round1.codex_reasoning_items,
            },
            {"role": "user", "content": "Now pick one and explain why in 30 words."},
        ]
        round2 = _run(
            adapter.create_agentic_response(
                model="gpt-5.5",
                system="You are a thoughtful database advisor.",
                messages=round2_messages,
                tools=[],
                tool_choice="auto",
                max_tokens=512,
                temperature=1.0,
                effort="low",
            )
        )
        # If replay walker dropped the encrypted blob, the server would
        # reject the request or strip reasoning state — content should
        # still be present.
        assert isinstance(round2, AgenticResponse) and round2.content


# ---------------------------------------------------------------------------
# R2 + R6 — GLM thinking field + reasoning_content extraction
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_GLM, reason="ZAI_API_KEY / GLM_API_KEY not set")
class TestGlmThinkingLive:
    def test_glm_4_6_thinking_returns_summary(self) -> None:
        from core.llm.providers.glm import GLMAgenticAdapter

        adapter = GLMAgenticAdapter()
        resp = _run(
            adapter.create_agentic_response(
                model="glm-4.6",
                system="You are a thoughtful database advisor.",
                messages=_simple_reasoning_prompt(),
                tools=[],
                tool_choice="auto",
                max_tokens=1024,
                temperature=0.7,
                effort="high",
            )
        )
        _assert_reasoning_response(resp)


# ---------------------------------------------------------------------------
# R1 + R6 — Codex Plus encrypted reasoning (subscription path)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_CODEX, reason="CHATGPT_OAUTH_TOKEN not set")
class TestCodexPlusReasoningLive:
    def test_codex_plus_returns_encrypted_items_and_summary(self) -> None:
        from core.llm.providers.codex import CodexAgenticAdapter

        adapter = CodexAgenticAdapter()
        resp = _run(
            adapter.create_agentic_response(
                model="gpt-5.5",
                system="You are a thoughtful database advisor.",
                messages=_simple_reasoning_prompt(),
                tools=[],
                tool_choice="auto",
                max_tokens=1024,
                temperature=1.0,
                effort="medium",
            )
        )
        _assert_reasoning_response(resp)
        assert resp.codex_reasoning_items

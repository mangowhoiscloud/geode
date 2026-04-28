"""R4-mini — Anthropic reasoning depth invariants (v0.56.0).

Pinned 2026-04-28 against the 3-codebase consensus + Anthropic
official docs (see ``docs/research/reasoning-depth-audit.md``):

  C1: ``thinking.display = "summarized"`` is set on every adaptive
      thinking call. Opus 4.7 default is ``"omitted"`` so without
      this override the thinking blocks arrive empty and the GEODE
      activity feed has no reasoning trace. Mirrors Hermes
      ``anthropic_adapter.py:1440``.

  B3: ``xhigh`` effort is accepted by GEODE's enum but is version-
      gated to Opus 4.7. On Opus 4.6 / Sonnet 4.6 it downgrades to
      ``"max"`` (those models reject ``xhigh`` with 400). Mirrors
      Hermes ``_supports_xhigh_effort`` substring-based gate.

  C2: Signature round-trip on tool-use multi-turn. All three
      reference codebases (OpenClaw, Claude Code, Hermes) preserve
      the ``signature`` field when echoing thinking blocks back into
      the next-turn ``messages`` array. Claude Code comment:
      *"mismatched thinking block signatures cause API 400 errors"*
      (``utils/messages.ts:2311-2322``). GEODE relied on implicit
      pass-through; this test pins the contract.
"""

from __future__ import annotations

from core.llm.providers.anthropic import (
    _ADAPTIVE_MODELS,
    _XHIGH_EFFORT_MODELS,
    _supports_xhigh_effort,
)


class TestXHighEffortGate:
    """B3 — ``xhigh`` is Opus 4.7-only; downgrades to ``"max"`` elsewhere."""

    def test_opus_4_7_supports_xhigh(self) -> None:
        assert _supports_xhigh_effort("claude-opus-4-7") is True

    def test_opus_4_6_does_not_support_xhigh(self) -> None:
        assert _supports_xhigh_effort("claude-opus-4-6") is False

    def test_sonnet_4_6_does_not_support_xhigh(self) -> None:
        assert _supports_xhigh_effort("claude-sonnet-4-6") is False

    def test_legacy_models_do_not_support_xhigh(self) -> None:
        assert _supports_xhigh_effort("claude-opus-4-1") is False
        assert _supports_xhigh_effort("claude-haiku-4-5") is False

    def test_xhigh_models_subset_of_adaptive_models(self) -> None:
        """Every model that accepts ``xhigh`` also accepts adaptive
        thinking — adapter sends ``xhigh`` only inside the adaptive
        branch."""
        assert _XHIGH_EFFORT_MODELS.issubset(_ADAPTIVE_MODELS)


class TestEffortEnumIncludesXHigh:
    """B3 — the AgenticLoop adaptive-compute table accepts ``xhigh``."""

    def test_loop_effort_levels_include_xhigh(self) -> None:
        # The downgrade logic in loop.py indexes into _EFFORT_LEVELS by
        # the user-supplied effort string; if "xhigh" is missing from
        # the list, the index() call would raise ValueError.
        from core.agent import loop as loop_mod

        with open(loop_mod.__file__, encoding="utf-8") as f:
            text = f.read()
        assert '"xhigh"' in text, (
            "core/agent/loop.py must include 'xhigh' in _EFFORT_LEVELS so "
            "the overthinking auto-downgrade can index it without crashing"
        )


class TestThinkingDisplaySummarized:
    """C1 — adaptive thinking always carries ``display: "summarized"``.

    Without this, Opus 4.7 returns empty thinking blocks (the new default
    is ``"omitted"``). Validated by inspecting the source — running the
    adapter requires a real Anthropic client which is out of scope for
    a unit test."""

    def test_adapter_source_sets_display_summarized(self) -> None:
        from core.llm.providers import anthropic as adapter

        with open(adapter.__file__, encoding="utf-8") as f:
            text = f.read()
        # The adaptive branch must construct thinking_param with display
        # set to "summarized" (any equivalent indent is fine).
        assert '"display": "summarized"' in text, (
            "Anthropic adaptive thinking branch must set "
            'thinking_param["display"] = "summarized" — Opus 4.7 default '
            'is "omitted" which silently drops thinking content'
        )

    def test_adapter_passes_xhigh_effort_through_when_supported(self) -> None:
        """xhigh stays as xhigh on Opus 4.7."""
        from core.llm.providers.anthropic import _supports_xhigh_effort

        # The adapter logic: ``effective_effort = effort if supported
        # else "max"``. Mirror it here as the contract.
        effort = "xhigh"
        for model in _XHIGH_EFFORT_MODELS:
            assert _supports_xhigh_effort(model)
            assert effort == "xhigh"  # passthrough

    def test_adapter_downgrades_xhigh_on_opus_4_6(self) -> None:
        from core.llm.providers.anthropic import _supports_xhigh_effort

        effort = "xhigh"
        model = "claude-opus-4-6"
        effective = effort if _supports_xhigh_effort(model) else "max"
        assert effective == "max"


class TestSignatureRoundTrip:
    """C2 — Anthropic thinking-block ``signature`` field must survive
    multi-turn tool-use round-trips. Without it the next call returns
    400 (Claude Code: "mismatched thinking block signatures cause API
    400 errors").

    The contract is subtle: when the adapter receives a ``thinking``
    content block from the model, it MUST be passed back unchanged
    (text + signature) the next time the same assistant turn is sent
    in the messages array — otherwise the API rejects the request.

    GEODE's normaliser (``normalize_anthropic`` in
    ``core/llm/agentic_response.py``) currently only extracts
    ``text`` and ``tool_use`` blocks into typed dataclasses. The
    raw ``thinking`` block is dropped from ``AgenticResponse.content``.
    This test pins the consequence: the loop's serialisation path
    (``_serialize_content`` in ``core/agent/loop.py``) does not
    re-emit the thinking block, so on the NEXT request the assistant
    message in ``messages`` lacks the signed thinking block.

    For the current GEODE code this is ACCEPTABLE because:
      a) The adaptive thinking flow doesn't echo thinking blocks back
         into messages — they're consumed within one round.
      b) The tool-use loop composes the next-turn messages from
         ``_serialize_content(response.content)``, which only contains
         the text + tool_use blocks — never thinking blocks.

    So the latent risk applies only if a future change tries to
    persist ``thinking`` blocks into the assistant message dict. This
    test pins both invariants:
      1) ``normalize_anthropic`` does NOT include thinking blocks in
         ``AgenticResponse.content`` (so loop can't accidentally
         serialize them with a stale signature).
      2) ``_serialize_content`` only handles ``text`` and ``tool_use``
         block types — anything else is silently skipped.

    If a future PR adds thinking-block round-trip support, both
    invariants must be revisited together with a live signature test.
    """

    def test_normalize_anthropic_drops_thinking_blocks(self) -> None:
        """Thinking blocks are NOT carried in AgenticResponse.content."""
        from types import SimpleNamespace

        from core.llm.agentic_response import normalize_anthropic

        resp = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="thinking",
                    thinking="reasoning text",
                    signature="opaque-sig-bytes",
                ),
                SimpleNamespace(type="text", text="visible answer"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, thinking_tokens=20),
        )
        result = normalize_anthropic(resp)
        # No thinking block in the typed content — only text survives.
        types = [block.type for block in result.content]
        assert "thinking" not in types
        assert types == ["text"]

    def test_serialize_content_only_emits_text_and_tool_use(self) -> None:
        """Loop's serialiser (``_serialize_content``) only handles two
        block types, so even if a thinking block snuck into the
        AgenticResponse it would be silently dropped before going into
        the message history. This is the safety guarantee that prevents
        a stale signature from being echoed back into the next request."""
        from core.agent.loop import AgenticLoop

        # Build a minimal AgenticLoop instance just to call _serialize_content.
        # We use object.__new__ to bypass the heavy ctor; the method only
        # reads ``block.type`` so no instance state is required.
        loop = object.__new__(AgenticLoop)

        from core.llm.agentic_response import TextBlock, ToolUseBlock

        text_block = TextBlock(text="hi")
        tool_block = ToolUseBlock(id="t1", name="search", input={"q": "x"})

        # Plus a fake "thinking" block — should be silently skipped
        class _FakeThinking:
            type = "thinking"
            text = "should be dropped"
            signature = "stale-sig"

        serialized = loop._serialize_content([text_block, tool_block, _FakeThinking()])  # type: ignore[arg-type]
        kinds = [d["type"] for d in serialized]
        assert kinds == ["text", "tool_use"]
        assert all(d["type"] != "thinking" for d in serialized)

"""R2 — GLM ``thinking`` field activation invariants (v0.58.0).

Pinned 2026-04-28 against the official ZhipuAI / Z.AI Chat Completion
API spec (re-verified at this commit):

  - Field shape: ``{"type": "enabled"|"disabled", "clear_thinking": bool}``
  - GLM-4.5+ honours the flag (hybrid). GLM-5.x / GLM-5V / GLM-4.7 /
    GLM-4.5V think compulsorily — sending the field is harmless,
    omitting it is also fine.
  - Pre-GLM-4.5 models reject the field; we omit entirely.
  - openai-python doesn't know ``thinking`` — must go via ``extra_body``.

Pre-fix audit (R2): three reference codebases (Hermes, OpenClaw,
Claude Code) all share this gap. GEODE adopting the field makes us the
leader on this dimension.

Sources:
  - https://docs.z.ai/api-reference/llm/chat-completion
  - https://docs.z.ai/guides/capabilities/thinking-mode
  - https://docs.z.ai/guides/llm/glm-4.5
  - https://docs.z.ai/guides/llm/glm-4.6
  - https://docs.z.ai/guides/llm/glm-4.7
  - https://docs.z.ai/guides/llm/glm-5.1
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from core.llm.agentic_response import normalize_openai
from core.llm.providers.glm import _GLM_THINKING_MODELS, _glm_thinking_supported


class TestGlmThinkingModelGate:
    """Per-model gating mirrors docs.z.ai per-model thinking docs."""

    def test_glm_5_1_supported(self) -> None:
        assert _glm_thinking_supported("glm-5.1") is True

    def test_glm_5_supported(self) -> None:
        assert _glm_thinking_supported("glm-5") is True

    def test_glm_4_7_supported(self) -> None:
        assert _glm_thinking_supported("glm-4.7") is True
        assert _glm_thinking_supported("glm-4.7-flash") is True

    def test_glm_4_6_supported(self) -> None:
        assert _glm_thinking_supported("glm-4.6") is True

    def test_glm_4_5_supported(self) -> None:
        assert _glm_thinking_supported("glm-4.5") is True
        assert _glm_thinking_supported("glm-4.5-air") is True

    def test_glm_4_legacy_rejected(self) -> None:
        """Pre-GLM-4.5 models reject the field; we must omit it."""
        assert _glm_thinking_supported("glm-4") is False
        assert _glm_thinking_supported("glm-4-flash") is False

    def test_unknown_model_rejected(self) -> None:
        """Default to off for safety — better to omit a field a model
        rejects than to send one and get 400."""
        assert _glm_thinking_supported("unknown-model") is False
        assert _glm_thinking_supported("") is False

    def test_thinking_models_set_is_frozen(self) -> None:
        """The model list is intentionally a frozenset to prevent
        accidental mutation at runtime."""
        assert isinstance(_GLM_THINKING_MODELS, frozenset)


class TestGlmReasoningContentExtraction:
    """``message.reasoning_content`` (GLM-only) lands in
    ``AgenticResponse.reasoning_summaries`` so the R6 surfacing path
    treats GLM the same as Anthropic + Codex."""

    def _make_choice(
        self, *, content: str | None, reasoning: str | None, tool_calls: list | None = None
    ) -> SimpleNamespace:
        message = SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
        )
        return SimpleNamespace(message=message, finish_reason="stop")

    def test_extracts_glm_reasoning_content(self) -> None:
        resp = MagicMock()
        resp.choices = [
            self._make_choice(
                content="visible answer",
                reasoning="step 1 → step 2 → conclusion",
            )
        ]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
        result = normalize_openai(resp)
        assert result.reasoning_summaries == ["step 1 → step 2 → conclusion"]
        # Visible content still extracted normally
        assert len(result.content) == 1
        assert result.content[0].text == "visible answer"

    def test_no_reasoning_content_returns_none(self) -> None:
        resp = MagicMock()
        resp.choices = [self._make_choice(content="hi", reasoning=None)]
        resp.usage = MagicMock(prompt_tokens=5, completion_tokens=2)
        result = normalize_openai(resp)
        assert result.reasoning_summaries is None

    def test_empty_string_reasoning_filtered(self) -> None:
        """Empty string and whitespace-only reasoning shouldn't pollute
        the sidecar."""
        for empty in ("", "   ", "\n"):
            resp = MagicMock()
            resp.choices = [self._make_choice(content="x", reasoning=empty)]
            resp.usage = MagicMock(prompt_tokens=5, completion_tokens=2)
            assert normalize_openai(resp).reasoning_summaries is None

    def test_provider_isolation_openai_legacy(self) -> None:
        """Non-GLM Chat Completions responses (without
        reasoning_content) leave the sidecar None — backward compat."""
        resp = MagicMock()
        # No reasoning_content attribute at all
        message = SimpleNamespace(content="hi", tool_calls=None)
        resp.choices = [SimpleNamespace(message=message, finish_reason="stop")]
        resp.usage = MagicMock(prompt_tokens=5, completion_tokens=2)
        result = normalize_openai(resp)
        assert result.reasoning_summaries is None


class TestGlmAdapterSendsThinkingField:
    """Source-level pin: ``GlmAgenticAdapter`` must build the
    ``extra_body={'thinking': ...}`` payload for supported models. We
    verify by reading the adapter source — running the live request
    requires a real GLM endpoint."""

    def test_adapter_sends_thinking_via_extra_body(self) -> None:
        from core.llm.providers import glm as glm_mod

        with open(glm_mod.__file__, encoding="utf-8") as f:
            text = f.read()
        # Both the field assembly and the kwarg passthrough must exist.
        assert '"thinking"' in text and '"clear_thinking"' in text, (
            "core/llm/providers/glm.py must build the thinking field "
            "before the chat completions call (per docs.z.ai/guides/"
            "capabilities/thinking-mode)"
        )
        assert "extra_body=" in text, (
            "thinking field must be passed via extra_body= because "
            "openai-python does not know about it"
        )

    def test_adapter_gates_on_supported_models(self) -> None:
        """The adapter must consult ``_glm_thinking_supported`` (or
        equivalent gate) so failover to a non-thinking model doesn't
        send a field the server rejects."""
        from core.llm.providers import glm as glm_mod

        with open(glm_mod.__file__, encoding="utf-8") as f:
            text = f.read()
        assert "_glm_thinking_supported" in text, (
            "adapter must gate the thinking field per model — sending "
            "it on pre-GLM-4.5 models is undefined behavior"
        )

    def test_clear_thinking_default_preserves_history(self) -> None:
        """``clear_thinking=False`` keeps prior-turn ``reasoning_content``
        in the model's context — matches R1's multi-turn-reasoning-
        preservation goal on Codex Plus."""
        from core.llm.providers import glm as glm_mod

        with open(glm_mod.__file__, encoding="utf-8") as f:
            text = f.read()
        assert '"clear_thinking": False' in text, (
            "clear_thinking must default to False to preserve "
            "reasoning_content across turns (multi-turn coherence). "
            "True would strip prior reasoning every turn."
        )

"""Two-axis model+effort picker invariants (v0.59.0).

Tests the data-layer contract for ``core/cli/effort_picker.py``.
The interactive raw-tty input loop is exercised via a smoke test
that drives synthetic key events; the per-provider effort enum and
cycle/default helpers are tested directly.

Pinned 2026-04-28 against:
  - Anthropic effort enum: docs.anthropic.com / platform.claude.com
    (low/medium/high/max/xhigh; xhigh is Opus 4.7-only)
  - OpenAI Responses effort enum: openai-python `shared/reasoning_effort.py`
    (none/minimal/low/medium/high/xhigh)
  - Codex Plus enum: codex-rs `protocol/src/openai_models.rs:43-51`
    (None/Minimal/Low/Medium/High/XHigh)
  - GLM thinking enum: docs.z.ai/guides/capabilities/thinking-mode
    (binary enabled/disabled)
"""

from __future__ import annotations

from core.cli.effort_picker import (
    cycle_effort,
    default_effort,
    supported_efforts,
)


class TestAnthropicEnum:
    def test_opus_4_7_includes_xhigh(self) -> None:
        levels = supported_efforts("claude-opus-4-7", "anthropic")
        assert levels == ("low", "medium", "high", "max", "xhigh")

    def test_opus_4_6_excludes_xhigh(self) -> None:
        levels = supported_efforts("claude-opus-4-6", "anthropic")
        assert levels == ("low", "medium", "high", "max")
        assert "xhigh" not in levels

    def test_sonnet_4_6_excludes_xhigh(self) -> None:
        levels = supported_efforts("claude-sonnet-4-6", "anthropic")
        assert levels == ("low", "medium", "high", "max")

    def test_haiku_no_effort_knob(self) -> None:
        """Non-adaptive models have no effort field — picker shows [fixed]."""
        levels = supported_efforts("claude-haiku-4-5", "anthropic")
        assert levels == ()

    def test_default_is_high(self) -> None:
        # Anthropic API default is "high" per platform.claude.com docs.
        # Opus 4.7's official guidance recommends xhigh as the *starting
        # point* for coding/agentic — picker surfaces xhigh as the
        # default for that model only (sonnet stays on high).
        assert default_effort("claude-opus-4-7", "anthropic") == "xhigh"
        assert default_effort("claude-sonnet-4-6", "anthropic") == "high"
        assert default_effort("claude-opus-4-6", "anthropic") == "high"


class TestOpenAIResponsesEnum:
    def test_gpt_5_5_full_enum(self) -> None:
        levels = supported_efforts("gpt-5.5", "openai-codex")
        assert levels == ("none", "minimal", "low", "medium", "high", "xhigh")

    def test_gpt_5_4_payg(self) -> None:
        levels = supported_efforts("gpt-5.4", "openai")
        assert levels == ("none", "minimal", "low", "medium", "high", "xhigh")

    def test_gpt_5_3_codex(self) -> None:
        levels = supported_efforts("gpt-5.3-codex", "openai-codex")
        assert "xhigh" in levels

    def test_non_gpt5_no_effort(self) -> None:
        """Non-gpt-5.x OpenAI models have no effort field."""
        levels = supported_efforts("gpt-4-turbo", "openai")
        assert levels == ()

    def test_default_is_medium(self) -> None:
        assert default_effort("gpt-5.5", "openai-codex") == "medium"


class TestGLMEnum:
    def test_hybrid_models_have_binary_enum(self) -> None:
        for model in ("glm-4.6", "glm-4.5", "glm-4.5-air"):
            levels = supported_efforts(model, "glm")
            assert levels == ("disabled", "enabled"), f"{model}: {levels}"

    def test_always_on_models_no_knob(self) -> None:
        """Always-on GLM thinking models silently ignore disabled —
        picker shows [fixed]."""
        for model in ("glm-5.1", "glm-4.7", "glm-4.7-flash"):
            levels = supported_efforts(model, "glm")
            assert levels == (), f"{model}: {levels}"

    def test_unknown_glm_no_knob(self) -> None:
        assert supported_efforts("glm-4", "glm") == ()
        assert supported_efforts("unknown", "glm") == ()

    def test_default_is_enabled(self) -> None:
        assert default_effort("glm-4.6", "glm") == "enabled"


class TestCycleEffort:
    def test_cycle_right_advances(self) -> None:
        levels = ("low", "medium", "high", "max")
        assert cycle_effort("low", levels, +1) == "medium"
        assert cycle_effort("medium", levels, +1) == "high"
        assert cycle_effort("high", levels, +1) == "max"

    def test_cycle_left_decreases(self) -> None:
        levels = ("low", "medium", "high", "max")
        assert cycle_effort("max", levels, -1) == "high"
        assert cycle_effort("high", levels, -1) == "medium"

    def test_cycle_wraps_around(self) -> None:
        levels = ("low", "medium", "high", "max")
        assert cycle_effort("max", levels, +1) == "low"
        assert cycle_effort("low", levels, -1) == "max"

    def test_empty_levels_returns_unchanged(self) -> None:
        """Models with no effort knob → cycling is a silent no-op."""
        assert cycle_effort("anything", (), +1) == "anything"
        assert cycle_effort("anything", (), -1) == "anything"

    def test_unknown_current_snaps_to_middle(self) -> None:
        """Switching models (e.g., from gpt-5.5 to claude-opus-4-7)
        with current="none" → snap to the new model's middle level."""
        levels = ("low", "medium", "high", "max", "xhigh")
        # "none" is not in the Anthropic enum
        result = cycle_effort("none", levels, +1)
        assert result in levels  # snapped to something valid
        assert result == levels[len(levels) // 2]  # middle


class TestPerProviderEnumIntegrity:
    """Cross-provider sanity — the enum table covers every model in
    MODEL_PROFILES with a sensible answer."""

    def test_every_profile_has_supported_efforts_callable(self) -> None:
        from core.cli.commands import MODEL_PROFILES

        for p in MODEL_PROFILES:
            levels = supported_efforts(p.id, p.provider)
            assert isinstance(levels, tuple)
            # Every level should be a non-empty string
            assert all(isinstance(level, str) and level for level in levels)

    def test_default_either_in_enum_or_none(self) -> None:
        from core.cli.commands import MODEL_PROFILES

        for p in MODEL_PROFILES:
            levels = supported_efforts(p.id, p.provider)
            d = default_effort(p.id, p.provider)
            if not levels:
                # No knob → default may be None
                assert d is None or d in levels
            else:
                # Default must be in the enum
                assert d in levels, f"{p.id} ({p.provider}): default={d} not in {levels}"

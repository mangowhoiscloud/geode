"""Two-axis model+effort picker invariants (v0.59.0).

Tests the data-layer contract for ``core/cli/effort_picker.py``.
The interactive raw-tty input loop is exercised via a smoke test
that drives synthetic key events; the per-provider effort enum and
cycle/default helpers are tested directly.

Pinned 2026-04-28 against:
  - Anthropic effort enum: docs.anthropic.com / platform.claude.com
    (low/medium/high/max/xhigh; xhigh is Opus 4.7+ — 4.7 / 4.8)
  - OpenAI Responses effort enum: the explicit per-model registry in
    `core.llm.adapters._openai_common` (the picker and wire share one contract)
  - GLM thinking enum: docs.z.ai/guides/capabilities/thinking-mode
    (binary enabled/disabled)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.cli.effort_picker import (
    cycle_effort,
    default_effort,
    supported_efforts,
)


class TestAnthropicEnum:
    def test_opus_4_8_includes_xhigh(self) -> None:
        levels = supported_efforts("claude-opus-4-8", "anthropic")
        assert levels == ("low", "medium", "high", "max", "xhigh")

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
        # Opus 4.7+ official guidance recommends xhigh as the *starting
        # point* for coding/agentic — picker surfaces xhigh as the
        # default for the xhigh-capable Opus models (4.7 / 4.8); sonnet
        # and Opus 4.6 stay on high.
        assert default_effort("claude-opus-4-8", "anthropic") == "xhigh"
        assert default_effort("claude-opus-4-7", "anthropic") == "xhigh"
        assert default_effort("claude-sonnet-4-6", "anthropic") == "high"
        assert default_effort("claude-opus-4-6", "anthropic") == "high"


class TestOpenAIResponsesEnum:
    def test_gpt_5_5_full_enum(self) -> None:
        levels = supported_efforts("gpt-5.5", "openai-codex")
        assert levels == ("none", "low", "medium", "high", "xhigh")

    def test_gpt_5_4_payg(self) -> None:
        levels = supported_efforts("gpt-5.4", "openai")
        assert levels == ("none", "low", "medium", "high", "xhigh")

    def test_gpt_5_4_subscription_uses_the_same_model_contract(self) -> None:
        assert supported_efforts("gpt-5.4", "openai-codex") == (
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
        )

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

    def test_legacy_openai_minimal_migrates_in_arrow_direction(self) -> None:
        levels = ("none", "low", "medium", "high", "xhigh")
        assert cycle_effort("minimal", levels, -1) == "none"
        assert cycle_effort("minimal", levels, +1) == "low"


class TestPerProviderEnumIntegrity:
    """Cross-provider sanity — the enum table covers every model in
    the picker list with a sensible answer."""

    def test_every_profile_has_supported_efforts_callable(self) -> None:
        from core.cli.commands import get_model_profiles

        for p in get_model_profiles():
            levels = supported_efforts(p.id, p.provider)
            assert isinstance(levels, tuple)
            # Every level should be a non-empty string
            assert all(isinstance(level, str) and level for level in levels)

    def test_default_either_in_enum_or_none(self) -> None:
        from core.cli.commands import get_model_profiles

        for p in get_model_profiles():
            levels = supported_efforts(p.id, p.provider)
            d = default_effort(p.id, p.provider)
            if not levels:
                # No knob → default may be None
                assert d is None or d in levels
            else:
                # Default must be in the enum
                assert d in levels, f"{p.id} ({p.provider}): default={d} not in {levels}"


def test_picker_preserves_legacy_openai_minimal_on_noop_enter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening and confirming a persisted legacy value must not rewrite it."""
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("gpt-5.4", "openai", "GPT-5.4", "$$", True, None),
    ]
    monkeypatch.setattr(effort_picker, "_read_key", lambda: effort_picker._KEY_ENTER)
    monkeypatch.setattr(effort_picker, "_render", lambda *args, **kwargs: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda lines: None)

    result = effort_picker.pick_model_and_effort(
        profiles,
        current_model="gpt-5.4",
        current_effort="minimal",
    )

    assert result.cancelled is False
    assert result.model_id == "gpt-5.4"
    assert result.effort == "minimal"


@pytest.mark.parametrize(
    ("arrow", "expected"),
    [
        ("_KEY_LEFT", "none"),
        ("_KEY_RIGHT", "low"),
    ],
)
def test_picker_migrates_legacy_openai_minimal_in_arrow_direction(
    monkeypatch: pytest.MonkeyPatch,
    arrow: str,
    expected: str,
) -> None:
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("gpt-5.4", "openai", "GPT-5.4", "$$", True, None),
    ]
    keys = iter([getattr(effort_picker, arrow), effort_picker._KEY_ENTER])
    monkeypatch.setattr(effort_picker, "_read_key", lambda: next(keys))
    monkeypatch.setattr(effort_picker, "_render", lambda *args, **kwargs: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda lines: None)

    result = effort_picker.pick_model_and_effort(
        profiles,
        current_model="gpt-5.4",
        current_effort="minimal",
    )

    assert result.effort == expected


def test_active_off_catalog_openai_model_enter_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted role model must not fall through to the first picker row."""
    import core.config
    from core.cli import effort_picker
    from core.cli.commands._state import get_model_profiles

    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-5.6-sol"):
        rows = get_model_profiles(configured_model_ids=("gpt-5.2",))
    profiles = [(row.id, row.provider, row.label, row.cost, True, None) for row in rows]

    monkeypatch.setattr(effort_picker, "_read_key", lambda: effort_picker._KEY_ENTER)
    monkeypatch.setattr(effort_picker, "_render", lambda *args, **kwargs: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda lines: None)

    result = effort_picker.pick_model_and_effort(
        profiles,
        current_model="gpt-5.2",
        current_effort="high",
    )

    assert result.cancelled is False
    assert result.model_id == "gpt-5.2"
    assert result.effort == "high"


def test_configured_rows_are_deduplicated_across_default_and_roles() -> None:
    import core.config
    from core.cli.commands._state import get_model_profiles

    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-5.2"):
        rows = get_model_profiles(configured_model_ids=("gpt-5.2", "gpt-5.1", "gpt-5.1", ""))

    ids = [row.id for row in rows]
    assert ids.count("gpt-5.2") == 1
    assert ids.count("gpt-5.1") == 1
    assert next(row for row in rows if row.id == "gpt-5.1").provider == "openai"


class TestRenderVersionHeader:
    """The picker title carries the running version so a stale binary
    (for example a lagging Homebrew formula) is visible immediately."""

    def test_header_names_running_version(self, capsys) -> None:
        from core import __version__
        from core.cli.effort_picker import _render

        _render(
            [("gpt-5.6-sol", "openai", "GPT-5.6 Sol", "$$", True, None)],
            cursor=0,
            effort_per_model={"gpt-5.6-sol": "medium"},
            initial_model="gpt-5.6-sol",
        )
        out = capsys.readouterr().out
        assert f"GEODE v{__version__}" in out
        assert "Select model" in out

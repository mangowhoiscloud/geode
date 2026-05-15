"""Tests for the Tier 3 (graphics inline) scaffold in
``core.ui.latex_graphics``.

PR scope is *capability detection + public-API pin* only — the actual
PNG generation lands in the follow-up. These tests therefore focus on:

  * The detect probe correctly classifies Kitty / WezTerm / Ghostty /
    Konsole / SIXEL / unknown / non-TTY environments.
  * `GEODE_LATEX_GRAPHICS_FORCE` and `..._DISABLE` env overrides win
    over the auto-detect.
  * The opt-in helper reads `GEODE_LATEX_GRAPHICS` cleanly.
  * `render_latex_image` raises a *clearly-described* `NotImplementedError`
    so a caller that bypasses the opt-in fails loud, not silent.
"""

from __future__ import annotations

import io

import pytest
from core.ui.latex_graphics import (
    detect_graphics_capability,
    graphics_opt_in_active,
    render_latex_image,
)


@pytest.fixture()
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Wipe every env var the detector consults so tests start blank."""
    for var in (
        "TERM",
        "KITTY_WINDOW_ID",
        "WEZTERM_PANE",
        "WEZTERM_EXECUTABLE",
        "GHOSTTY_RESOURCES_DIR",
        "KONSOLE_VERSION",
        "GEODE_LATEX_GRAPHICS_DISABLE",
        "GEODE_LATEX_GRAPHICS_FORCE",
        "GEODE_LATEX_GRAPHICS",
    ):
        monkeypatch.delenv(var, raising=False)
    # Default to a TTY so the isatty() guard does not short-circuit
    # the unrelated detection paths.
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    return monkeypatch


class TestDetectGraphicsCapability:
    def test_unknown_terminal_returns_none(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        assert detect_graphics_capability() is None

    def test_kitty_term_value(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-kitty")
        assert detect_graphics_capability() == "kitty"

    def test_kitty_window_id_env(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("KITTY_WINDOW_ID", "42")
        assert detect_graphics_capability() == "kitty"

    def test_wezterm_term_variant(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "wezterm-256color")
        assert detect_graphics_capability() == "kitty"

    def test_wezterm_env_vars(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("WEZTERM_EXECUTABLE", "/Applications/WezTerm.app/wezterm")
        assert detect_graphics_capability() == "kitty"
        isolated_env.delenv("WEZTERM_EXECUTABLE")
        isolated_env.setenv("WEZTERM_PANE", "1")
        assert detect_graphics_capability() == "kitty"

    def test_ghostty_term_variant(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-ghostty")
        assert detect_graphics_capability() == "kitty"

    def test_ghostty_resources_dir(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("GHOSTTY_RESOURCES_DIR", "/Applications/Ghostty.app/Contents/Resources")
        assert detect_graphics_capability() == "kitty"

    def test_konsole_version_env(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("KONSOLE_VERSION", "230400")
        assert detect_graphics_capability() == "kitty"

    def test_sixel_terminals(self, isolated_env: pytest.MonkeyPatch) -> None:
        for value in ("mlterm", "foot"):
            isolated_env.setenv("TERM", value)
            assert detect_graphics_capability() == "sixel", value

    def test_force_disable_overrides_capability(self, isolated_env: pytest.MonkeyPatch) -> None:
        isolated_env.setenv("TERM", "xterm-kitty")
        isolated_env.setenv("GEODE_LATEX_GRAPHICS_DISABLE", "1")
        assert detect_graphics_capability() is None

    def test_force_protocol_overrides_unknown_terminal(
        self, isolated_env: pytest.MonkeyPatch
    ) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("GEODE_LATEX_GRAPHICS_FORCE", "kitty")
        assert detect_graphics_capability() == "kitty"
        isolated_env.setenv("GEODE_LATEX_GRAPHICS_FORCE", "sixel")
        assert detect_graphics_capability() == "sixel"

    def test_force_protocol_invalid_value_falls_through(
        self, isolated_env: pytest.MonkeyPatch
    ) -> None:
        isolated_env.setenv("TERM", "xterm-256color")
        isolated_env.setenv("GEODE_LATEX_GRAPHICS_FORCE", "carrot")
        assert detect_graphics_capability() is None

    def test_non_tty_returns_none_even_for_kitty(self, isolated_env: pytest.MonkeyPatch) -> None:
        """Never emit graphics into a redirected pipe — that produces
        garbled bytes when the operator pipes ``geode "..." | tee log``."""
        isolated_env.setenv("TERM", "xterm-kitty")
        # Use a real-looking non-TTY object — Rich-style StringIO.
        isolated_env.setattr("sys.stdout", io.StringIO(), raising=False)
        assert detect_graphics_capability() is None


class TestGraphicsOptIn:
    def test_default_opt_in_off(self, isolated_env: pytest.MonkeyPatch) -> None:
        assert graphics_opt_in_active() is False

    def test_opt_in_truthy_values(self, isolated_env: pytest.MonkeyPatch) -> None:
        for value in ("1", "true", "yes", "TRUE", "Yes"):
            isolated_env.setenv("GEODE_LATEX_GRAPHICS", value)
            assert graphics_opt_in_active() is True, value

    def test_opt_in_falsy_values(self, isolated_env: pytest.MonkeyPatch) -> None:
        for value in ("0", "false", "no", "off", ""):
            isolated_env.setenv("GEODE_LATEX_GRAPHICS", value)
            assert graphics_opt_in_active() is False, value


class TestRenderLatexImage:
    def test_scaffold_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="follow-up PR"):
            render_latex_image(r"\frac{a}{b}", protocol="kitty")

    def test_scaffold_message_mentions_opt_in(self) -> None:
        """The error must point the caller at the opt-in path so a future
        regression of the wiring (e.g. someone wires it up without
        respecting the opt-in) is loud."""
        try:
            render_latex_image(r"x", protocol="sixel")
        except NotImplementedError as exc:
            msg = str(exc)
            assert "opt-in" in msg.lower() or "capability" in msg.lower()
        else:
            raise AssertionError("expected NotImplementedError")

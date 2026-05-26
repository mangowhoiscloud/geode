"""M2 — /model picker exposes ``settings.forced_login_method`` per provider.

Pre-fix ``settings.forced_login_method = {"openai": "apikey"}`` silently
re-sorted the plan chain in ``_apply_forced_login_method`` so a user
selecting ``gpt-5.5`` expecting Codex quietly ended up on PAYG.
The picker now surfaces the override with a ``(forced: <method>)``
suffix in both the interactive and non-tty list views, mirroring the
M5 ``(login required)`` badge.

Contracts pinned here:

1. ``commands._state.forced_login_method_for(provider)`` is ``None``
   when the setting is at its default (``"subscription"``,
   ``"auto"``, unset) — so the badge only renders when the user has
   *explicitly* chosen a non-default routing.
2. Any of ``apikey`` / ``api`` / ``api_key`` / ``key`` normalises to
   ``"apikey"`` — same alias map as
   ``plan_registry._apply_forced_login_method``.
3. The picker tuple carries the forced-method label as the 6th
   element. ``_render`` appends ``(forced: <method>)`` after the
   ``(login required)`` suffix when present.
4. The non-tty ``/model`` list also surfaces the badge.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Contract 1 — defaults collapse to None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "subscription", "auto", "  Subscription  ", "AUTO"],
)
def test_forced_login_method_for_default_returns_none(value: str) -> None:
    from core.cli.commands import _state

    fake_settings = type("S", (), {"forced_login_method": {"openai": value}})()
    with patch("core.config.settings", fake_settings):
        assert _state.forced_login_method_for("openai") is None, (
            f"default value {value!r} must collapse to None — the picker "
            "should only badge an explicit override"
        )


def test_forced_login_method_for_missing_provider_returns_none() -> None:
    from core.cli.commands import _state

    fake_settings = type("S", (), {"forced_login_method": {}})()
    with patch("core.config.settings", fake_settings):
        assert _state.forced_login_method_for("openai") is None


def test_forced_login_method_for_exception_returns_none() -> None:
    """Defensive: a broken settings object must not lock the picker."""
    from core.cli.commands import _state

    class _Boom:
        @property
        def forced_login_method(self) -> dict[str, str]:
            raise RuntimeError("settings broken")

    with patch("core.config.settings", _Boom()):
        assert _state.forced_login_method_for("openai") is None


# ---------------------------------------------------------------------------
# Contract 2 — apikey alias normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias",
    ["apikey", "api", "api_key", "key", "APIKEY", "  Key  "],
)
def test_forced_login_method_for_apikey_aliases(alias: str) -> None:
    from core.cli.commands import _state

    fake_settings = type("S", (), {"forced_login_method": {"openai": alias}})()
    with patch("core.config.settings", fake_settings):
        assert _state.forced_login_method_for("openai") == "apikey", (
            f"alias {alias!r} must normalise to 'apikey' — must stay in sync with "
            "plan_registry._apply_forced_login_method"
        )


def test_forced_login_method_for_unknown_value_passes_through() -> None:
    """Future-proof — an unrecognised value still surfaces so the user
    sees that *something* was set even if the alias map hasn't caught up."""
    from core.cli.commands import _state

    fake_settings = type("S", (), {"forced_login_method": {"openai": "future-mode"}})()
    with patch("core.config.settings", fake_settings):
        assert _state.forced_login_method_for("openai") == "future-mode"


# ---------------------------------------------------------------------------
# Contract 3 — picker render carries (forced: …) badge
# ---------------------------------------------------------------------------


def test_picker_render_includes_forced_badge(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("claude-opus-4-7", "anthropic", "Opus 4.7", "$$$", True, None),
        ("gpt-5.5", "openai-codex", "GPT-5.5", "$$", True, "apikey"),
    ]
    effort_picker._render(profiles, cursor=0, effort_per_model={}, initial_model="claude-opus-4-7")
    out = capsys.readouterr().out
    assert "(forced: apikey)" in out, f"forced-method badge missing from picker render: {out!r}"


def test_picker_render_skips_badge_when_default(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("claude-opus-4-7", "anthropic", "Opus 4.7", "$$$", True, None),
    ]
    effort_picker._render(profiles, cursor=0, effort_per_model={}, initial_model="claude-opus-4-7")
    out = capsys.readouterr().out
    assert "(forced:" not in out, (
        "default value must NOT render a badge — otherwise every row "
        "carries noise the user has to filter out"
    )


# ---------------------------------------------------------------------------
# Contract 4 — non-tty list surfaces the badge
# ---------------------------------------------------------------------------


def test_cmd_model_nontty_lists_forced_badge(capsys: pytest.CaptureFixture[str]) -> None:
    """/model (no args, no TTY) is the curl-driven view — must show
    the same forced-method status as the interactive picker."""
    from core.cli.commands import model as _model_mod

    def fake_forced(provider: str) -> str | None:
        return "apikey" if provider == "openai-codex" else None

    with (
        patch("core.cli.commands.model.model_available", return_value=True),
        patch("core.cli.commands.model.forced_login_method_for", side_effect=fake_forced),
        patch("sys.stdin.isatty", return_value=False),
    ):
        _model_mod.cmd_model("")

    out = capsys.readouterr().out
    assert "(forced: apikey)" in out, (
        "non-tty /model must surface forced-method override so a curl-driven "
        f"caller sees what an interactive user would: {out!r}"
    )

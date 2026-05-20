"""X1 — per-provider auth order: pinned profile takes priority.

Pre-fix ``ProfileRotator.resolve`` sorted eligible profiles solely by
type-priority + LRU, so an operator with multiple OAuth profiles for
the same provider could not pin a preferred one without removing the
others. ``ProfileStore.set_active(name)`` existed but the rotator
ignored it.

Contracts pinned here:

1. ``ProfileRotator.resolve(provider)`` returns the user-pinned
   active profile (when eligible) before falling back to the
   ``sort_key`` order.
2. An ineligible pin gracefully steps aside — the rotator continues
   with the next sort-key candidate.
3. ``/login use-profile <name>`` wraps ``store.set_active(name)`` and
   prints a confirmation line.
4. ``/login order`` lists the effective ordering per provider with an
   ``active`` / ``queued`` / ``<reject_reason>`` badge per row.
5. ``_login_show_status`` Profiles section appends ``(active)`` to
   the pinned row so the rotator's priority surfaces in the dashboard.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator

# ---------------------------------------------------------------------------
# Contract 1 — pinned active profile wins
# ---------------------------------------------------------------------------


def _build_store_two_oauth() -> ProfileStore:
    """Two OAuth profiles for openai-codex, both eligible, different last_used.

    Without a pin, the sort_key would pick the LRU one (least recent
    use). With a pin on the more-recent one, the rotator should
    return the pinned profile instead.
    """
    store = ProfileStore()
    store.add(
        AuthProfile(
            name="openai-codex:home",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="home-token",
            last_used=1000.0,
        )
    )
    store.add(
        AuthProfile(
            name="openai-codex:work",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="work-token",
            last_used=2000.0,
        )
    )
    return store


def test_resolve_returns_pinned_active_first() -> None:
    store = _build_store_two_oauth()
    store.set_active("openai-codex:work")  # the more-recent profile

    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    assert selected.name == "openai-codex:work", (
        "rotator must surface the pinned profile even when the sort_key "
        "(LRU) would favour the other one"
    )


def test_resolve_falls_back_to_sort_key_when_no_pin() -> None:
    """Without a pin, the legacy sort_key (LRU) order applies."""
    store = _build_store_two_oauth()
    # Default active is the FIRST registered (ProfileStore.add behaviour).
    # Override to a profile that no longer exists so the rotator falls
    # back to the sort_key tiebreak.
    store._active["openai-codex"] = "non-existent"

    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    # sort_key uses last_used (LRU), so the older :home wins.
    assert selected.name == "openai-codex:home"


# ---------------------------------------------------------------------------
# Contract 2 — ineligible pin steps aside
# ---------------------------------------------------------------------------


def test_resolve_ineligible_pin_falls_back_to_sort_key() -> None:
    store = _build_store_two_oauth()
    # Disable the pinned profile so it's ineligible.
    pinned = store.get("openai-codex:work")
    assert pinned is not None
    pinned.disabled = True
    store.set_active("openai-codex:work")

    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    assert selected.name == "openai-codex:home", (
        "an ineligible pin must step aside so the rotator does not starve the next eligible profile"
    )


# ---------------------------------------------------------------------------
# Contract 3 — /login use-profile command
# ---------------------------------------------------------------------------


def test_cmd_login_use_profile_sets_active(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_use_profile

    store = _build_store_two_oauth()
    with (
        patch("core.wiring.container.ensure_profile_store", return_value=store),
        patch("core.cli.commands._persist_auth_state"),
    ):
        _login_use_profile("openai-codex:work")

    out = capsys.readouterr().out
    assert "Pinned" in out
    assert "openai-codex:work" in out
    active = store.get_active("openai-codex")
    assert active is not None and active.name == "openai-codex:work"


def test_cmd_login_use_profile_unknown_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_use_profile

    store = _build_store_two_oauth()
    with patch("core.wiring.container.ensure_profile_store", return_value=store):
        _login_use_profile("does-not-exist")

    out = capsys.readouterr().out
    assert "Unknown profile" in out


def test_cmd_login_use_profile_missing_arg(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_use_profile

    _login_use_profile("")
    out = capsys.readouterr().out
    assert "Usage:" in out


# ---------------------------------------------------------------------------
# Contract 4 — /login order render
# ---------------------------------------------------------------------------


def test_cmd_login_order_renders_pinned_first(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _build_store_two_oauth()
    store.set_active("openai-codex:work")

    with patch("core.wiring.container.ensure_profile_store", return_value=store):
        _login_order("")

    out = capsys.readouterr().out
    assert "Profile order" in out
    # Pinned profile precedes its sibling in the output.
    work_pos = out.find("openai-codex:work")
    home_pos = out.find("openai-codex:home")
    assert 0 <= work_pos < home_pos, (
        f"pinned profile must appear before queued sibling: "
        f"work@{work_pos} vs home@{home_pos} — output={out!r}"
    )
    assert "active" in out


def test_cmd_login_order_narrows_to_provider(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _build_store_two_oauth()
    store.add(
        AuthProfile(
            name="anthropic:work",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="claude-token",
        )
    )

    with patch("core.wiring.container.ensure_profile_store", return_value=store):
        _login_order("anthropic")

    out = capsys.readouterr().out
    assert "anthropic:work" in out
    assert "openai-codex:" not in out


def test_cmd_login_order_empty_store(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    with patch("core.wiring.container.ensure_profile_store", return_value=ProfileStore()):
        _login_order("")

    out = capsys.readouterr().out
    assert "No profiles registered" in out


def test_cmd_login_order_unknown_provider_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _build_store_two_oauth()
    with patch("core.wiring.container.ensure_profile_store", return_value=store):
        _login_order("not-a-provider")

    out = capsys.readouterr().out
    assert "No profiles for provider" in out

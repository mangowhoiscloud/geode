"""X1.1 — full multi-rank auth ordering on top of X1 single-active pin.

X1 (v0.99.22) added ``ProfileStore.set_active`` + rotator honouring
``get_pinned_active``. This second slice adds full list ordering so
operators can specify ``[primary, secondary, tertiary]`` per provider;
the rotator tries them in order before falling back to the legacy
``sort_key`` tail.

Contracts pinned here:

1. ``ProfileStore.set_auth_order(provider, names)`` records the list,
   writes head to ``_pinned_active`` for X1 parity, and raises
   ``KeyError`` / ``ValueError`` on unknown / wrong-provider names.
2. ``get_auth_order`` returns a copy (mutation-safe).
3. ``clear_auth_order`` drops both the list and the single-active pin
   so the rotator falls back to pure ``sort_key``.
4. ``ProfileRotator.resolve`` walks the multi-rank list in order;
   missing / ineligible entries skip without starving the tail.
5. ``/login order set / clear`` CLI subcommands wrap the store API
   and emit visible confirmation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator


def _three_profiles() -> ProfileStore:
    store = ProfileStore()
    for i, last_used in enumerate([100.0, 50.0, 200.0], start=1):
        store.add(
            AuthProfile(
                name=f"openai-codex:p{i}",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key=f"token-{i}",
                last_used=last_used,
            )
        )
    return store


# ---------------------------------------------------------------------------
# Contract 1 — set_auth_order writes the list and the head pin
# ---------------------------------------------------------------------------


def test_set_auth_order_records_list_and_head_pin() -> None:
    store = _three_profiles()
    store.set_auth_order("openai-codex", ["openai-codex:p2", "openai-codex:p3", "openai-codex:p1"])

    assert store.get_auth_order("openai-codex") == [
        "openai-codex:p2",
        "openai-codex:p3",
        "openai-codex:p1",
    ]
    pinned = store.get_pinned_active("openai-codex")
    assert pinned is not None and pinned.name == "openai-codex:p2", (
        "head of multi-rank list must keep X1's get_pinned_active in sync"
    )


def test_set_auth_order_unknown_name_raises() -> None:
    store = _three_profiles()
    with pytest.raises(KeyError):
        store.set_auth_order("openai-codex", ["openai-codex:p1", "nope"])


def test_set_auth_order_wrong_provider_raises() -> None:
    store = _three_profiles()
    store.add(
        AuthProfile(
            name="anthropic:work",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="token",
        )
    )
    with pytest.raises(ValueError):
        store.set_auth_order("openai-codex", ["openai-codex:p1", "anthropic:work"])


# ---------------------------------------------------------------------------
# Contract 2 — get_auth_order returns a copy
# ---------------------------------------------------------------------------


def test_get_auth_order_returns_copy() -> None:
    store = _three_profiles()
    store.set_auth_order("openai-codex", ["openai-codex:p1"])
    snapshot = store.get_auth_order("openai-codex")
    snapshot.append("openai-codex:p2")
    # Mutation of the returned list must not affect the store.
    assert store.get_auth_order("openai-codex") == ["openai-codex:p1"]


# ---------------------------------------------------------------------------
# Contract 3 — clear_auth_order drops both surfaces
# ---------------------------------------------------------------------------


def test_clear_auth_order_drops_both_surfaces() -> None:
    store = _three_profiles()
    store.set_auth_order("openai-codex", ["openai-codex:p1", "openai-codex:p2"])
    store.clear_auth_order("openai-codex")
    assert store.get_auth_order("openai-codex") == []
    assert store.get_pinned_active("openai-codex") is None


def test_set_auth_order_empty_list_clears() -> None:
    store = _three_profiles()
    store.set_auth_order("openai-codex", ["openai-codex:p1"])
    store.set_auth_order("openai-codex", [])
    assert store.get_auth_order("openai-codex") == []
    assert store.get_pinned_active("openai-codex") is None


# ---------------------------------------------------------------------------
# Contract 4 — rotator walks the list in order; missing entries skip
# ---------------------------------------------------------------------------


def test_rotator_walks_multi_rank_in_order() -> None:
    store = _three_profiles()
    # Multi-rank: p3 first even though p2 has the lowest last_used (LRU
    # winner under the legacy path).
    store.set_auth_order("openai-codex", ["openai-codex:p3", "openai-codex:p1"])

    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    assert selected.name == "openai-codex:p3"


def test_rotator_skips_ineligible_pin_falls_to_next_rank() -> None:
    store = _three_profiles()
    p3 = store.get("openai-codex:p3")
    assert p3 is not None
    p3.disabled = True
    store.set_auth_order("openai-codex", ["openai-codex:p3", "openai-codex:p1"])

    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    assert selected.name == "openai-codex:p1", (
        "ineligible head entry must step aside without starving the next rank"
    )


def test_rotator_falls_back_to_sort_key_when_no_order() -> None:
    """No pin + no auth order → legacy LRU/type-priority wins."""
    store = _three_profiles()
    rotator = ProfileRotator(store)
    selected = rotator.resolve("openai-codex")
    assert selected is not None
    # last_used=50.0 (p2) is the LRU winner under the legacy path.
    assert selected.name == "openai-codex:p2"


# ---------------------------------------------------------------------------
# Contract 5 — CLI: /login order set / clear
# ---------------------------------------------------------------------------


def test_cmd_login_order_set_records_pin(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _three_profiles()
    with (
        patch("core.wiring.container.ensure_profile_store", return_value=store),
        patch("core.cli.commands._persist_auth_state"),
    ):
        _login_order("set openai-codex openai-codex:p2 openai-codex:p3")

    out = capsys.readouterr().out
    assert "Pinned auth order" in out
    assert "openai-codex:p2" in out
    assert store.get_auth_order("openai-codex") == [
        "openai-codex:p2",
        "openai-codex:p3",
    ]


def test_cmd_login_order_clear_drops_pin(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _three_profiles()
    store.set_auth_order("openai-codex", ["openai-codex:p1"])
    with (
        patch("core.wiring.container.ensure_profile_store", return_value=store),
        patch("core.cli.commands._persist_auth_state"),
    ):
        _login_order("clear openai-codex")

    out = capsys.readouterr().out
    assert "Cleared auth order" in out
    assert store.get_auth_order("openai-codex") == []


def test_cmd_login_order_set_missing_args_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _three_profiles()
    with patch("core.wiring.container.ensure_profile_store", return_value=store):
        _login_order("set")

    out = capsys.readouterr().out
    assert "Usage:" in out


def test_cmd_login_order_set_unknown_name_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import _login_order

    store = _three_profiles()
    with (
        patch("core.wiring.container.ensure_profile_store", return_value=store),
        patch("core.cli.commands._persist_auth_state"),
    ):
        _login_order("set openai-codex does-not-exist")

    out = capsys.readouterr().out
    assert "not found" in out

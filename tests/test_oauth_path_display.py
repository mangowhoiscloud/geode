"""Bug class B1 — OAuth success message must display the actual SOT path.

The v0.52.1 incident: ``/login oauth openai`` succeeded and printed
``Stored: /Users/mango/.geode/auth.json``, but the actual write landed
in ``~/.geode/auth.toml`` (v0.50.2 SOT). The display constant lagged
behind the SOT migration.

Invariant:
  1. ``auth_store_path()`` resolves to the live ``auth_toml_path()`` and
     respects the ``GEODE_AUTH_TOML`` env override.
  2. ``oauth_login.py`` does NOT pass the legacy constant to
     ``emit_oauth_login_success(stored_at=...)``. It must call
     ``auth_store_path()`` (or equivalent live resolver) instead.
"""

from __future__ import annotations

import inspect

import core.auth.oauth_login as _oauth
import pytest


def test_auth_store_path_resolves_to_auth_toml(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Honor GEODE_AUTH_TOML env override — same behaviour as auth_toml_path."""
    target = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(target))

    resolved = _oauth.auth_store_path()
    assert str(resolved) == str(target), (
        "auth_store_path must resolve via auth_toml_path() so the OAuth "
        "success message points at the actual SOT, not the legacy auth.json."
    )


def test_auth_store_path_does_not_return_legacy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(target))

    resolved = _oauth.auth_store_path()
    assert "auth.json" not in str(resolved), (
        "auth_store_path must never resolve to auth.json (legacy SOT)"
    )


def test_oauth_success_uses_auth_store_path() -> None:
    """Source-level: the OAuth success emit_* call must use auth_store_path()
    (or equivalent live resolver) so the displayed path matches what was
    actually written. Pre-v0.52.2 it used ``str(AUTH_STORE_PATH)`` which was
    a static alias for the legacy auth.json constant.
    """
    src = inspect.getsource(_oauth)
    # Locate the emit_oauth_login_success call and check its stored_at arg.
    success_call = src.find("emit_oauth_login_success(")
    assert success_call >= 0
    # Window around the call.
    block = src[success_call : success_call + 500]
    assert "auth_store_path()" in block or "auth_toml_path()" in block, (
        "emit_oauth_login_success(stored_at=...) must use the live SOT "
        "resolver. Pre-fix it stringified AUTH_STORE_PATH (legacy constant)."
    )
    # Anti-regression: the literal legacy alias must NOT appear in the call.
    legacy_pattern = "stored_at=str(AUTH_STORE_PATH)"
    assert legacy_pattern not in block, (
        "Legacy ``stored_at=str(AUTH_STORE_PATH)`` regression detected — "
        "this displayed auth.json while writing to auth.toml (B1)."
    )

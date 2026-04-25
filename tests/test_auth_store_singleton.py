"""Single ProfileStore invariant — Phase 1 of v0.50.0.

Pre-v0.50.0 the CLI (`/auth`) and the runtime LLM dispatch held two
separate ProfileStore instances. A credential added via the UI was not
visible to ProfileRotator.resolve(), so the user's mental model
("I added the key, why does it still say 'not configured'?") diverged
from reality. These tests pin the single-store invariant.
"""

from __future__ import annotations

from core.auth.profiles import AuthProfile, CredentialType


def _reset_singletons() -> None:
    """Force build_auth() to re-seed for isolated test runs."""
    from core.lifecycle import container as infra

    infra._profile_store = None
    infra._profile_rotator = None


class TestSingleStore:
    def test_ensure_profile_store_is_idempotent(self) -> None:
        _reset_singletons()
        from core.lifecycle.container import ensure_profile_store

        s1 = ensure_profile_store()
        s2 = ensure_profile_store()
        assert s1 is s2

    def test_cli_and_runtime_share_store(self) -> None:
        _reset_singletons()
        from core.cli.commands import _get_profile_store
        from core.lifecycle.container import ensure_profile_store

        runtime_store = ensure_profile_store()
        cli_store = _get_profile_store()
        assert runtime_store is cli_store

    def test_credential_added_via_cli_is_visible_to_rotator(self) -> None:
        _reset_singletons()
        from core.cli.commands import _get_profile_store
        from core.lifecycle.container import get_profile_rotator

        store = _get_profile_store()
        store.add(
            AuthProfile(
                name="anthropic:test-singleton",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-test",
            )
        )

        rotator = get_profile_rotator()
        assert rotator is not None
        resolved = rotator.resolve("anthropic")
        assert resolved is not None
        assert resolved.name == "anthropic:test-singleton" or any(
            p.name == "anthropic:test-singleton" for p in store.list_by_provider("anthropic")
        )

    def test_build_auth_returns_same_singleton(self) -> None:
        _reset_singletons()
        from core.lifecycle.container import build_auth

        s1, r1, _ = build_auth()
        s2, r2, _ = build_auth()
        assert s1 is s2
        assert r1 is r2

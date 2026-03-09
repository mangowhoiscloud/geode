"""Tests for Auth Profile System (P1-1, P1-2, P1-3)."""

from __future__ import annotations

import time

from geode.auth.cooldown import CooldownTracker
from geode.auth.profiles import (
    TYPE_PRIORITY,
    AuthProfile,
    CredentialType,
    ProfileStore,
)
from geode.auth.rotation import ProfileRotator, calculate_cooldown_ms

# ---------------------------------------------------------------------------
# CredentialType + Priority
# ---------------------------------------------------------------------------


class TestCredentialType:
    def test_enum_values(self):
        assert CredentialType.OAUTH.value == "oauth"
        assert CredentialType.TOKEN.value == "token"
        assert CredentialType.API_KEY.value == "api_key"

    def test_type_priority_order(self):
        assert TYPE_PRIORITY[CredentialType.OAUTH] < TYPE_PRIORITY[CredentialType.TOKEN]
        assert TYPE_PRIORITY[CredentialType.TOKEN] < TYPE_PRIORITY[CredentialType.API_KEY]


# ---------------------------------------------------------------------------
# AuthProfile
# ---------------------------------------------------------------------------


class TestAuthProfile:
    def test_basic_creation(self):
        p = AuthProfile(
            name="anthropic:work",
            provider="anthropic",
            credential_type=CredentialType.API_KEY,
            key="sk-ant-test-key-123456789012",
        )
        assert p.name == "anthropic:work"
        assert p.provider == "anthropic"
        assert p.is_available

    def test_masked_key_long(self):
        p = AuthProfile(
            name="test:key",
            provider="test",
            credential_type=CredentialType.API_KEY,
            key="sk-ant-api03-abcdef1234567890xyz",
        )
        masked = p.masked_key
        assert masked.startswith("sk-ant-api")
        assert "..." in masked

    def test_masked_key_short(self):
        p = AuthProfile(
            name="test:key",
            provider="test",
            credential_type=CredentialType.API_KEY,
            key="short",
        )
        assert p.masked_key == "***"

    def test_is_expired(self):
        p = AuthProfile(
            name="test:exp",
            provider="test",
            credential_type=CredentialType.TOKEN,
            expires_at=time.time() - 100,
        )
        assert p.is_expired

    def test_not_expired(self):
        p = AuthProfile(
            name="test:ok",
            provider="test",
            credential_type=CredentialType.TOKEN,
            expires_at=time.time() + 3600,
        )
        assert not p.is_expired

    def test_no_expiry(self):
        p = AuthProfile(
            name="test:noexp",
            provider="test",
            credential_type=CredentialType.API_KEY,
        )
        assert not p.is_expired

    def test_is_cooling_down(self):
        p = AuthProfile(
            name="test:cool",
            provider="test",
            credential_type=CredentialType.API_KEY,
            cooldown_until=time.time() + 60,
        )
        assert p.is_cooling_down
        assert not p.is_available

    def test_disabled(self):
        p = AuthProfile(
            name="test:dis",
            provider="test",
            credential_type=CredentialType.API_KEY,
            disabled=True,
            disabled_reason="quota_exceeded",
        )
        assert not p.is_available

    def test_sort_key_type_priority(self):
        oauth = AuthProfile(name="a:oauth", provider="a", credential_type=CredentialType.OAUTH)
        api_key = AuthProfile(name="a:key", provider="a", credential_type=CredentialType.API_KEY)
        assert oauth.sort_key() < api_key.sort_key()

    def test_sort_key_lru(self):
        old = AuthProfile(
            name="a:old",
            provider="a",
            credential_type=CredentialType.API_KEY,
            last_used=100.0,
        )
        new = AuthProfile(
            name="a:new",
            provider="a",
            credential_type=CredentialType.API_KEY,
            last_used=200.0,
        )
        assert old.sort_key() < new.sort_key()


# ---------------------------------------------------------------------------
# ProfileStore
# ---------------------------------------------------------------------------


class TestProfileStore:
    def _make_profile(self, name="test:default", provider="anthropic"):
        return AuthProfile(
            name=name,
            provider=provider,
            credential_type=CredentialType.API_KEY,
            key="sk-ant-test-123456789012345",
        )

    def test_add_and_get(self):
        store = ProfileStore()
        p = self._make_profile()
        store.add(p)
        assert store.get("test:default") is p
        assert len(store) == 1

    def test_remove(self):
        store = ProfileStore()
        store.add(self._make_profile())
        assert store.remove("test:default")
        assert len(store) == 0
        assert not store.remove("nonexistent")

    def test_list_by_provider(self):
        store = ProfileStore()
        store.add(self._make_profile("a:1", "anthropic"))
        store.add(self._make_profile("o:1", "openai"))
        store.add(self._make_profile("a:2", "anthropic"))

        anthro = store.list_by_provider("anthropic")
        assert len(anthro) == 2

    def test_list_available(self):
        store = ProfileStore()
        store.add(self._make_profile("a:1", "anthropic"))
        disabled = self._make_profile("a:2", "anthropic")
        disabled.disabled = True
        store.add(disabled)

        available = store.list_available("anthropic")
        assert len(available) == 1
        assert available[0].name == "a:1"

    def test_group_by_provider(self):
        store = ProfileStore()
        store.add(self._make_profile("a:1", "anthropic"))
        store.add(self._make_profile("o:1", "openai"))

        groups = store.group_by_provider()
        assert "anthropic" in groups
        assert "openai" in groups

    def test_contains(self):
        store = ProfileStore()
        store.add(self._make_profile())
        assert "test:default" in store
        assert "nonexistent" not in store

    def test_clear(self):
        store = ProfileStore()
        store.add(self._make_profile("a:1"))
        store.add(self._make_profile("a:2"))
        store.clear()
        assert len(store) == 0


# ---------------------------------------------------------------------------
# ProfileRotator
# ---------------------------------------------------------------------------


class TestProfileRotator:
    def _make_store_with_profiles(self):
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="a:key1",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-key1-123456789012345",
                last_used=100.0,
            )
        )
        store.add(
            AuthProfile(
                name="a:key2",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-key2-123456789012345",
                last_used=50.0,  # Older = preferred (LRU)
            )
        )
        store.add(
            AuthProfile(
                name="a:oauth",
                provider="anthropic",
                credential_type=CredentialType.OAUTH,
                key="oauth-token-xxx",
                last_used=200.0,
            )
        )
        return store

    def test_resolve_type_priority(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        selected = rotator.resolve("anthropic")
        assert selected is not None
        assert selected.credential_type == CredentialType.OAUTH

    def test_resolve_lru_within_type(self):
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="a:key1",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-key1-123456789012345",
                last_used=200.0,
            )
        )
        store.add(
            AuthProfile(
                name="a:key2",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-key2-123456789012345",
                last_used=100.0,
            )
        )
        rotator = ProfileRotator(store)
        selected = rotator.resolve("anthropic")
        assert selected is not None
        assert selected.name == "a:key2"  # Older last_used

    def test_resolve_no_profiles(self):
        store = ProfileStore()
        rotator = ProfileRotator(store)
        assert rotator.resolve("anthropic") is None

    def test_resolve_skips_disabled(self):
        store = ProfileStore()
        disabled = AuthProfile(
            name="a:disabled",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="token",
            disabled=True,
        )
        available = AuthProfile(
            name="a:available",
            provider="anthropic",
            credential_type=CredentialType.API_KEY,
            key="sk-ant-available-123456789",
        )
        store.add(disabled)
        store.add(available)
        rotator = ProfileRotator(store)
        selected = rotator.resolve("anthropic")
        assert selected is not None
        assert selected.name == "a:available"

    def test_mark_used(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        profile = store.get("a:key1")
        old_used = profile.last_used
        rotator.mark_used(profile)
        assert profile.last_used > old_used

    def test_mark_success(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        profile = store.get("a:key1")
        profile.error_count = 3
        rotator.mark_success(profile)
        assert profile.error_count == 0

    def test_mark_failure_applies_cooldown(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        profile = store.get("a:key1")
        rotator.mark_failure(profile)
        assert profile.error_count == 1
        assert profile.is_cooling_down

    def test_disable_enable(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        profile = store.get("a:key1")
        rotator.disable(profile, "quota_exceeded")
        assert not profile.is_available
        rotator.enable(profile)
        assert profile.is_available

    def test_get_status(self):
        store = self._make_store_with_profiles()
        rotator = ProfileRotator(store)
        statuses = rotator.get_status()
        assert len(statuses) == 3
        assert all("name" in s for s in statuses)


# ---------------------------------------------------------------------------
# Cooldown Calculator
# ---------------------------------------------------------------------------


class TestCooldownCalculation:
    def test_first_error(self):
        assert calculate_cooldown_ms(1) == 60_000  # 1 minute

    def test_second_error(self):
        assert calculate_cooldown_ms(2) == 300_000  # 5 minutes

    def test_third_error(self):
        assert calculate_cooldown_ms(3) == 1_500_000  # 25 minutes

    def test_fourth_error_capped(self):
        result = calculate_cooldown_ms(4)
        assert result == 3_600_000  # 60 min cap

    def test_large_count_capped(self):
        assert calculate_cooldown_ms(100) == 3_600_000

    def test_zero_error(self):
        assert calculate_cooldown_ms(0) == 60_000  # Normalized to 1


# ---------------------------------------------------------------------------
# CooldownTracker
# ---------------------------------------------------------------------------


class TestCooldownTracker:
    def test_record_failure(self):
        tracker = CooldownTracker()
        ms = tracker.record_failure("key1", "rate_limit")
        assert ms == 60_000
        assert not tracker.is_available("key1")

    def test_record_success_resets(self):
        tracker = CooldownTracker()
        tracker.record_failure("key1")
        tracker.record_success("key1")
        entry = tracker.get_entry("key1")
        assert entry.error_count == 0

    def test_unknown_key_is_available(self):
        tracker = CooldownTracker()
        assert tracker.is_available("nonexistent")

    def test_clear_specific(self):
        tracker = CooldownTracker()
        tracker.record_failure("key1")
        tracker.record_failure("key2")
        tracker.clear("key1")
        assert tracker.get_entry("key1") is None
        assert tracker.get_entry("key2") is not None

    def test_clear_all(self):
        tracker = CooldownTracker()
        tracker.record_failure("key1")
        tracker.record_failure("key2")
        tracker.clear()
        assert tracker.get_entry("key1") is None
        assert tracker.get_entry("key2") is None

    def test_remaining_ms(self):
        tracker = CooldownTracker()
        tracker.record_failure("key1")
        assert tracker.get_remaining_ms("key1") > 0
        assert tracker.get_remaining_ms("nonexistent") == 0

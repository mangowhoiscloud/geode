"""Tests for Auth Profile System (P1-1, P1-2, P1-3)."""

from __future__ import annotations

import time

from core.auth.cooldown import CooldownTracker
from core.auth.profiles import (
    TYPE_PRIORITY,
    AuthProfile,
    CredentialType,
    ProfileStore,
)
from core.auth.rotation import ProfileRotator, calculate_cooldown_ms

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


# ---------------------------------------------------------------------------
# Proactive Refresh + 401 Auto-Refresh
# ---------------------------------------------------------------------------


class TestProactiveRefresh:
    """Managed token refresh on resolve() when expiry is near."""

    def test_proactive_refresh_called_when_expiring(self):
        """resolve() calls refresher if managed profile expires within 120s."""
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="openai:codex",
                provider="openai",
                credential_type=CredentialType.OAUTH,
                key="old-token",
                expires_at=time.time() + 30,  # 30s left (< 120s skew)
                managed_by="codex-cli",
            )
        )
        rotator = ProfileRotator(store)
        refresh_calls: list[str] = []

        def mock_refresh(profile: AuthProfile) -> bool:
            refresh_calls.append(profile.name)
            profile.key = "new-token"
            return True

        rotator.register_refresher("codex-cli", mock_refresh)
        result = rotator.resolve("openai")

        assert result is not None
        assert result.key == "new-token"
        assert refresh_calls == ["openai:codex"]

    def test_no_refresh_when_not_expiring(self):
        """resolve() skips refresh if token has plenty of time left."""
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="openai:codex",
                provider="openai",
                credential_type=CredentialType.OAUTH,
                key="valid-token",
                expires_at=time.time() + 3600,  # 1h left
                managed_by="codex-cli",
            )
        )
        rotator = ProfileRotator(store)
        refresh_calls: list[str] = []

        rotator.register_refresher("codex-cli", lambda p: refresh_calls.append(p.name) or False)
        result = rotator.resolve("openai")

        assert result is not None
        assert result.key == "valid-token"
        assert refresh_calls == []

    def test_no_refresh_for_unmanaged_profile(self):
        """resolve() skips refresh for non-managed profiles."""
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="openai:default",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="sk-test",
            )
        )
        rotator = ProfileRotator(store)
        rotator.register_refresher("codex-cli", lambda p: True)
        result = rotator.resolve("openai")
        assert result is not None
        assert result.key == "sk-test"

    def test_refresh_failure_does_not_crash(self):
        """Refresher exception is caught, profile still returned."""
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="openai:codex",
                provider="openai",
                credential_type=CredentialType.OAUTH,
                key="old-token",
                expires_at=time.time() + 30,
                managed_by="codex-cli",
            )
        )
        rotator = ProfileRotator(store)

        def failing_refresh(_profile: AuthProfile) -> bool:
            raise OSError("disk error")

        rotator.register_refresher("codex-cli", failing_refresh)
        result = rotator.resolve("openai")
        assert result is not None
        assert result.key == "old-token"  # unchanged


class TestAutoRefreshOn401:
    """401 auto-refresh: re-read managed token on auth failure."""

    def test_401_triggers_managed_refresh(self):
        """mark_failure(is_auth_error=True) refreshes managed token."""
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:codex",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="expired-token",
            managed_by="codex-cli",
        )
        store.add(profile)
        rotator = ProfileRotator(store)

        def mock_refresh(p: AuthProfile) -> bool:
            p.key = "fresh-token"
            return True

        rotator.register_refresher("codex-cli", mock_refresh)
        rotator.mark_failure(profile, is_auth_error=True)

        assert profile.key == "fresh-token"
        assert profile.error_count == 0  # reset after refresh
        assert profile.cooldown_until == 0.0

    def test_401_no_refresh_applies_cooldown(self):
        """mark_failure(is_auth_error=True) with failed refresh applies cooldown."""
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:codex",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="expired-token",
            managed_by="codex-cli",
        )
        store.add(profile)
        rotator = ProfileRotator(store)
        rotator.register_refresher("codex-cli", lambda _p: False)  # not updated
        rotator.mark_failure(profile, is_auth_error=True)

        assert profile.error_count == 1
        assert profile.cooldown_until > time.time()

    def test_non_auth_error_skips_refresh(self):
        """mark_failure(is_auth_error=False) does not attempt refresh."""
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:codex",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="token",
            managed_by="codex-cli",
        )
        store.add(profile)
        rotator = ProfileRotator(store)
        refresh_calls: list[str] = []
        rotator.register_refresher("codex-cli", lambda p: refresh_calls.append(p.name) or False)
        rotator.mark_failure(profile, is_auth_error=False)

        assert refresh_calls == []  # no refresh attempted
        assert profile.error_count == 1

    def test_unmanaged_profile_401_applies_cooldown(self):
        """Unmanaged profile on 401 just applies cooldown."""
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:default",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            key="sk-test",
        )
        store.add(profile)
        rotator = ProfileRotator(store)
        rotator.mark_failure(profile, is_auth_error=True)

        assert profile.error_count == 1
        assert profile.cooldown_until > time.time()


# ---------------------------------------------------------------------------
# Credential Scrubbing
# ---------------------------------------------------------------------------


class TestCredentialScrubbing:
    """Tests for core.auth.scrub module."""

    def test_scrub_openai_key(self):
        from core.auth.scrub import scrub_credentials

        msg = "Authentication failed: sk-proj-abcdef1234567890XYZ"
        result = scrub_credentials(msg)
        assert "sk-proj" not in result
        assert "[REDACTED]" in result

    def test_scrub_github_pat(self):
        from core.auth.scrub import scrub_credentials

        msg = "Rate limit exceeded for ghp_1234567890abcdefABCDEF"
        result = scrub_credentials(msg)
        assert "ghp_" not in result

    def test_scrub_bearer_token(self):
        from core.auth.scrub import scrub_credentials

        msg = "Invalid header: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.abc123"
        result = scrub_credentials(msg)
        assert "eyJhbGci" not in result

    def test_scrub_slack_token(self):
        from core.auth.scrub import scrub_credentials

        msg = "Slack error: xoxb-1234-5678-abcdefghij/klmnop"
        result = scrub_credentials(msg)
        assert "xoxb-" not in result

    def test_scrub_query_params(self):
        from core.auth.scrub import scrub_credentials

        msg = "Request to https://api.example.com?api_key=abcdef1234567890&foo=bar"
        result = scrub_credentials(msg)
        assert "abcdef1234" not in result
        assert "foo=bar" in result

    def test_no_scrub_clean_text(self):
        from core.auth.scrub import scrub_credentials

        msg = "Connection timed out after 30 seconds"
        assert scrub_credentials(msg) == msg

    def test_scrub_multiple_patterns(self):
        from core.auth.scrub import scrub_credentials

        msg = "Failed with sk-test-abc1234567890xyz and Bearer tok_longvalue1234"
        result = scrub_credentials(msg)
        assert "sk-test" not in result
        assert "tok_longvalue" not in result


# ---------------------------------------------------------------------------
# ZAI Profile in build_auth
# ---------------------------------------------------------------------------


class TestBuildAuthZAI:
    """Verify build_auth registers ZAI profile when api key is set."""

    def test_zai_profile_registered(self):
        from unittest.mock import patch

        with patch("core.lifecycle.container.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.zai_api_key = "test-zai-key"

            from core.lifecycle.container import build_auth

            store, _rotator, _cooldown = build_auth()

        profile = store.get("glm:default")
        assert profile is not None
        assert profile.provider == "glm"
        assert profile.key == "test-zai-key"
        assert profile.credential_type == CredentialType.API_KEY

    def test_zai_profile_not_registered_when_empty(self):
        from unittest.mock import patch

        with patch("core.lifecycle.container.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.zai_api_key = ""

            from core.lifecycle.container import build_auth

            store, _rotator, _cooldown = build_auth()

        assert store.get("glm:default") is None

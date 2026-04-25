"""Tests for ProfileRotator wiring — mark_success/mark_failure integration.

Verifies that the LLM call chain notifies ProfileRotator on
success/failure via notify_llm_success/notify_llm_failure
(OpenClaw markAuthProfileGood/markAuthProfileFailure pattern).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator
from core.llm.credentials import (
    _last_profile,
    get_last_profile,
    notify_llm_failure,
    notify_llm_success,
    resolve_provider_key,
)


class TestProfileTracking:
    """get_last_profile() tracks the profile resolved by resolve_provider_key()."""

    def setup_method(self):
        _last_profile.clear()

    def test_resolve_stores_last_profile(self):
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:codex",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="test-token",
        )
        store.add(profile)
        rotator = ProfileRotator(store)

        with patch("core.lifecycle.container.get_profile_rotator", return_value=rotator):
            key = resolve_provider_key("openai", "fallback-key")

        assert key == "test-token"
        assert get_last_profile("openai") is profile

    def test_resolve_fallback_no_profile(self):
        with patch("core.lifecycle.container.get_profile_rotator", return_value=None):
            key = resolve_provider_key("openai", "fallback-key")

        assert key == "fallback-key"
        assert get_last_profile("openai") is None

    def test_get_last_profile_returns_none_for_unknown(self):
        assert get_last_profile("nonexistent") is None


class TestNotifySuccess:
    """notify_llm_success() calls rotator.mark_success()."""

    def setup_method(self):
        _last_profile.clear()

    def test_success_resets_error_count(self):
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:codex",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="token",
            error_count=3,
            cooldown_until=time.time() + 3600,
        )
        store.add(profile)
        rotator = ProfileRotator(store)
        _last_profile["openai"] = profile

        with patch("core.lifecycle.container.get_profile_rotator", return_value=rotator):
            notify_llm_success("openai")

        assert profile.error_count == 0
        assert profile.cooldown_until == 0.0

    def test_success_noop_without_profile(self):
        """No crash when no profile was resolved."""
        with patch("core.lifecycle.container.get_profile_rotator", return_value=MagicMock()):
            notify_llm_success("openai")  # should not raise

    def test_success_noop_without_rotator(self):
        """No crash when rotator is not available."""
        _last_profile["openai"] = MagicMock()
        with patch("core.lifecycle.container.get_profile_rotator", return_value=None):
            notify_llm_success("openai")  # should not raise


class TestNotifyFailure:
    """notify_llm_failure() calls rotator.mark_failure() with auth classification."""

    def setup_method(self):
        _last_profile.clear()

    def test_auth_error_triggers_auth_failure(self):
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
        _last_profile["openai"] = profile

        mock_refresher = MagicMock(return_value=True)
        rotator.register_refresher("codex-cli", mock_refresher)

        # Simulate auth error (401)
        exc = Exception("401 Unauthorized")
        with (
            patch("core.lifecycle.container.get_profile_rotator", return_value=rotator),
            patch("core.llm.fallback._is_auth_error", return_value=True),
        ):
            notify_llm_failure("openai", exc)

        # 401 auto-refresh should have been triggered
        mock_refresher.assert_called_once_with(profile)

    def test_non_auth_error_applies_cooldown(self):
        store = ProfileStore()
        profile = AuthProfile(
            name="openai:default",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            key="sk-test",
        )
        store.add(profile)
        rotator = ProfileRotator(store)
        _last_profile["openai"] = profile

        exc = Exception("Connection timeout")
        with (
            patch("core.lifecycle.container.get_profile_rotator", return_value=rotator),
            patch("core.llm.fallback._is_auth_error", return_value=False),
        ):
            notify_llm_failure("openai", exc)

        assert profile.error_count == 1
        assert profile.cooldown_until > time.time()

    def test_failure_noop_without_profile(self):
        """No crash when no profile was resolved."""
        exc = Exception("error")
        with patch("core.lifecycle.container.get_profile_rotator", return_value=MagicMock()):
            notify_llm_failure("openai", exc)  # should not raise


class TestFallbackIntegration:
    """Verify _notify_success/_notify_failure are called from retry_with_backoff_generic."""

    def test_success_path_calls_notify(self):
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        cb = CircuitBreaker()
        calls: list[str] = []

        with patch(
            "core.llm.fallback._notify_success", side_effect=lambda p: calls.append(f"ok:{p}")
        ):
            result = retry_with_backoff_generic(
                lambda model: "response",
                model="test-model",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                provider_label="openai",
            )

        assert result == "response"
        assert calls == ["ok:openai"]

    def test_failure_path_calls_notify(self):
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        cb = CircuitBreaker()
        calls: list[str] = []

        def failing_fn(model: str) -> None:
            raise ConnectionError("timeout")

        with patch(
            "core.llm.fallback._notify_failure",
            side_effect=lambda p, e: calls.append(f"fail:{p}"),
        ):
            import contextlib

            with contextlib.suppress(ConnectionError):
                retry_with_backoff_generic(
                    failing_fn,
                    model="test-model",
                    fallback_models=[],
                    circuit_breaker=cb,
                    retryable_errors=(ConnectionError,),
                    provider_label="LLM",
                    max_retries=1,
                    retry_base_delay=0.0,
                    retry_max_delay=0.0,
                )

        assert calls == ["fail:anthropic"]  # "LLM" maps to "anthropic"


class TestProviderLabelMapping:
    """_resolve_rotator_provider maps labels correctly."""

    def test_llm_maps_to_anthropic(self):
        from core.llm.fallback import _resolve_rotator_provider

        assert _resolve_rotator_provider("LLM") == "anthropic"

    def test_openai_maps_to_openai(self):
        from core.llm.fallback import _resolve_rotator_provider

        assert _resolve_rotator_provider("OpenAI") == "openai"

    def test_glm_maps_to_glm(self):
        from core.llm.fallback import _resolve_rotator_provider

        assert _resolve_rotator_provider("GLM") == "glm"

    def test_unknown_passthrough(self):
        from core.llm.fallback import _resolve_rotator_provider

        assert _resolve_rotator_provider("custom") == "custom"


class TestAuditLoggerCompleteness:
    """All 8 previously missing audit loggers are now registered."""

    def test_all_asymmetry_loggers_registered(self):
        from unittest.mock import patch as _patch

        with (
            _patch("core.lifecycle.bootstrap.RunLog"),
            _patch("core.lifecycle.bootstrap.StuckDetector"),
        ):
            from core.lifecycle.bootstrap import build_hooks

            hooks, _, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
                stuck_timeout_s=60,
            )

        all_hooks = hooks.list_hooks()

        # Previously missing — now should exist
        assert "llm_failed" in all_hooks.get("llm_call_failed", [])
        assert "llm_retry" in all_hooks.get("llm_call_retry", [])
        assert "recovery_ok" in all_hooks.get("tool_recovery_succeeded", [])
        assert "mcp_ok" in all_hooks.get("mcp_server_connected", [])
        assert "tool_offload" in all_hooks.get("tool_result_offloaded", [])
        assert "approval_req" in all_hooks.get("tool_approval_requested", [])
        assert "memory_saved" in all_hooks.get("memory_saved", [])
        assert "reasoning_metrics" in all_hooks.get("reasoning_metrics", [])

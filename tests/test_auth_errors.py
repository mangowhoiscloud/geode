"""Phase 5 — AuthError + ERROR_HINTS user-facing message tests."""

from __future__ import annotations

from core.auth.errors import (
    AuthError,
    AuthErrorCode,
    format_auth_error,
)
from core.auth.plans import GLM_CODING_TIERS, default_plan_for_payg


class TestErrorHints:
    def test_plan_not_registered_directs_to_login_add(self) -> None:
        err = AuthError(AuthErrorCode.PLAN_NOT_REGISTERED, provider="openai")
        msg = format_auth_error(err)
        assert "/login add" in msg
        assert "openai" in msg

    def test_quota_exhausted_includes_upgrade_url_when_present(self) -> None:
        plan = GLM_CODING_TIERS["lite"]
        err = AuthError(AuthErrorCode.QUOTA_EXHAUSTED, plan=plan)
        msg = format_auth_error(err)
        assert plan.upgrade_url in msg
        assert "/login use" in msg

    def test_key_invalid_suggests_set_key(self) -> None:
        plan = default_plan_for_payg("openai", "sk-stale")
        err = AuthError(AuthErrorCode.KEY_INVALID, plan=plan, provider="openai")
        msg = format_auth_error(err)
        assert f"/login set-key {plan.id}" in msg

    def test_oauth_refresh_directs_to_oauth_command(self) -> None:
        err = AuthError(AuthErrorCode.OAUTH_REFRESH_FAILED, provider="openai-codex")
        msg = format_auth_error(err)
        assert "/login oauth openai" in msg

    def test_subscription_expired_falls_back_when_no_upgrade_url(self) -> None:
        plan = default_plan_for_payg("openai", "")
        err = AuthError(AuthErrorCode.SUBSCRIPTION_EXPIRED, plan=plan)
        msg = format_auth_error(err)
        assert "/login set-key" in msg

    def test_endpoint_mismatch_references_login_add(self) -> None:
        plan = GLM_CODING_TIERS["lite"]
        err = AuthError(AuthErrorCode.ENDPOINT_MISMATCH, plan=plan)
        msg = format_auth_error(err)
        assert "/login add" in msg

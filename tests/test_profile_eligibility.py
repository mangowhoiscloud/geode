"""Phase v0.51.0 — ProfileStore.evaluate_eligibility + breadcrumb tests."""

from __future__ import annotations

import time
from unittest.mock import patch

from core.auth.credential_breadcrumb import format as fmt_breadcrumb
from core.auth.profiles import (
    AuthProfile,
    CredentialType,
    EligibilityResult,
    ProfileRejectReason,
    ProfileStore,
)


def _store_with(*profiles: AuthProfile) -> ProfileStore:
    s = ProfileStore()
    for p in profiles:
        s.add(p)
    return s


class TestEvaluateEligibility:
    def test_provider_mismatch(self) -> None:
        s = _store_with(
            AuthProfile(
                name="anthropic:work",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-x",
            )
        )
        verdicts = s.evaluate_eligibility("openai")
        assert len(verdicts) == 1
        v = verdicts[0]
        assert not v.eligible
        assert v.reason is ProfileRejectReason.PROVIDER_MISMATCH
        assert "anthropic" in v.detail and "openai" in v.detail

    def test_disabled_profile(self) -> None:
        s = _store_with(
            AuthProfile(
                name="openai:work",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="sk-x",
                disabled=True,
                disabled_reason="revoked by user",
            )
        )
        v = s.evaluate_eligibility("openai")[0]
        assert not v.eligible
        assert v.reason is ProfileRejectReason.DISABLED
        assert "revoked by user" in v.detail

    def test_missing_key(self) -> None:
        s = _store_with(
            AuthProfile(
                name="openai:work",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="",
            )
        )
        v = s.evaluate_eligibility("openai")[0]
        assert not v.eligible
        assert v.reason is ProfileRejectReason.MISSING_KEY

    def test_expired_token(self) -> None:
        s = _store_with(
            AuthProfile(
                name="openai-codex:cli",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key="tok",
                expires_at=time.time() - 60,
            )
        )
        v = s.evaluate_eligibility("openai-codex")[0]
        assert not v.eligible
        assert v.reason is ProfileRejectReason.EXPIRED
        assert "expired" in v.detail and "ago" in v.detail

    def test_cooling_down(self) -> None:
        s = _store_with(
            AuthProfile(
                name="openai:work",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="sk-x",
                cooldown_until=time.time() + 30,
                error_count=4,
            )
        )
        v = s.evaluate_eligibility("openai")[0]
        assert not v.eligible
        assert v.reason is ProfileRejectReason.COOLING_DOWN
        assert "remaining" in v.detail
        assert "error_count=4" in v.detail

    def test_eligible_profile_has_no_reason(self) -> None:
        s = _store_with(
            AuthProfile(
                name="openai:work",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="sk-x",
            )
        )
        v = s.evaluate_eligibility("openai")[0]
        assert v.eligible
        assert v.reason is None
        assert v.reason_code == "ok"

    def test_every_profile_gets_a_verdict(self) -> None:
        """No silent skips — verdicts list length always equals store size."""
        s = _store_with(
            AuthProfile("a:1", "a", CredentialType.API_KEY, key="k"),
            AuthProfile("b:1", "b", CredentialType.API_KEY, key="k"),
            AuthProfile("a:2", "a", CredentialType.API_KEY, key="k", disabled=True),
        )
        verdicts = s.evaluate_eligibility("a")
        assert len(verdicts) == 3  # all three, not just "a"-provider profiles
        names = {v.profile_name for v in verdicts}
        assert names == {"a:1", "b:1", "a:2"}


class TestRotatorLoggingAndCache:
    def test_resolve_caches_verdicts_for_breadcrumb(self) -> None:
        from core.auth.rotation import (
            ProfileRotator,
            get_last_eligibility_verdicts,
        )

        s = _store_with(
            AuthProfile(
                name="openai:work",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key="sk-x",
                cooldown_until=time.time() + 60,
                error_count=2,
            )
        )
        rotator = ProfileRotator(s)
        assert rotator.resolve("openai") is None

        cached = get_last_eligibility_verdicts("openai")
        assert len(cached) == 1
        assert cached[0].reason is ProfileRejectReason.COOLING_DOWN

    def test_resolve_logs_rejection_breakdown(self, caplog) -> None:
        from core.auth.rotation import ProfileRotator

        s = _store_with(
            AuthProfile(
                name="openai:expired",
                provider="openai",
                credential_type=CredentialType.OAUTH,
                key="tok",
                expires_at=time.time() - 30,
            )
        )
        rotator = ProfileRotator(s)
        with caplog.at_level("WARNING", logger="core.auth.rotation"):
            assert rotator.resolve("openai") is None
        joined = "\n".join(rec.message for rec in caplog.records)
        assert "openai:expired=expired" in joined


class TestBreadcrumbFormatter:
    def test_silent_when_eligible_present_and_no_relevant_rejections(self) -> None:
        s = _store_with(AuthProfile("openai:work", "openai", CredentialType.API_KEY, key="sk-x"))
        verdicts = s.evaluate_eligibility("openai")
        note = fmt_breadcrumb(verdicts, attempted_provider="openai")
        assert note == ""

    def test_includes_reason_and_action_for_cooldown(self) -> None:
        s = _store_with(
            AuthProfile(
                "openai:work",
                "openai",
                CredentialType.API_KEY,
                key="sk-x",
                cooldown_until=time.time() + 90,
                error_count=3,
            )
        )
        verdicts = s.evaluate_eligibility("openai")
        note = fmt_breadcrumb(verdicts, attempted_provider="openai", attempted_model="gpt-5.4")
        assert "[system] credential note" in note
        assert "openai:work" in note
        assert "cooling_down" in note
        assert "manage_login" in note
        assert "gpt-5.4" in note

    def test_empty_verdicts_emits_no_profiles_message(self) -> None:
        note = fmt_breadcrumb([], attempted_provider="openai")
        assert "no profiles registered" in note
        assert "manage_login" in note

    def test_excludes_provider_mismatch_noise(self) -> None:
        # Only an anthropic profile present, but we asked for openai.
        # The provider_mismatch verdict should NOT appear in the note.
        s = _store_with(
            AuthProfile("anthropic:work", "anthropic", CredentialType.API_KEY, key="sk-x")
        )
        verdicts = s.evaluate_eligibility("openai")
        note = fmt_breadcrumb(verdicts, attempted_provider="openai")
        assert "provider_mismatch" not in note
        # But it should still tell the LLM there are no eligible profiles
        assert "(none)" in note


class TestAgenticLoopBreadcrumbInjection:
    def test_inject_credential_breadcrumb_appends_user_message(self) -> None:
        # Light smoke — exercises the wiring without spinning up a real loop.
        from core.agent.agentic_loop import AgenticLoop

        loop = AgenticLoop.__new__(AgenticLoop)
        loop._provider = "openai"  # type: ignore[attr-defined]
        loop.model = "gpt-5.4"  # type: ignore[attr-defined]

        class _FakeContext:
            def __init__(self) -> None:
                self.messages: list[dict[str, str]] = [{"role": "user", "content": "hi"}]
                self.is_empty = False

            def add_user_message(self, content: str) -> None:
                self.messages.append({"role": "user", "content": content})

        loop.context = _FakeContext()  # type: ignore[attr-defined]

        # Simulate a cached cooldown verdict for openai
        with patch(
            "core.auth.rotation._LAST_VERDICTS",
            {
                "openai": [
                    EligibilityResult(
                        profile_name="openai:work",
                        provider="openai",
                        credential_type=CredentialType.API_KEY,
                        eligible=False,
                        reason=ProfileRejectReason.COOLING_DOWN,
                        detail="60s remaining (error_count=3)",
                        cooldown_until=time.time() + 60,
                        error_count=3,
                    )
                ]
            },
        ):
            loop._inject_credential_breadcrumb()

        injected = [m for m in loop.context.messages if "credential note" in m["content"]]
        assert injected, "breadcrumb was not appended to context"
        assert "cooling_down" in injected[0]["content"]

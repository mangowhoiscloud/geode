"""Bug class B5 — credential breadcrumb cross-provider escalation.

The v0.52.1 incident: GLM was exhausted (1113 Insufficient balance) but
the LLM only saw rejection details for GLM profiles. The user had
already registered Codex Plus OAuth and an Anthropic API key, but the
breadcrumb did not mention them, so the model could not suggest
``/model gpt-5.4-mini`` as recovery.

Invariant: when ``credential_breadcrumb.format()`` reports the active
provider has no eligible profile, it must scan other providers in
``ProfileStore`` for healthy profiles and surface them with a
``cross-provider:`` line.

Pattern source: OpenClaw Lane fail-over (Session Lane → Global Lane).
"""

from __future__ import annotations

from core.auth.credential_breadcrumb import format
from core.auth.profiles import (
    AuthProfile,
    CredentialType,
    EligibilityResult,
    ProfileRejectReason,
)


def _verdict(name: str, reason: ProfileRejectReason | None = None) -> EligibilityResult:
    return EligibilityResult(
        profile_name=name,
        provider="glm",
        credential_type=CredentialType.API_KEY,
        eligible=reason is None,
        reason=reason,
        detail="" if reason is None else f"reason={reason.value}",
    )


def test_no_alt_when_active_provider_has_eligible() -> None:
    """If active provider has eligible profiles, breadcrumb is empty —
    no cross-provider line either (nothing to escalate to)."""
    out = format([_verdict("glm:default")], attempted_provider="glm")
    assert out == ""


def test_alt_provider_listed_when_active_exhausted(monkeypatch) -> None:
    """All GLM profiles cooled-down; a healthy openai-codex profile exists.
    Breadcrumb must surface ``cross-provider:`` line with the codex profile.
    """
    from core.auth.profiles import ProfileStore
    from core.lifecycle import container as _infra

    store = ProfileStore()
    store.add(
        AuthProfile(
            name="openai-codex:codex-cli",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="oauth-token",
            managed_by="codex-cli",
        )
    )
    monkeypatch.setattr(_infra, "_profile_store", store)

    out = format(
        [_verdict("glm:default", ProfileRejectReason.COOLING_DOWN)],
        attempted_provider="glm",
        attempted_model="glm-5.1",
    )
    assert "cross-provider:" in out, (
        "When active provider is exhausted and another provider has an "
        "eligible profile, breadcrumb must surface it. Pre-fix the LLM "
        "saw only GLM rejections and could not suggest /model fallback."
    )
    assert "openai-codex" in out
    assert "codex-cli" in out


def test_no_cross_provider_line_when_no_alternatives(monkeypatch) -> None:
    """If no other provider has eligible profiles, no cross-provider line
    (avoid telling LLM to try things that won't work)."""
    from core.auth.profiles import ProfileStore
    from core.lifecycle import container as _infra

    store = ProfileStore()  # empty store
    monkeypatch.setattr(_infra, "_profile_store", store)

    out = format(
        [_verdict("glm:default", ProfileRejectReason.COOLING_DOWN)],
        attempted_provider="glm",
    )
    assert "cross-provider:" not in out, (
        "No alternative providers ⇒ no cross-provider hint (don't fabricate)"
    )


def test_alt_provider_skips_attempted_provider(monkeypatch) -> None:
    """The exhausted provider must not appear in its own alternatives list."""
    from core.auth.profiles import ProfileStore
    from core.lifecycle import container as _infra

    store = ProfileStore()
    store.add(
        AuthProfile(
            name="glm:default",
            provider="glm",
            credential_type=CredentialType.API_KEY,
            key="sk-glm-fake",
        )
    )
    monkeypatch.setattr(_infra, "_profile_store", store)

    out = format(
        [_verdict("glm:default", ProfileRejectReason.COOLING_DOWN)],
        attempted_provider="glm",
    )
    # Even if the GLM profile in the store is "eligible", we exclude the
    # exhausted provider from the suggestion list.
    assert "cross-provider:" not in out

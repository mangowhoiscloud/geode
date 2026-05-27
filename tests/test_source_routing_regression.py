"""Regression pin for PR-SOURCE-ROUTING (2026-05-28).

Three layers under test, all stem from one production incident: an operator
on ChatGPT Pro Lite subscription completed ``/login openai`` (registering
the ``openai-codex-geode:user`` OAuth profile in :class:`ProfileStore`) but
the very next ``gpt-5.5`` turn surfaced
``insufficient_quota — Switch to a different model``. Root cause was
**three independent regressions stacked**:

1. ``AgenticLoop.__init__`` defaulted ``source`` to literal ``"payg"`` so
   the daemon path (``core/server/supervised/services.py:211`` →
   ``AgenticLoop(...)`` with no ``source=`` kwarg) collapsed every
   ``provider="openai-codex"`` call to ``resolve_for("openai", "payg")``
   → ``openai-payg`` adapter → ``api.openai.com``.
2. ``core/agent/loop/_reflection.py:292`` and
   ``core/self_improving_loop/runner.py:830`` hard-coded ``"payg"`` so
   subscription-only Pattern B reflected / mutated through the depleted
   PAYG endpoint while the main loop sat on the subscription endpoint.
3. ``core/llm/errors.py:_classify_openai_error`` treated
   ``openai.RateLimitError`` as ``rate_limit`` unconditionally — but the
   SDK raises the same class for both transient 429 throttling AND
   ``insufficient_quota`` (PAYG balance depletion). The operator saw
   "Switch to a different model with ``/model``" — the wrong action
   (switching model still hits the same depleted bucket).

The fix introduces :func:`core.llm.adapters._source_inference.infer_source`
which consults the ``{provider}_credential_source`` setting + ProfileStore
so OAuth-registered providers promote to ``"subscription"`` by default;
threads it through the AgenticLoop default + the two hard-coded sub-loops;
and gates the ``RateLimitError`` branch on :func:`is_billing_fatal` so
``insufficient_quota`` surfaces as ``billing`` (the right action — change
credential source, not model).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.llm.adapters._source_inference import infer_source
from core.llm.adapters.base import SOURCE_PAYG, SOURCE_SUBSCRIPTION

# ---------------------------------------------------------------------------
# Layer 1 — infer_source resolution priority
# ---------------------------------------------------------------------------


def _stub_store(profiles: list[AuthProfile]) -> ProfileStore:
    store = ProfileStore()
    for p in profiles:
        store.add(p)
    return store


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """Stamp credential_source fields on the singleton settings."""
    from core.config import settings

    for field, value in overrides.items():
        monkeypatch.setattr(settings, field, value, raising=False)


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: ProfileStore | None) -> None:
    """Replace the wiring container's profile store accessor for the test."""

    def _fake() -> ProfileStore:
        if store is None:
            raise RuntimeError("no store")
        return store

    monkeypatch.setattr(
        "core.llm.adapters._source_inference.ensure_profile_store",
        _fake,
        raising=False,
    )
    # The helper imports inside the function, so also patch the source:
    import core.wiring.container as _container

    monkeypatch.setattr(_container, "ensure_profile_store", _fake)


def test_infer_source_explicit_oauth_setting_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/login source openai oauth`` → setting=oauth → subscription, no probe."""
    _patch_settings(monkeypatch, openai_credential_source="oauth")
    # Store is empty — explicit setting still promotes.
    _patch_store(monkeypatch, _stub_store([]))
    assert infer_source("openai") == SOURCE_SUBSCRIPTION
    assert infer_source("openai-codex") == SOURCE_SUBSCRIPTION


def test_infer_source_explicit_api_key_setting_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/login source openai api_key`` → setting=api_key → payg even with OAuth profile."""
    _patch_settings(monkeypatch, openai_credential_source="api_key")
    _patch_store(
        monkeypatch,
        _stub_store(
            [
                AuthProfile(
                    name="openai-codex-geode:user",
                    provider="openai-codex",
                    credential_type=CredentialType.OAUTH,
                    key="dummy",
                    plan_id="openai-codex-geode",
                )
            ]
        ),
    )
    assert infer_source("openai") == SOURCE_PAYG


def test_infer_source_auto_with_oauth_profile_promotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto + OAuth profile present → subscription (the regression that broke /login openai)."""
    _patch_settings(monkeypatch, openai_credential_source="auto")
    _patch_store(
        monkeypatch,
        _stub_store(
            [
                AuthProfile(
                    name="openai-codex-geode:user",
                    provider="openai-codex",
                    credential_type=CredentialType.OAUTH,
                    key="dummy",
                    plan_id="openai-codex-geode",
                )
            ]
        ),
    )
    assert infer_source("openai") == SOURCE_SUBSCRIPTION
    assert infer_source("openai-codex") == SOURCE_SUBSCRIPTION


def test_infer_source_auto_with_only_payg_profile_stays_payg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto + only PAYG profile (no OAuth) → payg (preserved historical default)."""
    _patch_settings(monkeypatch, openai_credential_source="auto")
    _patch_store(
        monkeypatch,
        _stub_store(
            [
                AuthProfile(
                    name="openai-payg:env",
                    provider="openai",
                    credential_type=CredentialType.API_KEY,
                    key="sk-dummy",
                    plan_id="openai-payg",
                )
            ]
        ),
    )
    assert infer_source("openai") == SOURCE_PAYG


def test_infer_source_unknown_provider_falls_back_to_payg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers GEODE doesn't gate (e.g. glm) keep the historical payg default."""
    _patch_settings(monkeypatch, openai_credential_source="oauth")
    _patch_store(monkeypatch, None)
    assert infer_source("glm") == SOURCE_PAYG
    assert infer_source("unknown") == SOURCE_PAYG


def test_infer_source_anthropic_setting_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """anthropic_credential_source is read for anthropic, NOT openai_credential_source."""
    _patch_settings(
        monkeypatch,
        openai_credential_source="oauth",
        anthropic_credential_source="api_key",
    )
    _patch_store(monkeypatch, _stub_store([]))
    assert infer_source("openai") == SOURCE_SUBSCRIPTION
    assert infer_source("anthropic") == SOURCE_PAYG


# ---------------------------------------------------------------------------
# Layer 2 — AgenticLoop default inference (source-level pin on the wiring)
# ---------------------------------------------------------------------------


def test_agentic_loop_default_source_no_longer_payg_literal() -> None:
    """Source-level pin: AgenticLoop default goes through ``infer_source``, not literal ``"payg"``.

    A regression that re-introduces ``source or "payg"`` would re-collapse
    every interactive call (the daemon never passes ``source=``) onto the
    PAYG adapter and silently masquerade an OAuth-registered subscription
    operator's session as a PAYG call. The fix lives in
    :func:`core.agent.loop.agent_loop.AgenticLoop.__init__` and must
    consult :func:`infer_source` before defaulting.
    """
    loop_source = (
        Path(__file__).resolve().parents[1] / "core" / "agent" / "loop" / "agent_loop.py"
    ).read_text(encoding="utf-8")
    # The legacy single-line default must be gone.
    assert 'self._source = source or "payg"' not in loop_source, (
        "AgenticLoop.__init__ still uses the literal-payg default — the "
        "daemon path will silently route OAuth-registered providers through "
        "the depleted PAYG endpoint."
    )
    # The inference call must be present.
    assert "infer_source(provider)" in loop_source, (
        "AgenticLoop.__init__ no longer consults infer_source — the "
        "credential_source setting + ProfileStore OAuth presence will be "
        "ignored when source is unspecified."
    )


def test_reflection_node_no_longer_hardcodes_payg() -> None:
    """Source-level pin: reflection dispatch uses ``infer_source(provider)``."""
    reflection_source = (
        Path(__file__).resolve().parents[1] / "core" / "agent" / "loop" / "_reflection.py"
    ).read_text(encoding="utf-8")
    assert (
        'resolve_for(_normalize_provider_for_registry(provider), "payg")' not in reflection_source
    ), (
        "_reflection.py still hard-codes the payg source — subscription-only "
        "operators reflect through the depleted PAYG endpoint."
    )
    assert "infer_source(provider)" in reflection_source, (
        "_reflection.py no longer threads infer_source through reflection dispatch."
    )


def test_self_improving_runner_no_longer_hardcodes_payg() -> None:
    """Source-level pin: self-improving mutator uses ``infer_source(provider)``."""
    runner_source = (
        Path(__file__).resolve().parents[1] / "core" / "self_improving_loop" / "runner.py"
    ).read_text(encoding="utf-8")
    assert 'resolve_for(_normalize_provider_for_registry(provider), "payg")' not in runner_source, (
        "runner.py still hard-codes the payg source on the mutator path."
    )
    assert "infer_source(provider)" in runner_source, (
        "runner.py no longer threads infer_source through the mutator dispatch."
    )


def test_agentic_loop_explicit_source_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``source=`` kwarg bypasses inference (caller authority preserved).

    Pinned because the audit-subprocess path (``geode_target.py`` after PR
    #1792) deliberately passes the alias-translated source via
    ``source=...`` — the inference must not override it.
    """
    from core.llm.adapters.registry import _reset_for_test

    from core.llm.adapters import bootstrap_builtins

    _patch_settings(monkeypatch, openai_credential_source="oauth")
    _patch_store(monkeypatch, _stub_store([]))

    try:
        _reset_for_test()
        bootstrap_builtins()

        # Build a loop with an explicit source — inference would say
        # "subscription" but explicit "payg" should win.
        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(action_handlers={}, hitl_level=0),
            model="gpt-5.5",
            provider="openai-codex",
            source="payg",
            quiet=True,
            max_rounds=0,
        )
        assert loop._source == "payg", (
            f"Explicit source='payg' was overridden by inference "
            f"(loop._source={loop._source!r}); caller authority broken."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()


def test_agentic_loop_dispatches_codex_oauth_when_oauth_profile_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end pin: gpt-5.5 + OAuth profile → codex-oauth adapter, not openai-payg.

    This is the exact user incident. Without the fix:
      - ``self._source = source or "payg"`` → ``"payg"``
      - ``_PROVIDER_NORMALIZATION["openai-codex"]`` → ``"openai"``
      - ``resolve_for("openai", "payg")`` → ``openai-payg``
      - HTTP call lands on ``api.openai.com`` → ``insufficient_quota``.
    With the fix the dispatched adapter must be ``codex-oauth``.
    """
    from core.llm.adapters.registry import _reset_for_test

    from core.llm.adapters import bootstrap_builtins

    _patch_settings(monkeypatch, openai_credential_source="auto")
    _patch_store(
        monkeypatch,
        _stub_store(
            [
                AuthProfile(
                    name="openai-codex-geode:user",
                    provider="openai-codex",
                    credential_type=CredentialType.OAUTH,
                    key="dummy",
                    plan_id="openai-codex-geode",
                )
            ]
        ),
    )

    try:
        _reset_for_test()
        bootstrap_builtins()

        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(action_handlers={}, hitl_level=0),
            model="gpt-5.5",
            provider="openai-codex",
            quiet=True,
            max_rounds=0,
        )
        assert loop._new_adapter.name == "codex-oauth", (
            f"AgenticLoop dispatched {loop._new_adapter.name!r} instead of "
            f"codex-oauth; the OAuth-promotion fix is wired wrong and the "
            f"user's subscription bucket is bypassed."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()


def test_agentic_loop_dispatches_openai_payg_without_oauth_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical default preserved: no OAuth profile → openai-payg dispatch."""
    from core.llm.adapters.registry import _reset_for_test

    from core.llm.adapters import bootstrap_builtins

    _patch_settings(monkeypatch, openai_credential_source="auto")
    _patch_store(monkeypatch, _stub_store([]))

    try:
        _reset_for_test()
        bootstrap_builtins()

        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(action_handlers={}, hitl_level=0),
            model="gpt-5.5",
            provider="openai-codex",
            quiet=True,
            max_rounds=0,
        )
        assert loop._new_adapter.name == "openai-payg", (
            f"Without an OAuth profile, AgenticLoop must keep dispatching "
            f"openai-payg (the historical default); got {loop._new_adapter.name!r}."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()


# ---------------------------------------------------------------------------
# Layer 3 — classifier: insufficient_quota → billing, not rate_limit
# ---------------------------------------------------------------------------


def _make_openai_rate_limit_error(*, body_code: str | None) -> Exception:
    """Synthesise an ``openai.RateLimitError`` carrying a structured body."""
    import httpx
    import openai

    body: dict[str, object] = {}
    if body_code is not None:
        body["error"] = {"code": body_code, "message": "synthetic", "type": body_code}
    response = httpx.Response(
        status_code=429,
        json=body or {"error": {"message": "synthetic"}},
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    return openai.RateLimitError("synthetic", response=response, body=body or None)


def test_classifier_insufficient_quota_maps_to_billing() -> None:
    """PAYG balance depletion must NOT surface as rate_limit (operator gets wrong action)."""
    from core.llm.errors import classify_llm_error

    exc = _make_openai_rate_limit_error(body_code="insufficient_quota")
    error_type, severity, hint = classify_llm_error(exc)
    assert error_type == "billing", (
        f"insufficient_quota classified as {error_type!r}; the operator will "
        f"see 'Switch to a different model' instead of the correct 'change "
        f"credential source' action."
    )
    assert severity == "critical"
    assert "credit" in hint.lower() or "billing" in hint.lower() or "balance" in hint.lower()


def test_classifier_billing_hard_limit_maps_to_billing() -> None:
    """The other PAYG billing-fatal code also routes to billing."""
    from core.llm.errors import classify_llm_error

    exc = _make_openai_rate_limit_error(body_code="billing_hard_limit_reached")
    error_type, _, _ = classify_llm_error(exc)
    assert error_type == "billing"


def test_classifier_transient_429_still_rate_limit() -> None:
    """OAuth subscription 429 (no insufficient_quota code) keeps rate_limit classification.

    The fix must not collapse every RateLimitError into billing — transient
    throttling on the subscription endpoint (no ``error.code`` field in
    body) must keep the rate_limit hint so the existing retry path stays
    reachable.
    """
    from core.llm.errors import classify_llm_error

    exc = _make_openai_rate_limit_error(body_code=None)
    error_type, _, _ = classify_llm_error(exc)
    assert error_type == "rate_limit", (
        f"Transient 429 (no billing code) classified as {error_type!r}; "
        f"the existing retry path is bypassed."
    )

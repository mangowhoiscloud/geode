"""v0.52.4 — Plan-aware routing policy: SUBSCRIPTION/OAUTH wins over PAYG.

Pre-fix bug (production incident, 2026-04-26): user registered
``openai-codex-geode`` (OAuth Plus subscription, provider=``openai-codex``)
via ``/login oauth openai`` BUT every ``gpt-5.4`` LLM call still hit
``api.openai.com/v1/responses`` (PAYG, provider=``openai``) at $0.10/call
because ``_resolve_provider("gpt-5.4")`` was a static map and the
``PlanRegistry.resolve_routing()`` resolver was never consulted by the
LLM call path.

Three contracts pinned here:

1. **Equivalence-class scan** — when both ``openai-codex`` (OAuth) and
   ``openai`` (PAYG) plans are registered, the resolver returns the
   ``openai-codex`` plan first. Pattern source: openai/codex CLI default
   (``forced_login_method`` unset → ChatGPT subscription wins).

2. **`forced_login_method = "apikey"` escape hatch** — same setup but
   user explicitly wants metered PAYG; resolver returns ``openai`` plan.
   Pattern source: openai/codex#2733 — same flag inverted.

3. **Router wiring** — ``core/llm/router.py`` ``_route_provider(model)``
   calls ``resolve_routing`` and returns the actually-routed provider,
   not the static ``_resolve_provider`` answer. Without the wiring, the
   policy fix is invisible to real LLM calls.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import core.llm.router as _router_mod
import pytest
from core.auth.plan_registry import resolve_routing
from core.auth.plans import PLAN_KIND_PRIORITY, Plan, PlanKind
from core.auth.profiles import AuthProfile, CredentialType
from core.llm.registry import equivalent_providers

# ---------------------------------------------------------------------------
# Contract 0 — equivalence map + kind priority sanity
# ---------------------------------------------------------------------------


def test_plan_kind_priority_subscription_first() -> None:
    """SUBSCRIPTION must rank before PAYG. The OAuth/Plus plans are
    prepaid; routing them to PAYG silently re-meters the same call."""
    assert PLAN_KIND_PRIORITY[PlanKind.SUBSCRIPTION] < PLAN_KIND_PRIORITY[PlanKind.PAYG]
    assert PLAN_KIND_PRIORITY[PlanKind.OAUTH_BORROWED] < PLAN_KIND_PRIORITY[PlanKind.PAYG]
    # CLOUD_PROVIDER (Bedrock/Vertex) is also prepaid via cloud commitment.
    assert PLAN_KIND_PRIORITY[PlanKind.CLOUD_PROVIDER] < PLAN_KIND_PRIORITY[PlanKind.PAYG]


def test_openai_equivalence_class_pairs_with_codex() -> None:
    """openai and openai-codex must share an equivalence class so a
    Codex Plus OAuth plan is considered when the user requests gpt-5.x."""
    eq = equivalent_providers("openai")
    assert "openai-codex" in eq
    assert "openai" in eq
    # Preferred-first ordering: codex (OAuth) before openai (PAYG).
    assert eq.index("openai-codex") < eq.index("openai")


def test_unrelated_provider_is_singleton() -> None:
    """Anthropic and GLM must NOT pull in unrelated siblings."""
    assert equivalent_providers("anthropic") == ["anthropic"]
    # GLM has its own equivalence class for the Coding Plan vs PAYG split.
    glm_class = equivalent_providers("glm")
    assert set(glm_class) == {"glm-coding", "glm"}


# ---------------------------------------------------------------------------
# Contract 1 — resolve_routing prefers SUBSCRIPTION plan over PAYG
# ---------------------------------------------------------------------------


def _seed_two_plans(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Plan, Plan]:
    """Helper: register both an OAuth Codex Plus plan and a PAYG OpenAI
    plan, each with an available profile. Returns (subscription_plan,
    payg_plan)."""
    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    from core.auth import plan_registry as _pr
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle import container as _infra
    from core.lifecycle.container import ensure_profile_store

    _infra._profile_store = None
    _pr._plan_registry = None

    registry = get_plan_registry()
    store = ensure_profile_store()

    sub_plan = Plan(
        id="openai-codex-geode",
        provider="openai-codex",
        kind=PlanKind.OAUTH_BORROWED,
        display_name="OpenAI Codex (Plus)",
        base_url="https://chatgpt.com/backend-api/codex",
        auth_type="oauth_external",
    )
    registry.add(sub_plan)
    store.add(
        AuthProfile(
            name="openai-codex:geode",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="oauth-token-xyz",
            plan_id=sub_plan.id,
        )
    )

    payg_plan = Plan(
        id="openai-payg",
        provider="openai",
        kind=PlanKind.PAYG,
        display_name="OpenAI (PAYG)",
        base_url="https://api.openai.com/v1",
    )
    registry.add(payg_plan)
    store.add(
        AuthProfile(
            name="openai:payg",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            key="sk-test-payg",
            plan_id=payg_plan.id,
        )
    )
    return sub_plan, payg_plan


def test_resolve_routing_prefers_oauth_over_payg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both plans registered, no explicit /login route — Codex Plus must win.
    This is the v0.52.1-incident-defining contract: a user who paid for
    Plus must not be billed PAYG for the same model."""
    sub_plan, _ = _seed_two_plans(monkeypatch, tmp_path)
    target = resolve_routing("gpt-5.4")
    assert target is not None, "no routing target — singleton seeding broke?"
    assert target.plan.id == sub_plan.id, (
        f"routed to {target.plan.id}; expected {sub_plan.id}. "
        "Equivalence-class scan + PLAN_KIND_PRIORITY didn't run, or "
        "ProfileRotator picked the PAYG profile despite OAuth availability."
    )
    assert target.plan.provider == "openai-codex"
    assert target.base_url == "https://chatgpt.com/backend-api/codex"


def test_resolve_routing_explicit_set_routing_wins_over_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If user set ``/login route gpt-5.4 openai-payg``, the explicit
    override must win even though kind-priority would prefer OAuth."""
    from core.auth.plan_registry import get_plan_registry

    _, payg_plan = _seed_two_plans(monkeypatch, tmp_path)
    get_plan_registry().set_routing("gpt-5.4", [payg_plan.id])

    target = resolve_routing("gpt-5.4")
    assert target is not None
    assert target.plan.id == payg_plan.id, (
        "explicit set_routing must override the equivalence-class default"
    )


# ---------------------------------------------------------------------------
# Contract 2 — forced_login_method = "apikey" escape hatch
# ---------------------------------------------------------------------------


def test_forced_login_method_apikey_promotes_payg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex CLI parity: ``forced_login_method = {"openai": "apikey"}``
    flips the kind-priority so PAYG wins. For the user who deliberately
    wants metered API access despite an active OAuth subscription."""
    _, payg_plan = _seed_two_plans(monkeypatch, tmp_path)
    from core.config import settings

    monkeypatch.setattr(settings, "forced_login_method", {"openai": "apikey"})

    target = resolve_routing("gpt-5.4")
    assert target is not None
    assert target.plan.id == payg_plan.id, (
        "forced_login_method='apikey' must route to PAYG. "
        "Reference: openai/codex#2733 same flag, inverted."
    )


def test_forced_login_method_default_keeps_subscription_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No forced_login_method ⇒ default (subscription wins). Pin the
    default explicitly so a refactor that swaps the default is caught."""
    sub_plan, _ = _seed_two_plans(monkeypatch, tmp_path)
    from core.config import settings

    # Either unset or "subscription" — both must keep OAuth winning.
    monkeypatch.setattr(settings, "forced_login_method", {})
    assert resolve_routing("gpt-5.4").plan.id == sub_plan.id  # type: ignore[union-attr]

    monkeypatch.setattr(settings, "forced_login_method", {"openai": "subscription"})
    assert resolve_routing("gpt-5.4").plan.id == sub_plan.id  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Contract 3 — router.py wires resolve_routing through _route_provider
# ---------------------------------------------------------------------------


def test_router_route_provider_helper_exists() -> None:
    """``core/llm/router.py`` must define ``_route_provider`` and use it
    in every call_llm* entry. Pre-v0.52.4 the call sites used the static
    ``_resolve_provider`` directly, which bypassed PlanRegistry entirely.
    """
    src = inspect.getsource(_router_mod)
    assert "def _route_provider(" in src, (
        "_route_provider helper missing — without it the policy is invisible to actual LLM calls."
    )
    # All 4 call sites must use the new helper.
    assert src.count("_route_provider(target_model)") >= 4, (
        f"expected ≥4 call sites using _route_provider; got "
        f"{src.count('_route_provider(target_model)')}. "
        "Some call_llm* path still uses the static _resolve_provider."
    )
    # And the static helper must NOT be called directly with target_model
    # in a router function body (the only allowed direct uses are inside
    # _route_provider's own fallback path).
    static_calls = src.count("_resolve_provider(target_model)")
    assert static_calls == 0, (
        f"{static_calls} call sites still use _resolve_provider(target_model) "
        f"directly — should go through _route_provider for plan-awareness"
    )


def test_route_provider_falls_back_when_resolve_routing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When PlanRegistry has no plan for the model, ``_route_provider``
    must fall back to the static ``_resolve_provider`` so legacy env-var
    users (no /login add) still route correctly."""
    monkeypatch.setattr("core.auth.plan_registry.resolve_routing", lambda _model: None)
    monkeypatch.setattr("core.llm.router._resolve_provider", lambda _m: "anthropic")
    assert _router_mod._route_provider("claude-opus-4-7") == "anthropic"


def test_route_provider_returns_routed_provider_when_plan_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When resolve_routing returns a Plan, ``_route_provider`` must
    return the Plan's provider — not the static map."""
    fake_plan = Plan(
        id="openai-codex-geode",
        provider="openai-codex",
        kind=PlanKind.OAUTH_BORROWED,
        display_name="OpenAI Codex Plus",
        base_url="https://chatgpt.com/backend-api/codex",
    )
    fake_target = type(
        "T",
        (),
        {"plan": fake_plan, "profile": None, "base_url": fake_plan.base_url},
    )()
    monkeypatch.setattr("core.auth.plan_registry.resolve_routing", lambda _m: fake_target)
    # Static fallback would have returned "openai"; the Plan-aware path
    # must override to "openai-codex".
    assert _router_mod._route_provider("gpt-5.4") == "openai-codex"

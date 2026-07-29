"""v0.52.4 — Plan-aware routing policy: SUBSCRIPTION/OAUTH wins over PAYG.

Pre-fix bug (production incident, 2026-04-26): user registered
``openai-codex-geode`` (OAuth Plus subscription, provider=``openai-codex``)
via ``/login openai`` BUT every ``gpt-5.4`` LLM call still hit
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

from pathlib import Path
from unittest.mock import patch

import pytest
from core.auth.profiles import AuthProfile, CredentialType
from core.llm.registry import equivalent_providers
from core.llm.strategies.plan_registry import resolve_routing
from core.llm.strategies.plans import PLAN_KIND_PRIORITY, Plan, PlanKind

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
    Codex OAuth plan is considered when the user requests gpt-5.x."""
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
    """Helper: register both an OAuth Codex plan and a PAYG OpenAI
    plan, each with an available profile. Returns (subscription_plan,
    payg_plan)."""
    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    from core.llm.strategies import plan_registry as _pr
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring import container as _infra
    from core.wiring.container import ensure_profile_store

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
    """Both plans registered, no explicit /login route — Codex must win.
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
    from core.llm.strategies.plan_registry import get_plan_registry

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


def test_failover_enforces_model_allowlist_per_model() -> None:
    """The live async entry consults the routing policy for EVERY model.

    2026-07-29: ``call_llm`` / ``_route_provider`` were deleted with the sync
    stack. This pins behaviour (not a source-string grep — the first
    replacement did exactly that and passed vacuously, Codex review): a model
    the policy disallows must never reach the call function.
    """
    import asyncio

    from core.llm.router.calls import _failover as _failover_mod

    attempted: list[str] = []

    async def _call(model: str) -> str:
        attempted.append(model)
        return "ok"

    with patch.object(_failover_mod, "is_model_allowed", side_effect=lambda m: m != "blocked"):
        result, used = asyncio.run(_failover_mod.call_with_failover(["blocked", "allowed"], _call))

    assert attempted == ["allowed"], "policy-disallowed model must not be called"
    assert used == "allowed"
    assert result == "ok"

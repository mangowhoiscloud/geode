"""PlanRegistry — runtime store for Plan instances + routing resolution.

Sits next to ProfileStore. The CLI (`/login`) creates Plans here and
binds AuthProfiles to them via `plan_id`. Provider modules query this
registry through `resolve_routing(model)` to pick the active endpoint
and credential.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.auth.plans import Plan, PlanUsage, default_plan_for_payg
from core.auth.profiles import AuthProfile

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore
    from core.auth.rotation import ProfileRotator


@dataclass
class RoutingTarget:
    """Output of resolve_routing(): which Plan + Profile to use for a model."""

    plan: Plan
    profile: AuthProfile
    base_url: str  # final endpoint (Plan.base_url respecting profile override)


class PlanRegistry:
    """In-memory Plan store with model-routing resolution.

    Keyed by Plan.id. A separate `_routing` map records the preferred
    Plan ID order for each model name (set by the user via
    `/login route`).
    """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._usage: dict[str, PlanUsage] = {}
        # model_pattern -> ordered list of plan_ids
        self._routing: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    # --- Plan CRUD ---

    def add(self, plan: Plan) -> None:
        with self._lock:
            self._plans[plan.id] = plan
            self._usage.setdefault(plan.id, PlanUsage(plan_id=plan.id))

    def get(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def remove(self, plan_id: str) -> bool:
        with self._lock:
            existed = self._plans.pop(plan_id, None) is not None
            self._usage.pop(plan_id, None)
            for model, ids in list(self._routing.items()):
                self._routing[model] = [i for i in ids if i != plan_id]
                if not self._routing[model]:
                    del self._routing[model]
            return existed

    def list_all(self) -> list[Plan]:
        return list(self._plans.values())

    def list_for_provider(self, provider: str) -> list[Plan]:
        return [p for p in self._plans.values() if p.provider == provider]

    def usage_for(self, plan_id: str) -> PlanUsage:
        return self._usage.setdefault(plan_id, PlanUsage(plan_id=plan_id))

    # --- Routing ---

    def set_routing(self, model: str, plan_ids: list[str]) -> None:
        with self._lock:
            self._routing[model] = list(plan_ids)

    def get_routing(self, model: str) -> list[str]:
        return list(self._routing.get(model, ()))

    def all_routing(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._routing.items()}

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()
            self._usage.clear()
            self._routing.clear()


# Module-level singleton (mirrors ProfileStore lifecycle)
_plan_registry: PlanRegistry | None = None
_registry_lock = threading.Lock()


def get_plan_registry() -> PlanRegistry:
    """Return the singleton PlanRegistry, building it if necessary."""
    global _plan_registry
    if _plan_registry is None:
        with _registry_lock:
            if _plan_registry is None:
                _plan_registry = PlanRegistry()
    return _plan_registry


def reset_plan_registry() -> None:
    """Test helper — clear the singleton between tests."""
    global _plan_registry
    with _registry_lock:
        _plan_registry = None


# ---------------------------------------------------------------------------
# Routing resolution — model → (Plan, AuthProfile, base_url)
# ---------------------------------------------------------------------------


def resolve_routing(model: str) -> RoutingTarget | None:
    """Resolve which Plan + AuthProfile should serve a given model.

    Resolution order:
      1. Explicit per-model routing (``PlanRegistry.set_routing``) — try
         each Plan ID in order and return the first whose linked
         AuthProfile is available.
      2. (v0.52.4) **Equivalence-class scan** — gather every Plan whose
         provider is in the resolved provider's equivalence class
         (e.g. ``openai`` → ``[openai-codex, openai]``), sort by
         ``(PLAN_KIND_PRIORITY, profile.sort_key())`` so SUBSCRIPTION /
         OAUTH plans win over PAYG, then pick the first with an
         available profile. The user paid for the prepaid plan; routing
         it to PAYG silently re-meters the same call.
      3. Fall back to the model's resolved provider directly
         (``_resolve_provider``) — keeps the legacy single-provider path
         alive for environments where no Plan was registered.
      4. Synthesize a PAYG Plan so env-var-only users still route.

    The user can override the policy globally via the per-provider
    ``settings.forced_login_method`` config (Codex CLI parity) — see
    ``_apply_forced_login_method`` below.

    Returns None when no usable credential exists.
    """
    from core.config import _resolve_provider
    from core.lifecycle.container import get_profile_rotator, get_profile_store

    registry = get_plan_registry()
    store = get_profile_store()
    rotator = get_profile_rotator()
    if store is None or rotator is None:
        return None

    # 1) explicit per-model routing
    explicit_chain: list[Plan] = []
    for plan_id in registry.get_routing(model):
        plan = registry.get(plan_id)
        if plan is not None:
            explicit_chain.append(plan)
    if explicit_chain:
        for plan in explicit_chain:
            profile = _pick_profile_for_plan(store, rotator, plan)
            if profile is not None:
                return RoutingTarget(
                    plan=plan,
                    profile=profile,
                    base_url=profile.base_url_override or plan.base_url,
                )

    base_provider = _resolve_provider(model)

    # 2) equivalence-class scan — sibling providers, kind-priority sorted
    eq_chain = _equivalence_class_plans(registry, base_provider)
    eq_chain = _apply_forced_login_method(eq_chain, base_provider)
    for plan in eq_chain:
        profile = _pick_profile_for_plan(store, rotator, plan)
        if profile is not None:
            return RoutingTarget(
                plan=plan,
                profile=profile,
                base_url=profile.base_url_override or plan.base_url,
            )

    # 3) single-provider fallback (legacy)
    plan_chain = registry.list_for_provider(base_provider)
    for plan in plan_chain:
        profile = _pick_profile_for_plan(store, rotator, plan)
        if profile is not None:
            return RoutingTarget(
                plan=plan,
                profile=profile,
                base_url=profile.base_url_override or plan.base_url,
            )

    # 4) synthesize PAYG Plan so legacy env-var users still route
    profile = rotator.resolve(base_provider)
    if profile is None:
        return None
    plan = default_plan_for_payg(base_provider, profile.key)
    return RoutingTarget(
        plan=plan,
        profile=profile,
        base_url=profile.base_url_override or plan.base_url,
    )


def _equivalence_class_plans(registry: PlanRegistry, base_provider: str) -> list[Plan]:
    """Collect Plans across the equivalence class, sorted by kind priority.

    Sort key: ``PLAN_KIND_PRIORITY[plan.kind]`` (lower wins).
    Within tier, preserve registry insertion order (stable sort).
    """
    from core.auth.plans import PLAN_KIND_PRIORITY
    from core.llm.registry import equivalent_providers

    candidates: list[Plan] = []
    for sibling in equivalent_providers(base_provider):
        candidates.extend(registry.list_for_provider(sibling))
    # De-duplicate by Plan.id while preserving order
    seen: set[str] = set()
    unique: list[Plan] = []
    for plan in candidates:
        if plan.id in seen:
            continue
        seen.add(plan.id)
        unique.append(plan)
    unique.sort(key=lambda p: PLAN_KIND_PRIORITY.get(p.kind, 99))
    return unique


def _apply_forced_login_method(plans: list[Plan], base_provider: str) -> list[Plan]:
    """Apply the per-provider ``forced_login_method`` escape hatch.

    Codex CLI's ``forced_login_method = "api"`` semantic: when set, the
    user wants the API-key path even though a subscription is active.
    GEODE mirrors this so users who deliberately want metered PAYG can
    keep their config.

    Values:
      - ``"subscription"`` (default) — keep current sort (sub/oauth first)
      - ``"apikey"`` — promote PAYG plans to the front
      - ``"auto"`` — alias for default
    """
    from core.auth.plans import PlanKind
    from core.config import settings

    forced = (getattr(settings, "forced_login_method", {}) or {}).get(base_provider, "subscription")
    forced = str(forced).strip().lower()
    if forced in ("apikey", "api", "api_key", "key"):
        # Stable partition: PAYG first, then everyone else in original order.
        payg = [p for p in plans if p.kind is PlanKind.PAYG]
        rest = [p for p in plans if p.kind is not PlanKind.PAYG]
        return payg + rest
    return plans


def _pick_profile_for_plan(
    store: ProfileStore,
    rotator: ProfileRotator,
    plan: Plan,
) -> AuthProfile | None:
    """Find an available AuthProfile bound to this Plan, or fall back
    to any available profile for the Plan's provider."""
    bound: list[AuthProfile] = [
        p for p in store.list_all() if p.plan_id == plan.id and p.is_available
    ]
    if bound:
        bound.sort(key=lambda p: p.sort_key())
        return bound[0]
    return rotator.resolve(plan.provider)

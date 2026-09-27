"""Resolve operator policy once; refresh accounts only within that concrete route.

Settings and model plan chains seed new sessions. SessionModelConfig owns the
result afterwards: account lookup must never change its billing source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.auth.profiles import AuthProfile, CredentialType
from core.llm.registry import CONCRETE_SOURCES, SOURCE_PAYG, ProviderSpec, provider_specs_for
from core.llm.strategies.plan_registry import get_plan_registry
from core.llm.strategies.plans import PLAN_KIND_PRIORITY, Plan, PlanKind

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore
    from core.config import Settings
    from core.config.policy_source import PolicySourcePaths


@dataclass(frozen=True, slots=True)
class RoutingTarget:
    """An available account on an already selected provider/source/endpoint."""

    plan: Plan
    profile: AuthProfile
    base_url: str


def _provider_specs(provider: str) -> tuple[ProviderSpec, ...]:
    from core.llm.adapters.registry import active_registry_snapshot, normalize_registry_provider

    provider = normalize_registry_provider(provider)
    declared = {spec.credential.source: spec for spec in provider_specs_for(provider)}
    for registration in active_registry_snapshot().registrations.values():
        spec = registration.provider_spec
        if spec is not None and spec.profile.provider == provider:
            declared[spec.credential.source] = spec
    if not declared:
        raise RuntimeError(f"provider {provider!r} has no registered credential route")
    return tuple(declared.values())


def _load_profile_store() -> ProfileStore:
    from core.wiring.container import ensure_profile_store

    return ensure_profile_store()


def _model_plans(model: str, sources: PolicySourcePaths | None) -> list[Plan]:
    from core.llm.strategies.provider_routing_policy import (
        _load_provider_routing_override,
        apply_provider_routing_policy,
    )

    if not model:
        return []
    registry = get_plan_registry()
    ids = apply_provider_routing_policy(
        model, registry.get_routing(model), _load_provider_routing_override(sources=sources)
    )
    plans: list[Plan] = []
    for plan_id in ids:
        plan = registry.get(plan_id)
        if plan is None:
            raise RuntimeError(f"model {model!r} references unknown plan {plan_id!r}")
        plans.append(plan)
    return plans


def _policy_source(
    specs: tuple[ProviderSpec, ...],
    credential_source: str | None = None,
    settings: Settings | None = None,
) -> str:
    from core.config import _get_settings
    from core.config.credential_source import CLAUDE_CLI_RETIRED_MESSAGE

    effective = settings if settings is not None else _get_settings()
    provider = specs[0].profile.provider
    fields = {spec.credential.settings_field for spec in specs if spec.credential.settings_field}
    if len(fields) > 1:
        raise RuntimeError(f"provider {provider!r} declares multiple credential setting fields")
    field = next(iter(fields), "")
    raw = (
        credential_source
        if credential_source is not None
        else (str(getattr(effective, field, "auto") or "auto").lower() if field else "auto")
    )
    if raw == "none":
        raise RuntimeError(f"provider {provider!r} is disabled by {field}='none'")
    if raw == "claude-cli" or (provider == "anthropic" and raw == "oauth"):
        raise RuntimeError(CLAUDE_CLI_RETIRED_MESSAGE)
    selected = next(
        (spec.credential.source for spec in specs if raw in spec.credential.settings_values), ""
    )
    if raw != "auto" and not selected:
        raise RuntimeError(f"{raw!r} is not a credential source for provider {provider!r}")
    forced = str(effective.forced_login_method.get(provider, "auto")).lower()
    forced_source = {
        "auto": "",
        "subscription": "subscription",
        "apikey": SOURCE_PAYG,
        "api": SOURCE_PAYG,
        "api_key": SOURCE_PAYG,
        "key": SOURCE_PAYG,
    }.get(forced)
    if forced_source is None:
        raise RuntimeError(f"unsupported forced login method for provider {provider!r}")
    if selected and forced_source and selected != forced_source:
        raise RuntimeError(f"conflicting credential policies for provider {provider!r}")
    return selected or forced_source


def _select_route(
    provider: str,
    model: str,
    source: str | None,
    sources: PolicySourcePaths | None,
    credential_source: str | None = None,
    settings: Settings | None = None,
) -> tuple[ProviderSpec, list[Plan], bool]:
    from core.wiring.container import get_profile_store

    if sources is None:
        from core.config.policy_source import PolicySourcePaths
        from core.llm.adapters.registry import active_registry_snapshot, normalize_registry_provider

        family = normalize_registry_provider(provider)
        inherited = {
            candidate
            for adapter in active_registry_snapshot().list_adapters()
            if adapter.provider == family
            and isinstance(
                candidate := getattr(adapter, "routing_sources", None), PolicySourcePaths
            )
        }
        if len(inherited) > 1:
            raise RuntimeError(f"provider {family!r} has conflicting routing policy sources")
        sources = next(iter(inherited), None)

    specs = _provider_specs(provider)
    if source is not None and source not in CONCRETE_SOURCES:
        raise RuntimeError(f"source {source!r} is not a concrete adapter route")
    selected = source if source is not None else _policy_source(specs, credential_source, settings)
    candidates = [spec for spec in specs if not selected or spec.credential.source == selected]
    if not candidates:
        raise RuntimeError(f"provider {provider!r} does not support source {selected!r}")
    # A configured source is selected even while its account is unavailable;
    # quota/expiry never authorizes PAYG fallback. Account reads never hydrate.
    store = get_profile_store()
    plans = _model_plans(model, sources)
    explicit_plans = bool(plans)
    if not plans:
        plans = get_plan_registry().list_all()
        plans.sort(key=lambda plan: PLAN_KIND_PRIORITY[plan.kind])
    ids = {spec.id for spec in specs}
    if explicit_plans and any(plan.provider not in ids for plan in plans):
        raise RuntimeError(f"model {model!r} has a plan for a different provider")
    plans = [plan for plan in plans if plan.provider in {spec.id for spec in candidates}]
    if explicit_plans and not plans:
        raise RuntimeError(f"model {model!r} has no plan for the selected source")
    if plans:
        spec = next(spec for spec in candidates if spec.id == plans[0].provider)
    else:
        registered = [
            spec
            for spec in candidates
            if store is not None and store.list_by_provider(spec.credential.account_provider)
        ]
        spec = next(
            (spec for spec in registered if spec.credential.source == "subscription"),
            next((spec for spec in candidates if spec.credential.default), candidates[0]),
        )
    return spec, [plan for plan in plans if plan.provider == spec.id], explicit_plans


def infer_source(
    provider: str,
    *,
    model: str = "",
    sources: PolicySourcePaths | None = None,
    credential_source: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Interpret policy for a new route; never call for a concrete session route."""
    _load_profile_store()
    spec, _, _ = _select_route(provider, model, None, sources, credential_source, settings)
    return spec.credential.source


def resolve_routing(
    model: str,
    *,
    provider: str = "",
    source: str | None = None,
    sources: PolicySourcePaths | None = None,
    base_url: str | None = None,
) -> RoutingTarget | None:
    """Select an account without escaping the chosen source or explicit plan chain.

    Missing credentials return None. Invalid policy fails explicitly. An explicit
    plan chain's unavailable account cannot fall through to another billing source.
    """
    from core.config import _resolve_provider
    from core.wiring.container import get_profile_store

    spec, plans, explicit = _select_route(
        provider or _resolve_provider(model), model, source, sources
    )
    store = get_profile_store()
    if store is None:
        if explicit:
            raise RuntimeError(f"model {model!r} has no available account on its selected plan")
        return None
    order = store.get_auth_order(spec.credential.account_provider)
    pinned = store.get_pinned_active(spec.credential.account_provider)
    if not order and pinned is not None:
        order = [pinned.name]
    ranks = {name: rank for rank, name in enumerate(order)}
    candidates: list[tuple[int, AuthProfile, Plan]] = []
    for index, plan in enumerate(plans):
        expected = {
            PlanKind.PAYG: SOURCE_PAYG,
            PlanKind.SUBSCRIPTION: "subscription",
            PlanKind.OAUTH_BORROWED: "subscription",
            PlanKind.CLOUD_PROVIDER: "adapter",
        }[plan.kind]
        if expected != spec.credential.source:
            if explicit:
                raise RuntimeError(f"plan {plan.id!r} kind conflicts with its provider route")
            continue
        profiles = [
            profile
            for profile in store.list_by_provider(spec.credential.account_provider)
            if profile.plan_id == plan.id
            and profile.key
            and profile.is_available
            and (
                spec.credential.source != SOURCE_PAYG
                or (profile.credential_type is CredentialType.API_KEY and not profile.managed_by)
            )
            and (
                explicit
                or base_url is None
                or (profile.base_url_override or plan.base_url).rstrip("/") == base_url.rstrip("/")
            )
        ]
        candidates.extend((index if explicit else 0, profile, plan) for profile in profiles)
    selected = min(
        candidates,
        key=lambda item: (
            item[0],
            ranks.get(item[1].name, len(ranks)),
            bool(item[1].managed_by),
            item[1].sort_key(),
        ),
        default=None,
    )
    if selected is not None:
        _, profile, plan = selected
        return RoutingTarget(plan, profile, profile.base_url_override or plan.base_url)
    if explicit:
        raise RuntimeError(f"model {model!r} has no available account on its selected plan")
    return None

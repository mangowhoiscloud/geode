"""Persistence for Plans + Profile bindings → ~/.geode/auth.toml.

In-memory PlanRegistry / ProfileStore singletons (Phases 1-2) restart
empty on every process boot. This module persists user-registered Plans
and their bound credentials to a single TOML file so `/login add` is a
one-time action.

Schema:

    [[plans]]
    id = "glm-coding-lite"
    provider = "glm-coding"
    kind = "subscription"
    display_name = "GLM Coding Lite"
    base_url = "https://api.z.ai/api/coding/paas/v4"
    auth_type = "bearer"
    subscription_tier = "Lite"
    upgrade_url = "https://z.ai/subscribe"

    [plans.quota]
    window_s = 18000
    max_calls = 80
    model_weights = { "glm-5.1" = 3.0 }

    [[profiles]]
    name = "glm-coding-lite:user"
    provider = "glm-coding"
    plan_id = "glm-coding-lite"
    credential_type = "api_key"
    key = "..."

    [routing]
    "glm-5.1" = ["glm-coding-lite", "glm-payg"]

API keys live in this file in plaintext just like .env. The file is
created with mode 0600 so other users on the host can't read it.
"""

from __future__ import annotations

import fcntl
import logging
import math
import os
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.llm.strategies.plan_registry import PlanRegistry, get_plan_registry
from core.llm.strategies.plans import Plan, PlanKind, Quota
from core.paths import GLOBAL_AUTH_TOML

log = logging.getLogger(__name__)

DEFAULT_AUTH_TOML: Path = GLOBAL_AUTH_TOML


def auth_toml_path() -> Path:
    """Resolve auth.toml location, honoring `GEODE_AUTH_TOML` env override."""
    override = os.environ.get("GEODE_AUTH_TOML")
    # expanduser so GEODE_AUTH_TOML=~/x resolves (PR-PATH-MODERNIZE — consistency
    # with GEODE_CONFIG_TOML / GEODE_DIAGNOSTICS_LOG / GEODE_HOME).
    return Path(override).expanduser() if override else DEFAULT_AUTH_TOML


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _plan_to_dict(plan: Plan) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": plan.id,
        "provider": plan.provider,
        "kind": plan.kind.value,
        "display_name": plan.display_name,
        "base_url": plan.base_url,
        "auth_type": plan.auth_type,
    }
    if plan.subscription_tier:
        out["subscription_tier"] = plan.subscription_tier
    if plan.upgrade_url:
        out["upgrade_url"] = plan.upgrade_url
    if plan.quota is not None:
        out["quota"] = {
            "window_s": plan.quota.window_s,
            "max_calls": plan.quota.max_calls,
            "model_weights": plan.quota.model_weights,
        }
    return out


def _plan_from_dict(d: dict[str, Any]) -> Plan:
    quota = None
    if "quota" in d:
        q = d["quota"]
        quota = Quota(
            window_s=int(q.get("window_s", 0)),
            max_calls=int(q.get("max_calls", 0)),
            model_weights={k: float(v) for k, v in q.get("model_weights", {}).items()},
        )
    return Plan(
        id=str(d["id"]),
        provider=str(d["provider"]),
        kind=PlanKind(d.get("kind", "payg")),
        display_name=str(d.get("display_name", d["id"])),
        base_url=str(d.get("base_url", "")),
        auth_type=str(d.get("auth_type", "bearer")),
        quota=quota,
        subscription_tier=d.get("subscription_tier"),
        upgrade_url=d.get("upgrade_url"),
    )


def _profile_to_dict(p: AuthProfile) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": p.name,
        "provider": p.provider,
        "credential_type": p.credential_type.value,
        "key": p.key,
    }
    if p.plan_id:
        out["plan_id"] = p.plan_id
    if p.refresh_token:
        out["refresh_token"] = p.refresh_token
    if p.expires_at:
        out["expires_at"] = p.expires_at
    if p.managed_by:
        out["managed_by"] = p.managed_by
    if p.base_url_override:
        out["base_url_override"] = p.base_url_override
    return out


def _profile_from_dict(d: dict[str, Any]) -> AuthProfile:
    return AuthProfile(
        name=str(d["name"]),
        provider=str(d["provider"]),
        credential_type=CredentialType(d.get("credential_type", "api_key")),
        key=str(d.get("key", "")),
        refresh_token=str(d.get("refresh_token", "")),
        expires_at=float(d.get("expires_at", 0.0)),
        managed_by=str(d.get("managed_by", "")),
        plan_id=str(d.get("plan_id", "")),
        base_url_override=d.get("base_url_override"),
    )


def _auth_candidate(
    data: dict[str, Any],
) -> tuple[
    list[Plan], list[AuthProfile], dict[str, list[str]], dict[str, str], dict[str, list[str]]
]:
    """Validate the complete file before any live registry can be changed."""
    plan_rows = data.get("plans", [])
    profile_rows = data.get("profiles", [])
    if not isinstance(plan_rows, list) or not isinstance(profile_rows, list):
        raise ValueError("plans and profiles must be arrays of tables")
    for rows, identity in ((plan_rows, "id"), (profile_rows, "name")):
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("auth entries must be tables")
            for field in (identity, "provider"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError("auth identity and provider must be nonempty strings")
            if row[identity] in seen:
                raise ValueError("duplicate auth identity")
            seen.add(row[identity])
    plans = [_plan_from_dict(row) for row in plan_rows]
    profiles = [_profile_from_dict(row) for row in profile_rows]
    for raw, profile in zip(profile_rows, profiles, strict=True):
        if profile.managed_by or not math.isfinite(profile.expires_at):
            raise ValueError("managed credentials and nonfinite expiry are not file-owned")
        for field in ("key", "refresh_token", "plan_id"):
            if not isinstance(raw.get(field, ""), str):
                raise ValueError("credential fields must be strings")
        if raw.get("base_url_override") is not None and not isinstance(
            raw["base_url_override"], str
        ):
            raise ValueError("profile endpoint must be a string or absent")
    by_name = {profile.name: profile for profile in profiles}
    by_id = {plan.id: plan for plan in plans}
    for profile in profiles:
        if profile.plan_id and (
            profile.plan_id not in by_id or by_id[profile.plan_id].provider != profile.provider
        ):
            raise ValueError("profile plan binding must reference its provider")
    routing = data.get("routing", {})
    pins = data.get("pinned_active", {})
    orders = data.get("auth_order", {})
    if not all(isinstance(mapping, dict) for mapping in (routing, pins, orders)):
        raise ValueError("auth routing and preferences must be tables")
    for model, chain in routing.items():
        if (
            not model
            or not isinstance(chain, list)
            or any(not isinstance(pid, str) or pid not in by_id for pid in chain)
        ):
            raise ValueError("routing must reference declared plans")
    for provider, name in pins.items():
        if not isinstance(name, str) or name not in by_name or by_name[name].provider != provider:
            raise ValueError("pin must reference a profile of the same provider")
    for provider, order in orders.items():
        if not isinstance(order, list) or any(
            not isinstance(name, str) or name not in by_name or by_name[name].provider != provider
            for name in order
        ):
            raise ValueError("auth order must reference profiles of the same provider")
        if len(set(order)) != len(order):
            raise ValueError("auth order must not contain duplicate profiles")
        if order and pins.get(provider, order[0]) != order[0]:
            raise ValueError("pin must agree with the first ordered profile")
    return plans, profiles, routing, pins, orders


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def save_auth_toml(
    *,
    registry: PlanRegistry | None = None,
    store: ProfileStore | None = None,
    path: Path | None = None,
) -> Path:
    """Serialise the current Plan + Profile state to TOML.

    Only profiles that are user-managed (no `managed_by`) are persisted.
    Codex CLI OAuth and similar borrowed credentials live in their CLI's
    own store and are re-read on every boot.
    """
    from core.wiring.container import ensure_profile_store

    registry = registry or get_plan_registry()
    store = ensure_profile_store() if store is None else store
    path = path or auth_toml_path()

    plans = registry.list_all()
    profiles = [
        p
        for p in store.list_all()
        if not p.managed_by and p.metadata.get("origin") != "environment"
    ]
    names = {profile.name for profile in profiles}
    pins, orders = store.auth_preferences()
    pins = {provider: name for provider, name in pins.items() if name in names}
    orders = {
        provider: [name for name in order if name in names] for provider, order in orders.items()
    }
    orders = {provider: order for provider, order in orders.items() if order}
    # Filtering externally managed entries can change an order's first entry.
    pins.update({provider: order[0] for provider, order in orders.items()})
    routing = registry.all_routing()
    payload: dict[str, Any] = {
        "plans": [_plan_to_dict(p) for p in plans],
        "profiles": [_profile_to_dict(p) for p in profiles],
        "routing": routing,
        "pinned_active": pins,
        "auth_order": orders,
    }
    text = _to_toml(payload)
    try:
        _auth_candidate(tomllib.loads(text))
    except ValueError as exc:  # TOMLDecodeError included; values stay out of the message
        reason = type(exc).__name__
        raise ValueError(f"refusing to write an unreadable auth file ({reason})") from exc
    from core.memory.atomic_write import atomic_write_text

    atomic_write_text(path, text)
    source = str(path.resolve())
    registry.remember_auth_file(source, plans, routing)
    store.remember_auth_file(source, profiles, pins, orders)
    return path


# ---------------------------------------------------------------------------
# Hand-rolled TOML writer — schema is small + fixed, no third-party dep.
# ---------------------------------------------------------------------------


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + " }"
        )
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


_BARE_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _toml_key(key: str) -> str:
    if key and all(ch in _BARE_KEY_CHARS for ch in key):
        return key
    return _toml_string(key)


def _to_toml(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for plan in payload.get("plans", []):
        lines.append("[[plans]]")
        nested: dict[str, dict[str, Any]] = {}
        for k, v in plan.items():
            if isinstance(v, dict):
                nested[k] = v
            else:
                lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        for nk, nested_dict in nested.items():
            lines.append(f"\n[plans.{_toml_key(nk)}]")
            for k, v in nested_dict.items():
                lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        lines.append("")
    for profile in payload.get("profiles", []):
        lines.append("[[profiles]]")
        for k, v in profile.items():
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        lines.append("")
    for section in ("routing", "pinned_active", "auth_order"):
        entries = payload.get(section) or {}
        if entries:
            lines.append(f"\n[{section}]")
            for key, value in entries.items():
                lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    return "\n".join(lines).rstrip() + "\n"


def load_auth_toml(
    *,
    registry: PlanRegistry | None = None,
    store: ProfileStore | None = None,
    path: Path | None = None,
) -> bool:
    """Validate then reconcile this file's plans, credentials and explicit choices.

    Missing or invalid files leave the live stores unchanged. Deleted entries
    disappear only if this file still owns their current objects; callers with
    borrowed references keep them, and managed/environment objects are retained.
    """
    from core.wiring.container import ensure_profile_store

    registry = registry or get_plan_registry()
    store = ensure_profile_store() if store is None else store
    path = path or auth_toml_path()

    if not path.exists():
        return False
    try:
        path.chmod(0o600)
        with open(path, "rb") as f:
            data = tomllib.load(f)
        plans, profiles, routing, pins, orders = _auth_candidate(data)
        source = str(path.resolve())
        previous_plans = registry.file_plans(source)
        for plan in plans:
            current_plan = registry.get(plan.id)
            if (
                current_plan is not None
                and previous_plans.get(plan.id) is not current_plan
                and current_plan.provider != plan.provider
            ):
                raise ValueError("plan provider conflicts with an existing owner")
        previous = store.file_profiles(source)
        owned: list[AuthProfile] = []
        for profile in profiles:
            current = store.get(profile.name)
            if current is not None:
                if current.provider != profile.provider:
                    raise ValueError("profile provider conflicts with an existing owner")
                if current.managed_by or previous.get(profile.name) is not current:
                    continue
                if _profile_to_dict(current) == _profile_to_dict(profile):
                    profile = current
            owned.append(profile)
    except Exception as exc:
        # Exception strings and raw entries can contain keys supplied by a
        # malformed file. Report the class only; never log credential values.
        log.warning("Auth file rejected: %s (%s)", path, type(exc).__name__)
        return False
    registry.reconcile_auth_file(source, plans, routing)
    store.reconcile_auth_file(source, owned, pins, orders)
    return True


@contextmanager
def auth_file_transaction(
    *,
    registry: PlanRegistry | None = None,
    store: ProfileStore | None = None,
    path: Path | None = None,
) -> Iterator[tuple[PlanRegistry, ProfileStore]]:
    """Change the file-owned auth state, then publish it after the write succeeds.

    The thin CLI, daemon and workers each hold an in-memory copy and write the
    whole file. The block edits a candidate read from the current file under one
    lock, so a stale copy cannot revive removed entries or restore rotated
    tokens. A rejected change or failed write raises and leaves both the file
    and the live stores unchanged. Environment and imported CLI credentials are
    not file-owned and are absent from the candidate. Not reentrant: a nested
    transaction on the same file waits on its own lock.
    """
    from core.wiring.container import ensure_profile_store

    registry = registry or get_plan_registry()
    store = ensure_profile_store() if store is None else store
    path = path or auth_toml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = PlanRegistry(), ProfileStore()
    with open(path.with_name(f".{path.name}.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists() and not load_auth_toml(
            registry=candidate[0], store=candidate[1], path=path
        ):
            raise ValueError(f"{path} is invalid; fix or remove it before changing credentials")
        yield candidate
        save_auth_toml(registry=candidate[0], store=candidate[1], path=path)
        if not load_auth_toml(registry=registry, store=store, path=path):
            raise ValueError(
                f"{path} was saved, but this process kept its previous credentials; "
                "run /login refresh after resolving the conflict"
            )

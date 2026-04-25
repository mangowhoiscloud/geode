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

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from core.gateway.auth.plan_registry import PlanRegistry, get_plan_registry
from core.gateway.auth.plans import Plan, PlanKind, Quota
from core.gateway.auth.profiles import AuthProfile, CredentialType, ProfileStore

log = logging.getLogger(__name__)

DEFAULT_AUTH_TOML = Path.home() / ".geode" / "auth.toml"


def auth_toml_path() -> Path:
    """Resolve auth.toml location, honoring `GEODE_AUTH_TOML` env override."""
    override = os.environ.get("GEODE_AUTH_TOML")
    return Path(override) if override else DEFAULT_AUTH_TOML


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
    from core.runtime_wiring.infra import ensure_profile_store

    registry = registry or get_plan_registry()
    store = store or ensure_profile_store()
    path = path or auth_toml_path()

    payload: dict[str, Any] = {
        "plans": [_plan_to_dict(p) for p in registry.list_all()],
        "profiles": [
            _profile_to_dict(p) for p in store.list_all() if not p.managed_by
        ],
        "routing": registry.all_routing(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    text = _to_toml(payload)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        log.debug("Could not chmod %s to 0600", path)
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
            "{ "
            + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
            + " }"
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
    routing = payload.get("routing") or {}
    if routing:
        lines.append("[routing]")
        for model, plan_ids in routing.items():
            lines.append(f"{_toml_key(model)} = {_toml_value(plan_ids)}")
    return "\n".join(lines).rstrip() + "\n"


def load_auth_toml(
    *,
    registry: PlanRegistry | None = None,
    store: ProfileStore | None = None,
    path: Path | None = None,
) -> bool:
    """Hydrate Plan + Profile singletons from TOML.

    Returns True if the file existed and was parsed. Profiles already in
    the store (e.g. from .env / managed CLIs) are NOT removed.
    """
    from core.runtime_wiring.infra import ensure_profile_store

    registry = registry or get_plan_registry()
    store = store or ensure_profile_store()
    path = path or auth_toml_path()

    if not path.exists():
        return False
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        log.warning("Failed to parse %s: %s", path, exc)
        return False

    for raw in data.get("plans", []):
        try:
            registry.add(_plan_from_dict(raw))
        except Exception:
            log.warning("Skipping malformed plan entry: %r", raw, exc_info=True)
    for raw in data.get("profiles", []):
        try:
            store.add(_profile_from_dict(raw))
        except Exception:
            log.warning("Skipping malformed profile entry: %r", raw, exc_info=True)
    for model, plan_ids in (data.get("routing") or {}).items():
        if isinstance(plan_ids, list):
            registry.set_routing(str(model), [str(pid) for pid in plan_ids])
    return True


def migrate_env_to_toml(
    *,
    registry: PlanRegistry | None = None,
    store: ProfileStore | None = None,
    path: Path | None = None,
) -> int:
    """Snapshot any env-loaded PAYG keys into auth.toml on first run.

    Returns the number of plans persisted. Idempotent — re-running after
    the file exists is a no-op (data is loaded but not duplicated).
    """
    from core.gateway.auth.plans import default_plan_for_payg
    from core.runtime_wiring.infra import ensure_profile_store

    registry = registry or get_plan_registry()
    store = store or ensure_profile_store()
    path = path or auth_toml_path()

    if path.exists():
        # Already migrated. Just hydrate.
        load_auth_toml(registry=registry, store=store, path=path)
        return 0

    from core.config import settings

    seeded = 0
    for provider, key in (
        ("anthropic", settings.anthropic_api_key),
        ("openai", settings.openai_api_key),
        ("glm", settings.zai_api_key),
    ):
        if not key:
            continue
        plan = default_plan_for_payg(provider, key)
        registry.add(plan)
        profile_name = f"{plan.id}:env"
        if profile_name not in store:
            store.add(
                AuthProfile(
                    name=profile_name,
                    provider=provider,
                    credential_type=CredentialType.API_KEY,
                    key=key,
                    plan_id=plan.id,
                )
            )
        seeded += 1
    if seeded:
        save_auth_toml(registry=registry, store=store, path=path)
    return seeded

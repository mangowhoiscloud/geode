"""Per-user Petri override store — read/write ``~/.geode/petri.toml``.

Lets the user pin a model / source per role without touching the
manifest (which ships with the codebase). The ``/petri`` command
writes here; :func:`plugins.petri_audit.registry.get_binding` reads
through this layer before falling back to the manifest defaults.

Schema (TOML)::

    [petri.auditor]
    model = "claude-opus-4-7"
    source = "claude-cli"

    [petri.target]
    model = "gpt-5.4-mini"
    # source absent → auto

    [petri.judge]
    model = "claude-sonnet-4-6"
    source = "api_key"

Both keys are optional per role. A missing role → no overrides
(manifest default wins). A missing field → that axis stays default.

The store is intentionally **side-effect-light** — read/write are
synchronous, no schema migration, no caching beyond the OS page cache.
This is fine for a CLI-only path that fires on user keystroke.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_PETRI_TOML

__all__ = [
    "RoleOverride",
    "clear_overrides",
    "load_user_overrides",
    "read_role_override",
    "save_role_override",
]


# Lightweight typed-dict-style alias; keep as plain dict[str, str] for
# write-side simplicity. The two keys are 'model' and 'source'; either
# may be absent.
RoleOverride = dict[str, str]


def _resolve_path(path: Path | str | None) -> Path:
    """Resolve the petri.toml path, honouring ``GEODE_PETRI_TOML`` env override.

    Order: explicit ``path`` argument → ``GEODE_PETRI_TOML`` env → default
    :data:`core.paths.GLOBAL_PETRI_TOML`. Matches the pattern used by
    :mod:`core.auth.auth_toml`.
    """
    if path is not None:
        return Path(path)
    env = os.environ.get("GEODE_PETRI_TOML")
    if env:
        return Path(env)
    return GLOBAL_PETRI_TOML


def load_user_overrides(path: Path | str | None = None) -> dict[str, RoleOverride]:
    """Return ``{role: {model?: str, source?: str}}`` from petri.toml.

    Missing file → empty dict. Malformed TOML / non-table sections →
    skipped silently (CLI keystroke path must be robust; manifest path
    is the authoritative SOT). Unknown roles and unknown axis keys are
    preserved so future schema additions don't drop user data.
    """
    target = _resolve_path(path)
    if not target.exists():
        return {}
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    petri = data.get("petri")
    if not isinstance(petri, dict):
        return {}
    out: dict[str, RoleOverride] = {}
    for role_name, role_data in petri.items():
        if not isinstance(role_data, dict):
            continue
        cleaned: RoleOverride = {}
        for key in ("model", "source"):
            value = role_data.get(key)
            if isinstance(value, str) and value:
                cleaned[key] = value
        if cleaned:
            out[role_name] = cleaned
    return out


def read_role_override(role: str, *, path: Path | str | None = None) -> RoleOverride:
    """Return the override dict for a single role (empty if unset)."""
    return load_user_overrides(path).get(role, {})


def save_role_override(
    role: str,
    *,
    model: str | None = None,
    source: str | None = None,
    path: Path | str | None = None,
) -> None:
    """Persist a role override to petri.toml.

    ``model`` / ``source`` semantics:

    - ``None`` (default) → keep the existing value for that axis.
    - ``""`` (empty string) → delete that axis from the role (so the
      manifest default takes over).
    - non-empty string → write the value.

    The function is additive — other roles are preserved verbatim. Atomic
    write via a temp-file rename so a crashed editor never leaves a
    partial petri.toml on disk.
    """
    target = _resolve_path(path)
    existing = load_user_overrides(target)
    role_dict = dict(existing.get(role, {}))

    if model is not None:
        if model == "":
            role_dict.pop("model", None)
        else:
            role_dict["model"] = model
    if source is not None:
        if source == "":
            role_dict.pop("source", None)
        else:
            role_dict["source"] = source

    if role_dict:
        existing[role] = role_dict
    else:
        existing.pop(role, None)

    _atomic_write_toml(target, existing)


def clear_overrides(role: str | None = None, *, path: Path | str | None = None) -> None:
    """Drop overrides — for a single role or for every role.

    ``role=None`` (default) wipes the whole ``[petri.*]`` tree but leaves
    other top-level sections in the file untouched (forward-compat —
    petri.toml is currently single-section but the writer treats it as
    additive).
    """
    target = _resolve_path(path)
    existing = load_user_overrides(target)
    if role is None:
        existing.clear()
    else:
        existing.pop(role, None)
    _atomic_write_toml(target, existing)


def _atomic_write_toml(target: Path, overrides: dict[str, RoleOverride]) -> None:
    """Write the overrides dict to ``target`` atomically.

    Format — one ``[petri.<role>]`` block per role with stable key
    order (model first, source second). No tomli-w dependency; we hand-
    serialise because the surface is tiny + we want exact diffability.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overrides:
        # Empty state — keep the file as a tombstone so future writes
        # don't surprise the user, but the body is just a header comment.
        body = (
            "# Petri per-user role × model × source overrides.\n"
            "# Edited by `/petri` slash command — read by\n"
            "# plugins.petri_audit.user_overrides.load_user_overrides.\n"
        )
    else:
        lines: list[str] = [
            "# Petri per-user role × model × source overrides.\n"
            "# Edited by `/petri` slash command — read by\n"
            "# plugins.petri_audit.user_overrides.load_user_overrides.\n",
        ]
        for role_name in sorted(overrides):
            role_data = overrides[role_name]
            lines.append(f"\n[petri.{role_name}]\n")
            for key in ("model", "source"):
                if key in role_data:
                    value = role_data[key].replace('"', '\\"')
                    lines.append(f'{key} = "{value}"\n')
        body = "".join(lines)

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(target)


def _coerce(role_data: Any) -> RoleOverride:
    """Defensive coercion used by tests + external callers."""
    if not isinstance(role_data, dict):
        return {}
    out: RoleOverride = {}
    for key in ("model", "source"):
        value = role_data.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out

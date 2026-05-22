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

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_PETRI_TOML

log = logging.getLogger(__name__)


def _emit_user_overrides_event(
    event: str,
    *,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a user-overrides event into the active SessionJournal.

    P1b — closes the silent legacy-petri.toml fallback gap from the
    2026-05-19 observability audit §5. Discovered via the ContextVar
    so callers outside a self-improving-loop run (single-shot CLI
    invocations) are no-ops. Failure to emit must not break the
    override resolver — exception swallowed.
    """
    try:
        from core.observability import current_session_journal

        journal = current_session_journal()
        if journal is None:
            return
        journal.append(event, level=level, payload=payload or {})
    except Exception:  # pragma: no cover - defensive
        log.debug("user_overrides: journal emit %s failed", event, exc_info=True)


__all__ = [
    "RoleOverride",
    "clear_overrides",
    "load_user_overrides",
    "migration_plan_from_petri_toml",
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
    """Return the override dict for a single role (empty if unset).

    PR-δ2 (2026-05-19) — precedence:
      1. ``[self_improving_loop.petri.<role>]`` section in ``~/.geode/config.toml``
         (PR-α1 single SoT).
      2. Legacy ``[petri.<role>]`` in ``~/.geode/petri.toml`` (only
         honoured when ``path`` is the default; explicit path arg
         always reads the legacy file as before so callers that
         deliberately load a snapshot keep working).

    The legacy fallback is retained for one release so existing users
    are not stranded; the migration helper
    (``migration_plan_from_petri_toml``) prints the diff and the
    follow-up PR-ε1 wires it into ``geode config migrate-petri-toml``.
    """
    if path is None:
        outer_override = _read_role_from_self_improving_loop(role)
        if outer_override:
            return outer_override
    return load_user_overrides(path).get(role, {})


def _read_role_from_self_improving_loop(role: str) -> RoleOverride:
    """Pull ``[self_improving_loop.petri.<role>]`` into the legacy RoleOverride shape.

    Returns an empty dict when the section is absent (no role configured)
    or the loader is unavailable (test contexts that stub
    ``core.config``).

    Strict-mode validation errors (``ValueError`` raised by
    :func:`core.config.self_improving_loop.load_self_improving_loop_config`) are
    intentionally *not* caught — they propagate so an operator who
    typos a key sees the failure rather than silently keeps reading
    the legacy ``petri.toml``. ``ImportError`` is the only exception
    swallowed so this module stays importable in environments that
    stub out ``core.config``.
    """
    try:
        from core.config.self_improving_loop import load_self_improving_loop_config
    except ImportError:
        # P1b — emit so the operator can see that the run silently fell
        # back to the legacy petri.toml instead of consulting the new
        # [self_improving_loop.petri.<role>] config section. No-op when
        # no journal is in scope.
        _emit_user_overrides_event(
            "petri_role_legacy_fallback",
            payload={"role": role, "reason": "import_error"},
        )
        return {}
    cfg = load_self_improving_loop_config()
    entry = cfg.petri.get(role)
    if entry is None:
        return {}
    out: RoleOverride = {}
    if entry.model:
        out["model"] = entry.model
    if entry.source and entry.source != "auto":
        out["source"] = entry.source
    return out


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

    SoT-flip (2026-05-22) — the operator-facing SoT for ``model`` /
    ``source`` per role is now
    ``[self_improving_loop.petri.<role>]`` in ``~/.geode/config.toml``.
    The ``/petri`` slash command uses
    :func:`save_role_override_to_config_toml` for that path; this
    function survives as the legacy ``~/.geode/petri.toml`` writer for
    fixtures + back-compat probes that explicitly target petri.toml.
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


def save_role_override_to_config_toml(
    role: str,
    *,
    model: str | None = None,
    source: str | None = None,
) -> None:
    """Persist a role override to ``~/.geode/config.toml`` under
    ``[self_improving_loop.petri.<role>]`` — the operator-config SoT.

    Closes the read/write asymmetry that made ``/petri model <role> X``
    a silent no-op when the operator had already pinned a value in
    ``config.toml``: the new-section value won the read precedence
    (per :func:`read_role_override`) while the slash command wrote the
    legacy file, so the operator's intent never reached the audit.

    Axis-split routing — non-empty model / source writes go to
    config.toml via ``_persist_section_updates``; empty-string
    (delete-axis) requests fall back to the legacy
    ``save_role_override`` write path **for that single axis only**.
    This protects the common ``/petri model <role> X`` flow when a
    provider switch also sets ``source=""`` (cli.py:128-133): the
    model lands in config.toml as the SoT, the source clear lands on
    the legacy file's ``[petri.<role>]`` block. Without the split the
    entire write fell back to legacy and the model update was lost to
    the read-precedence (config.toml's stale value still won).

    The legacy file is read as a fallback layer by
    :func:`read_role_override`, so the source-clear actually flows
    through to subsequent binding resolution — but ONLY because the
    config.toml side stopped pinning the source (it's a fresh write
    target, no pre-existing key).
    """
    config_updates: dict[str, str] = {}
    legacy_axes: dict[str, str] = {}

    if model is not None:
        if model == "":
            legacy_axes["model"] = ""
        else:
            config_updates["model"] = model
    if source is not None:
        if source == "":
            legacy_axes["source"] = ""
        else:
            config_updates["source"] = source

    if config_updates:
        from core.cli.commands.self_improving import _persist_section_updates

        _persist_section_updates(f"self_improving_loop.petri.{role}", config_updates)

    if legacy_axes:
        # Empty-string clears the axis in petri.toml. The legacy file's
        # value is read AFTER config.toml on the read precedence, so a
        # legacy clear only takes effect when the operator's config.toml
        # also lacks the corresponding key — which is typical because
        # this code is the only writer that pins ``source`` into
        # ``[self_improving_loop.petri.<role>]`` and we only do that
        # when ``source`` is explicitly non-empty.
        save_role_override(
            role,
            model=legacy_axes.get("model"),
            source=legacy_axes.get("source"),
            path=GLOBAL_PETRI_TOML,
        )


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


# ---------------------------------------------------------------------------
# Migration helper (PR-δ2 — 2026-05-19)
# ---------------------------------------------------------------------------


def migration_plan_from_petri_toml(
    *, petri_toml_path: Path | str | None = None
) -> dict[str, RoleOverride]:
    """Return the ``{role: override}`` map currently living in petri.toml.

    Used by ``geode config migrate-petri-toml`` (landing in PR-ε1) to
    show the operator a dry-run diff before copying the entries to
    ``~/.geode/config.toml`` ``[self_improving_loop.petri.*]``. This function
    *reads only* — it does not mutate either file. Empty dict when the
    legacy file is absent or has no per-role overrides.
    """
    return load_user_overrides(petri_toml_path)

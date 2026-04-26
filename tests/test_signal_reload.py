"""Bug class B7 — state propagation invariants for thin → daemon auth writes.

When a THIN slash command (``/login``, ``/key``, ``/auth``) writes to
``~/.geode/auth.toml`` from the CLI process, the daemon's in-memory
``ProfileStore`` / ``PlanRegistry`` singletons stay stale until the daemon
re-reads the file. v0.52 phase 3 wires this via a ``client.send_command(
"/login", "refresh")`` signal sent immediately after every THIN auth command,
which the daemon handles by calling ``load_auth_toml()``.

This file pins both halves of the contract so a future refactor of either
the CLI dispatch loop or the ``cmd_login("refresh")`` handler cannot silently
re-introduce the stale-state bug.

Contracts:
  1. CLI dispatch loop (``core/cli/__init__.py``) MUST call ``send_command(
     "/login", "refresh")`` after THIN execution of ``/login``, ``/key``,
     ``/auth``.
  2. ``cmd_login("refresh")`` MUST invoke ``load_auth_toml()`` and the merge
     MUST be additive — newly written plans/profiles appear in the singleton
     while in-memory entries that don't appear in auth.toml (e.g. Codex CLI
     OAuth, .env-seeded profiles) are NOT evicted.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import core.cli as _cli_pkg
import pytest
from core.auth.auth_toml import save_auth_toml
from core.auth.plan_registry import get_plan_registry
from core.auth.plans import Plan, PlanKind
from core.auth.profiles import AuthProfile, CredentialType
from core.cli.commands import cmd_login
from core.lifecycle.container import ensure_profile_store

# ---------------------------------------------------------------------------
# Contract 1 — CLI dispatch sends refresh signal after THIN auth commands
# ---------------------------------------------------------------------------


def test_cli_thin_dispatch_signals_daemon_refresh() -> None:
    """Source-level invariant: THIN auth commands must trigger /login refresh.

    We inspect the dispatch block in ``core/cli/__init__.py`` rather than
    spinning up a real IPC socket — the goal is to catch a future refactor
    that moves the dispatch but forgets to copy the refresh signal.
    """
    src = inspect.getsource(_cli_pkg)
    # The exact relay call. If this string disappears, B7 regresses.
    assert 'client.send_command("/login", "refresh")' in src, (
        "Thin dispatch must relay /login refresh to daemon after THIN auth "
        "commands write to auth.toml. See core/cli/__init__.py THIN branch."
    )
    # And it must be gated by the auth-writing command set.
    assert '("/login", "/key", "/auth")' in src, (
        "Refresh signal must fire only for THIN commands that mutate "
        "auth.toml — gating set ('/login', '/key', '/auth') missing."
    )


# ---------------------------------------------------------------------------
# Contract 2 — cmd_login("refresh") reloads auth.toml into singletons
# ---------------------------------------------------------------------------


def _seed_auth_toml_with_plan(plan_id: str) -> Plan:
    """Helper: write a single Plan to auth.toml and return it."""
    registry = get_plan_registry()
    store = ensure_profile_store()
    plan = Plan(
        id=plan_id,
        provider="openai",
        kind=PlanKind.PAYG,
        display_name=f"Test {plan_id}",
        base_url="https://api.openai.com/v1",
    )
    registry.add(plan)
    store.add(
        AuthProfile(
            name=f"openai:{plan_id}",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            key="sk-test-" + ("x" * 20),
            plan_id=plan_id,
        )
    )
    save_auth_toml()
    return plan


def test_cmd_login_refresh_reloads_auth_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daemon-side: cmd_login("refresh") picks up a plan written out-of-band.

    Simulates the v0.52 phase-3 flow: thin CLI completes /login oauth in its
    own process (writes auth.toml), then relays /login refresh to the daemon
    so its singletons see the new plan.
    """
    # Step 1 — pretend the thin CLI wrote a Plan to auth.toml. monkeypatch
    # restores GEODE_AUTH_TOML at teardown so the file (which conftest's
    # cleanup hook does not know about) cannot leak into the next test.
    auth_path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_path))
    _seed_auth_toml_with_plan("plan-from-thin")

    # Step 2 — daemon-side singletons start fresh (mimic restart)
    from core.auth import plan_registry as _pr
    from core.lifecycle import container as _infra

    _infra._profile_store = None
    _pr._plan_registry = None

    assert get_plan_registry().get("plan-from-thin") is None, (
        "precondition: fresh daemon singleton has no knowledge of the plan"
    )

    # Step 3 — daemon receives /login refresh and reloads
    cmd_login("refresh")

    # Step 4 — singleton now contains the plan
    assert get_plan_registry().get("plan-from-thin") is not None, (
        "cmd_login('refresh') must call load_auth_toml() so daemon "
        "singletons pick up plans written by the thin CLI"
    )


def test_cmd_login_refresh_is_additive_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh MUST NOT evict in-memory profiles missing from auth.toml.

    This protects Codex CLI OAuth + .env-seeded profiles, which are loaded
    once at boot and never written to auth.toml. A naive 'rebuild from disk'
    refresh would silently delete them — exactly the v0.51 stale-state bug
    in reverse.
    """
    auth_path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_path))

    store = ensure_profile_store()
    # Simulate a Codex CLI OAuth profile loaded at boot — managed_by means
    # save_auth_toml() will skip it, so it never appears on disk.
    store.add(
        AuthProfile(
            name="openai:codex-cli",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="oauth-token-xyz",
            managed_by="codex-cli",
        )
    )
    # And a separate plan-backed profile that DOES go to disk.
    _seed_auth_toml_with_plan("plan-on-disk")

    assert any(p.name == "openai:codex-cli" for p in store.list_all())
    assert any(p.name == "openai:plan-on-disk" for p in store.list_all())

    # Trigger the daemon reload path.
    cmd_login("refresh")

    names = {p.name for p in ensure_profile_store().list_all()}
    assert "openai:codex-cli" in names, (
        "Additive-only invariant: managed-by-CLI profile (not in auth.toml) "
        "must survive a /login refresh — see commands.py refresh docstring"
    )
    assert "openai:plan-on-disk" in names, (
        "Refresh must still re-merge profiles that ARE in auth.toml"
    )


def test_cmd_login_refresh_swallows_missing_auth_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh on a fresh install (no auth.toml yet) must not raise.

    Important because the dispatch loop in core/cli/__init__.py wraps the
    relay in ``contextlib.suppress(Exception)`` precisely because a daemon
    that throws here would tank the user's slash command.
    """
    auth_path = tmp_path / "does-not-exist.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_path))
    assert not auth_path.exists()
    # Must not raise.
    cmd_login("refresh")


def test_cmd_login_refresh_emits_observability_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """B2 v0.52.2 — refresh must emit an INFO log on success.

    Pre-fix the success path was completely silent. Production
    observability black hole — no way to verify the thin → daemon refresh
    signal was firing in the field.
    """
    import logging

    auth_path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_path))
    _seed_auth_toml_with_plan("plan-observability")

    # Reset singletons so the reload actually merges new entries.
    from core.auth import plan_registry as _pr
    from core.lifecycle import container as _infra

    _infra._profile_store = None
    _pr._plan_registry = None

    with caplog.at_level(logging.INFO, logger="core.cli.commands"):
        cmd_login("refresh")

    messages = [rec.message for rec in caplog.records]
    assert any("auth.toml reload" in m for m in messages), (
        "cmd_login('refresh') must emit an INFO log on success — pre-v0.52.2 "
        "this branch was silent and B7 fires were undetectable in production"
    )
    # The summary line must include count fields so SREs can see at a glance
    # whether a refresh was a no-op vs. actually merged something.
    summary = next(m for m in messages if "auth.toml reload" in m and "loaded=" in m)
    assert "total_plans=" in summary
    assert "total_profiles=" in summary
    assert "new_plans=" in summary
    assert "new_profiles=" in summary

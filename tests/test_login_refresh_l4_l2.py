"""L2 + L4 — /login refresh console output + /key migration guide.

L2 — pre-fix ``/login refresh`` only emitted ``log.info`` records, so
the operator running the command from the REPL saw nothing on stdout
and could not tell whether the daemon had picked up the new plan or
profile. The success branch now surfaces a ``+N plan / +M profile``
summary alongside the failure / no-change paths.

L4 — pre-fix ``/key`` (no args) printed a single muted line and
redirected to ``/login``. The migration table is now inline so the
legacy command becomes self-documenting (operator learns the new
surface without grepping the changelog).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# L2 — /login refresh console output
# ---------------------------------------------------------------------------


def _patch_refresh_path(
    *,
    ok: bool,
    new_plans: set[str],
    new_profiles: set[str],
) -> tuple[object, ...]:
    """Build the three patches the refresh branch needs."""
    plan_store = MagicMock()
    plan_store.list_all.return_value = [
        type("P", (), {"id": p})() for p in (new_plans | {"existing-plan"})
    ]
    profile_store = MagicMock()
    profile_store.list_all.return_value = [
        type("PR", (), {"name": n})() for n in (new_profiles | {"existing:env"})
    ]

    # Two `list_all` calls — before vs after `load_auth_toml`. Pre-call
    # returns just the existing entries; post-call returns existing +
    # new.
    plan_calls = [
        [type("P", (), {"id": "existing-plan"})()],
        [type("P", (), {"id": p})() for p in ({"existing-plan"} | new_plans)],
    ]
    profile_calls = [
        [type("PR", (), {"name": "existing:env"})()],
        [type("PR", (), {"name": n})() for n in ({"existing:env"} | new_profiles)],
    ]
    plan_store.list_all.side_effect = plan_calls
    profile_store.list_all.side_effect = profile_calls

    return (
        patch("core.llm.routing.plan_registry.get_plan_registry", return_value=plan_store),
        patch("core.wiring.container.ensure_profile_store", return_value=profile_store),
        patch("core.auth.auth_toml.load_auth_toml", return_value=ok),
        patch("core.auth.auth_toml.auth_toml_path", return_value="/tmp/auth.toml"),  # noqa: S108
    )


def test_login_refresh_success_with_new_plans(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import cmd_login

    patches = _patch_refresh_path(ok=True, new_plans={"glm-coding-lite"}, new_profiles=set())
    with patches[0], patches[1], patches[2], patches[3]:
        cmd_login("refresh")

    out = capsys.readouterr().out
    assert "auth.toml reloaded" in out
    assert "+1 plan" in out
    assert "glm-coding-lite" in out


def test_login_refresh_no_changes_shows_muted(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import cmd_login

    patches = _patch_refresh_path(ok=True, new_plans=set(), new_profiles=set())
    with patches[0], patches[1], patches[2], patches[3]:
        cmd_login("refresh")

    out = capsys.readouterr().out
    assert "no new plans or profiles" in out


def test_login_refresh_failure_warns(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.login import cmd_login

    patches = _patch_refresh_path(ok=False, new_plans=set(), new_profiles=set())
    with patches[0], patches[1], patches[2], patches[3]:
        cmd_login("refresh")

    out = capsys.readouterr().out
    assert "auth.toml reload failed" in out


# ---------------------------------------------------------------------------
# L4 — /key (no args) carries migration guide
# ---------------------------------------------------------------------------


def test_cmd_key_noargs_prints_migration_guide(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.key import cmd_key

    with patch("core.cli.commands.cmd_login") as fake_login:
        cmd_key("")
        fake_login.assert_called_once_with("")

    out = capsys.readouterr().out
    assert "Migration guide" in out
    assert "/login add" in out
    assert "/login set-key" in out

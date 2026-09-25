"""Thin auth commands run terminal input locally and daemon state remotely.

Terminal-bound ``/login`` subcommands and ``/key`` run in the thin client and
then relay ``/login refresh``; every other ``/login`` request runs in the
daemon, which owns the live credential state. Model selection keeps the IPC
client attached to its session admission path. Daemon reload reconciles
file-owned auth entries while preserving profiles supplied by other owners,
such as Codex CLI OAuth.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, call

import pytest
from core.auth.auth_toml import save_auth_toml
from core.auth.profiles import AuthProfile, CredentialType
from core.cli.commands import cmd_login
from core.cli.ipc_client import IPCClient
from core.cli.routing import run_thin_command
from core.llm.strategies.plan_registry import get_plan_registry
from core.llm.strategies.plans import Plan, PlanKind
from core.wiring.container import ensure_profile_store

# ---------------------------------------------------------------------------
# Contract 1 — CLI dispatch sends refresh signal after THIN auth commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cmd", "args", "local_target"),
    [
        ("/login", "openai", "core.cli.commands.login.cmd_login"),
        ("/key", "status", "core.cli.dispatcher._handle_command"),
    ],
)
def test_cli_thin_dispatch_signals_daemon_refresh(
    cmd: str, args: str, local_target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute the routing owner; local handling precedes the refresh signal."""
    from core.ui.console import console

    calls = Mock()
    calls.local.return_value = True
    monkeypatch.setattr(local_target, calls.local)
    client = Mock(spec=IPCClient)
    calls.attach_mock(client.send_command, "relay")
    client.send_command.return_value = {"status": "error", "message": "refresh rejected"}

    with console.capture() as output:
        run_thin_command(client, cmd, args)

    local = (
        call.local(args) if cmd == "/login" else call.local(cmd, args, False, command_registry=None)
    )
    assert calls.mock_calls == [local, call.relay("/login", "refresh")]
    assert "daemon refresh failed" in output.get()
    assert "refresh rejected" in output.get()


def test_cli_thin_failed_local_login_does_not_signal_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.cli.commands.login.cmd_login", Mock(return_value=False))
    client = Mock(spec=IPCClient)

    run_thin_command(client, "/login", "set-key ghost sk-test")

    client.send_command.assert_not_called()


@pytest.mark.parametrize("args", ["", "remove glm-payg", "use-profile openai:work", "refresh"])
def test_cli_thin_daemon_owned_login_relays_without_local_state(
    args: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Views and nonsecret changes read or change the daemon's live state."""
    from core.ui.console import console

    local = Mock(side_effect=AssertionError("thin state must not answer this request"))
    monkeypatch.setattr("core.cli.commands.login.cmd_login", local)
    monkeypatch.setattr("core.cli.dispatcher._handle_command", local)
    client = Mock(spec=IPCClient)
    client.send_command.return_value = {
        "status": "error",
        "message": "Plan not found: glm-payg",
        "output": "",
    }

    with console.capture() as output:
        run_thin_command(client, "/login", args)

    client.send_command.assert_called_once_with("/login", args)
    assert "Plan not found: glm-payg" in output.get()


def test_cli_thin_readopts_the_file_after_a_daemon_change(monkeypatch: pytest.MonkeyPatch) -> None:
    reload = Mock(return_value=True)
    monkeypatch.setattr("core.auth.auth_toml.load_auth_toml", reload)
    client = Mock(spec=IPCClient)
    client.send_command.return_value = {"status": "ok", "output": ""}

    run_thin_command(client, "/login", "route gpt-6-sol openai-payg")

    reload.assert_called_once_with()


def test_cli_thin_keeps_unrecognized_login_input_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pasted key after /login must not cross IPC or be echoed by the daemon."""
    local = Mock(return_value=False)
    monkeypatch.setattr("core.cli.commands.login.cmd_login", local)
    client = Mock(spec=IPCClient)

    run_thin_command(client, "/login", "sk-pasted-secret-value")

    local.assert_called_once_with("sk-pasted-secret-value")
    client.send_command.assert_not_called()


def test_cli_thin_reports_lost_daemon_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.ui.console import console

    client = Mock(spec=IPCClient)
    client.send_command.return_value = {"type": "error", "message": "Connection lost"}

    with console.capture() as output:
        run_thin_command(client, "/login", "")

    assert "Connection lost" in output.get()


def test_cli_thin_non_auth_command_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = Mock()
    monkeypatch.setattr("core.cli.dispatcher._handle_command", local)
    client = Mock(spec=IPCClient)

    run_thin_command(client, "/skills", "")

    local.assert_called_once_with("/skills", "", False, command_registry=None)
    client.send_command.assert_not_called()


def test_cli_thin_model_keeps_session_client_and_propagates_admission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = Mock()
    model = Mock(side_effect=RuntimeError("session admission rejected"))
    monkeypatch.setattr("core.cli.dispatcher._handle_command", local)
    monkeypatch.setattr("core.cli.commands.model.cmd_model", model)
    client = Mock(spec=IPCClient)

    with pytest.raises(RuntimeError, match="session admission rejected"):
        run_thin_command(client, "/model", "gpt-6-sol low")

    model.assert_called_once_with("gpt-6-sol low", client=client)
    local.assert_not_called()
    client.send_command.assert_not_called()


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

    Simulates the v0.52 phase-3 flow: thin CLI completes /login openai in its
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
    from core.llm.strategies import plan_registry as _pr
    from core.wiring import container as _infra

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


def test_cmd_login_refresh_keeps_profiles_the_file_does_not_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh replaces file-owned entries and keeps profiles owned elsewhere.

    Codex CLI OAuth and environment profiles are loaded at boot and never
    written to auth.toml. A 'rebuild from disk' refresh would silently delete
    them — the v0.51 stale-state bug in reverse.
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
        "A profile auth.toml does not own must survive a /login refresh"
    )
    assert "openai:plan-on-disk" in names, (
        "Refresh must still re-merge profiles that ARE in auth.toml"
    )


def test_cmd_login_refresh_without_auth_toml_still_resets_imported_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no file there is nothing to adopt; imported credential caches still reset."""
    auth_path = tmp_path / "does-not-exist.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_path))
    codex, google = Mock(), Mock()
    monkeypatch.setattr("core.auth.codex_cli_oauth.invalidate_cache", codex)
    monkeypatch.setattr("core.mcp.google_workspace_client.reset_google_workspace_client", google)

    assert cmd_login("refresh") is True

    codex.assert_called_once_with()
    google.assert_called_once_with()
    assert not auth_path.exists()


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
    from core.llm.strategies import plan_registry as _pr
    from core.wiring import container as _infra

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
    summary = next(m for m in messages if "auth.toml reload" in m and "plans=" in m)
    assert "profiles=" in summary
    assert "changes=" in summary

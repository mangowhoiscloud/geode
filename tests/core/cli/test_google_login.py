"""User-facing /login google command tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from core.auth.google_oauth import GoogleAccount
from core.cli.commands import cmd_login
from core.cli.commands.google_login import run_login_google


def _account() -> GoogleAccount:
    return GoogleAccount(
        account_id="account-1",
        email="user@example.com",
        display_name="User",
        client_id="client.apps.googleusercontent.com",
        project_id="project",
        services=("calendar-write", "gmail-send"),
        granted_scopes=("openid",),
        secret_ref="account:account-1",
        status="connected",
        created_at="2026-07-16T00:00:00Z",
        updated_at="2026-07-16T00:00:00Z",
    )


def test_login_router_dispatches_google_branch() -> None:
    with patch("core.cli.commands.google_login.run_login_google") as google:
        cmd_login("google status")
    google.assert_called_once_with("status")


def test_connect_parses_client_and_service_bundles(tmp_path: Path) -> None:
    client_json = tmp_path / "client.json"
    store = MagicMock()
    store.get_active.return_value = None
    store.path = tmp_path / "accounts.json"
    with (
        patch("core.cli.commands.google_login.GoogleAccountStore", return_value=store),
        patch("core.cli.commands.google_login.login_google", return_value=_account()) as login,
        patch("core.cli.commands.console"),
    ):
        run_login_google(
            f"--client-json {client_json} --services gmail-send,calendar-write --replace-services"
        )
    assert login.call_args.kwargs["client_json"] == client_json
    assert login.call_args.kwargs["services"] == ("calendar-write", "gmail-send")
    assert login.call_args.kwargs["replace_services"] is True
    assert login.call_args.kwargs["new_account"] is False


def test_connect_displays_effective_union_for_active_account(tmp_path: Path) -> None:
    store = MagicMock()
    store.get_active.return_value = _account()
    store.path = tmp_path / "accounts.json"
    with (
        patch("core.cli.commands.google_login.GoogleAccountStore", return_value=store),
        patch("core.cli.commands.google_login.login_google", return_value=_account()) as login,
        patch("core.cli.commands.console") as console,
    ):
        run_login_google("--services workspace-files")

    rendered = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "calendar-write, gmail-send, workspace-files" in rendered
    assert login.call_args.kwargs["new_account"] is False


def test_new_account_does_not_inherit_active_services(tmp_path: Path) -> None:
    store = MagicMock()
    store.get_active.return_value = _account()
    store.path = tmp_path / "accounts.json"
    with (
        patch("core.cli.commands.google_login.GoogleAccountStore", return_value=store),
        patch("core.cli.commands.google_login.login_google", return_value=_account()) as login,
        patch("core.cli.commands.console") as console,
    ):
        run_login_google("--new-account --services workspace-files")

    rendered = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "Service bundles: workspace-files" in rendered
    assert "calendar-write, gmail-send, workspace-files" not in rendered
    assert login.call_args.kwargs["new_account"] is True


def test_status_never_loads_secret_store() -> None:
    rows = [
        {
            "account_id": "account-1",
            "email": "user@example.com",
            "display_name": "User",
            "active": True,
            "status": "connected",
            "services": ["gmail-send"],
            "granted_scopes": ["openid"],
            "updated_at": "2026-07-16T00:00:00Z",
            "last_refresh_at": "",
        }
    ]
    with (
        patch("core.cli.commands.google_login.google_account_status", return_value=rows),
        patch("core.cli.commands.console") as console,
    ):
        run_login_google("status")
    rendered = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "user@example.com" in rendered
    assert "gmail-send" in rendered


def test_services_lists_risk_classification() -> None:
    with patch("core.cli.commands.console") as console:
        run_login_google("services")
    rendered = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "gmail-read" in rendered
    assert "restricted" in rendered
    assert "workspace-files" in rendered


def test_google_invalid_arguments_fail_without_echoing_secret() -> None:
    import pytest
    from core.cli.commands.login import run_login
    from core.ui.console import capture_output
    from rich.text import Text

    secret = "sk-" + "synthetic1234567890" * 2
    with patch("core.cli.commands.google_login.login_google") as login:
        with pytest.raises(ValueError, match="Unknown option"):
            run_login(f"google {secret}")
        with capture_output() as output:
            assert cmd_login(f"google {secret}") is False
        login.assert_not_called()
    assert secret not in output.getvalue()
    assert "[REDACTED]" in Text.from_ansi(output.getvalue()).plain


def test_google_failures_propagate_from_every_action() -> None:
    import pytest
    from core.auth.google_oauth import GoogleOAuthError
    from core.cli.commands.login import run_login
    from core.ui.console import capture_output

    store = MagicMock()
    store.get_active.return_value = _account()
    failure = GoogleOAuthError("controlled failure")
    with (
        patch("core.cli.commands.google_login.GoogleAccountStore", return_value=store),
        patch("core.cli.commands.google_login.login_google", side_effect=failure),
        patch("core.cli.commands.google_login.revoke_google_account", side_effect=failure),
        patch("core.cli.commands.google_login.google_account_status", side_effect=failure),
        patch("core.mcp.google_workspace_client.reset_google_workspace_client") as reset,
    ):
        store.set_active.side_effect = failure
        for args in (
            "google --services workspace-files",
            "google use user@example.com",
            "google logout user@example.com",
            "google status",
            "status google",
        ):
            with pytest.raises(ValueError, match="controlled failure"):
                run_login(args)
            with capture_output() as output:
                assert cmd_login(args) is False
            assert "controlled failure" in output.getvalue()
        reset.assert_not_called()


def test_google_user_cancel_does_not_call_backend_or_report_success(tmp_path) -> None:
    from core.ui.console import capture_output

    store = MagicMock()
    store.get_active.return_value = None
    with (
        patch("core.cli.commands.google_login.GoogleAccountStore", return_value=store),
        patch("core.cli.commands.google_login.login_google") as login,
        patch("core.mcp.google_workspace_client.reset_google_workspace_client") as reset,
    ):
        for args in ("google", f"google --client-json {tmp_path / 'client.json'}"):
            for cancellation in (EOFError, KeyboardInterrupt):
                with (
                    patch("rich.console.Console.input", side_effect=cancellation),
                    capture_output() as output,
                ):
                    assert cmd_login(args) is False
                assert "cancelled" in output.getvalue()
        login.assert_not_called()
        reset.assert_not_called()

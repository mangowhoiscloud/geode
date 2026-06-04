"""Registration + smoke tests for the ``geode campaign`` Typer command.

PR-CAMPAIGN-CLI. ``geode campaign`` is a thin forwarder over the argparse
driver in ``core/self_improving/campaign.py`` (it rebuilds the user options as
an argv list and hands them to ``campaign.main``). These tests assert the
command is discoverable and that the flags forward faithfully WITHOUT launching
a real campaign: the delegation test mocks ``campaign.main`` so no audit
subprocess is spawned and no PAYG budget is spent.
"""

from __future__ import annotations

from unittest.mock import patch

import click
import typer
from typer.testing import CliRunner

from core.cli import app


def test_campaign_command_is_registered() -> None:
    # Resolve the underlying click command so the name is the real CLI name
    # (``app.registered_commands`` stores name=None for ``app.command()`` with
    # no explicit name; the name is derived at build time from the function).
    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)
    assert "campaign" in click_app.commands


def test_campaign_help_lists_core_flags() -> None:
    # Assert the flags on the command's declared params, NOT by substring-matching
    # the rendered ``--help`` text: Typer renders help through Rich, whose box
    # wrapping + ANSI styling vary by terminal width / TTY (a narrow, no-TTY CI
    # runner wraps the options panel so a literal "--n" is not a clean substring).
    # The help is generated FROM these params, so introspecting them tests the
    # same intent deterministically.
    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)
    campaign_cmd = click_app.commands["campaign"]
    opt_names = {opt for param in campaign_cmd.params for opt in param.opts}
    for flag in ("--n", "--k", "--arms", "--dry-run"):
        assert flag in opt_names, f"{flag} missing from campaign command params"

    # Smoke: ``--help`` still renders and exits cleanly (format-agnostic).
    result = CliRunner().invoke(app, ["campaign", "--help"])
    assert result.exit_code == 0


def test_campaign_forwards_options_to_campaign_main() -> None:
    with patch("core.self_improving.campaign.main", return_value=0) as mock_main:
        result = CliRunner().invoke(
            app,
            [
                "campaign",
                "--n",
                "2",
                "--k",
                "1",
                "--arms",
                "never,gate",
                "--mc",
                "4",
                "--audit-max-samples",
                "5",
                "--audit-max-connections",
                "6",
                "--dry-run",
            ],
        )

    assert result.exit_code == 0
    mock_main.assert_called_once()
    forwarded = mock_main.call_args.args[0]
    assert forwarded == [
        "--n",
        "2",
        "--k",
        "1",
        "--arms",
        "never,gate",
        "--mc",
        "4",
        "--audit-max-samples",
        "5",
        "--audit-max-connections",
        "6",
        "--dry-run",
    ]


def test_campaign_defaults_forward_without_dry_run() -> None:
    with patch("core.self_improving.campaign.main", return_value=0) as mock_main:
        result = CliRunner().invoke(app, ["campaign"])

    assert result.exit_code == 0
    forwarded = mock_main.call_args.args[0]
    # Defaults mirror campaign.py argparse (--n 10, --k 5, gate LAST); no --dry-run.
    assert forwarded == [
        "--n",
        "10",
        "--k",
        "5",
        "--arms",
        "never,random,gate",
        "--mc",
        "8",
        "--audit-max-samples",
        "3",
        "--audit-max-connections",
        "8",
    ]
    assert "--dry-run" not in forwarded


def test_campaign_propagates_nonzero_exit_code() -> None:
    with patch("core.self_improving.campaign.main", return_value=2):
        result = CliRunner().invoke(app, ["campaign", "--arms", "bogus"])

    assert result.exit_code == 2

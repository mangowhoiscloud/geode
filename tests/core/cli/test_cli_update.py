"""Typer surface tests for ``geode update``."""

from unittest.mock import patch

from core.cli import app
from typer.testing import CliRunner


def test_update_forwards_latest_and_lifecycle_options() -> None:
    with patch(
        "core.cli.commands.lifecycle.do_update",
        return_value=True,
    ) as do_update:
        result = CliRunner().invoke(
            app,
            ["update", "--latest", "--dry-run", "--force", "--no-restart"],
        )

    assert result.exit_code == 0
    do_update.assert_called_once_with(
        dry_run=True,
        force=True,
        restart=False,
        latest=True,
    )


def test_update_exits_nonzero_when_lifecycle_update_fails() -> None:
    with patch(
        "core.cli.commands.lifecycle.do_update",
        return_value=False,
    ):
        result = CliRunner().invoke(app, ["update"])

    assert result.exit_code == 1

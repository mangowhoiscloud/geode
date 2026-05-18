"""CLI version surface tests."""

from __future__ import annotations

from typer.testing import CliRunner

from core import __version__
from core.cli import app


def test_global_version_option() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"GEODE v{__version__}" in result.output

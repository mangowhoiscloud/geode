"""Evaluation CLI ownership checks."""

from pathlib import Path

import pytest
from evals.cli import app
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _isolate_seed_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "evals.seed_generation.picker.GLOBAL_CONFIG_TOML",
        tmp_path / "config.toml",
    )
    monkeypatch.setattr(
        "evals.seed_generation.picker.GLOBAL_SEED_PIPELINE_TOML",
        tmp_path / "seed_generation.toml",
    )


def test_audit_seeds_config_shows_roles(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_seed_config(monkeypatch, tmp_path)
    result = runner.invoke(app, ["audit-seeds", "config"])
    assert result.exit_code == 0, result.output
    for role in (
        "generator",
        "critic",
        "proximity",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ):
        assert role in result.output
    assert "Judge panel voters" in result.output

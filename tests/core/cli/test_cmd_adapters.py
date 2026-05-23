"""``geode adapters`` CLI surface tests — Follow-up D."""

from __future__ import annotations

import pytest
from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _registry_with_builtins():
    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_adapters_list_shows_all_six(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["adapters", "list"])
    assert result.exit_code == 0, result.output
    for adapter_name in (
        "anthropic-payg",
        "anthropic-oauth",
        "claude-cli",
        "openai-payg",
        "codex-oauth",
        "codex-cli",
    ):
        assert adapter_name in result.output


def test_adapters_list_shows_billing_type(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["adapters", "list"])
    assert "api" in result.output
    assert "subscription" in result.output
    assert "subscription_included" in result.output


def test_adapters_detect_model_missing_adapter_exits_1(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["adapters", "detect-model", "no-such-adapter"])
    assert result.exit_code == 1


def test_adapters_detect_model_no_credential_exits_2(runner: CliRunner, monkeypatch) -> None:
    """When a registered adapter has no credentials configured, exit 2."""
    from core.cli import app

    # Force PAYG to report no credential.
    monkeypatch.setattr("core.config.settings.anthropic_api_key", "")
    result = runner.invoke(app, ["adapters", "detect-model", "anthropic-payg"])
    assert result.exit_code == 2
    assert "no credential" in result.output.lower()


def test_audit_seeds_config_shows_role_table(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["audit-seeds", "config"])
    assert result.exit_code == 0, result.output
    # All 7 enabled roles surface
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


def test_audit_seeds_config_shows_judge_voters(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["audit-seeds", "config"])
    assert "Judge panel voters" in result.output

"""``geode adapters`` CLI surface tests — Follow-up D."""

from __future__ import annotations

import pytest
from core.llm.adapters.base import (
    SOURCE_PAYG,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from core.llm.adapters.registry import (
    _reset_for_test,
    bootstrap_builtins,
    register_adapter,
)
from typer.testing import CliRunner


class _MinimalAdapter:
    name = "minimal"
    provider = "test"
    source = SOURCE_PAYG
    billing_type = AdapterBillingType.UNKNOWN

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        return AdapterCallResult(text="", usage=UsageSummary(), stop_reason="end_turn")


@pytest.fixture(autouse=True)
def _registry_with_builtins():
    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_adapters_list_shows_openai_as_payg_and_subscription(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["adapters", "list"])
    assert result.exit_code == 0, result.output
    for adapter_name in (
        "anthropic-payg",
        "openai-payg",
        "openrouter-payg",
        "codex-oauth",
    ):
        assert adapter_name in result.output
    assert "codex-cli" not in result.output
    assert "Registry generation 1: 6 adapter(s)." in result.output


def test_adapters_list_shows_billing_type(runner: CliRunner) -> None:
    from core.cli import app

    result = runner.invoke(app, ["adapters", "list"])
    assert "api" in result.output
    assert "subscription" in result.output


def test_adapters_list_accepts_completion_only_adapter(runner: CliRunner) -> None:
    from core.cli import app

    register_adapter(_MinimalAdapter())
    result = runner.invoke(app, ["adapters", "list"])
    assert result.exit_code == 0, result.output
    assert "minimal" in result.output
    assert "n/a — diagnostics unsupported" in result.output


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


def test_adapters_detect_model_reports_unsupported_capability(runner: CliRunner) -> None:
    from core.cli import app

    register_adapter(_MinimalAdapter())
    result = runner.invoke(app, ["adapters", "detect-model", "minimal"])
    assert result.exit_code == 2
    assert "credential detection not supported" in result.output.lower()

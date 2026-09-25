"""Status observes current credentials independently of CLI startup snapshots."""

from __future__ import annotations

import pytest
from core.cli import session_state
from core.cli.tool_handlers import cli_handler_groups
from core.wiring import startup


@pytest.mark.parametrize("credential", ["api", "subscription", "profile"])
def test_status_tracks_credentials_without_cli_bootstrap(
    credential: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    available = False
    monkeypatch.setattr(session_state, "_get_readiness", lambda: None)
    monkeypatch.setattr(startup, "_has_any_llm_key", lambda: available and credential == "api")
    monkeypatch.setattr(
        startup,
        "detect_subscription_oauth",
        lambda: "openai" if available and credential == "subscription" else None,
    )
    monkeypatch.setattr(
        startup, "_has_available_profile", lambda: available and credential == "profile"
    )
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    status = handlers["check_status"]

    assert status()["mode"] == "dry_run"
    available = True
    assert status()["mode"] == "full_llm"
    available = False
    assert status()["mode"] == "dry_run"


def test_status_reads_explicit_request_policy_after_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = startup.ReadinessReport(force_dry_run=True)
    monkeypatch.setattr(session_state, "_get_readiness", lambda: readiness)
    handlers = dict(next(group for name, group in cli_handler_groups() if name == "system"))
    status = handlers["check_status"]

    assert status()["mode"] == "dry_run"
    readiness = startup.ReadinessReport(force_dry_run=False)
    assert status()["mode"] == "full_llm"
    readiness = startup.ReadinessReport(force_dry_run=True)
    assert status()["mode"] == "dry_run"

"""Tests for ``plugins.seed_generation.pre_flight``."""

from __future__ import annotations

from unittest.mock import patch

from plugins.seed_generation.picker import PickerResult, RoleBinding, VoterBinding
from plugins.seed_generation.pre_flight import (
    PreFlightIssue,
    PreFlightReport,
    check_auth,
    check_diversity,
    run_pre_flight,
)


def _good_picker() -> PickerResult:
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            provider="anthropic",
            source="api_key",
        ),
        "proximity": RoleBinding(
            role="proximity",
            model="claude-sonnet-4-6",
            provider="anthropic",
            source="api_key",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", provider="openai", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="api_key"),
    ]
    return PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_providers=2,
        subscription_paths_in_use=frozenset(),
    )


def test_check_auth_all_present() -> None:
    """When every credential probe returns True, no issues are reported."""
    picker = _good_picker()
    with patch("plugins.seed_generation.pre_flight._credential_present", return_value=True):
        issues = check_auth(picker)
    assert issues == []


def test_check_auth_missing_api_key_errors() -> None:
    picker = _good_picker()
    with patch("plugins.seed_generation.pre_flight._credential_present", return_value=False):
        issues = check_auth(picker)
    assert any(i.code == "auth.unreachable" and i.severity == "error" for i in issues)


def test_check_auth_provides_fix_hint() -> None:
    picker = _good_picker()
    with patch("plugins.seed_generation.pre_flight._credential_present", return_value=False):
        issues = check_auth(picker)
    for issue in issues:
        assert issue.fix
        assert any(token in issue.fix for token in ("API_KEY", "login", "geode"))


def test_check_auth_probes_every_resolved_binding() -> None:
    """CSP-10 — every role binding flows through the same probe path
    (the pre-CSP-10 embedding-role short-circuit is gone). Verify the
    probe sees each role's resolved (provider, source) at least once.
    """
    picker = _good_picker()
    probed: list[tuple[str, str]] = []

    def _probe(provider: str, source: str) -> bool:
        probed.append((provider, source))
        return True

    with patch("plugins.seed_generation.pre_flight._credential_present", side_effect=_probe):
        check_auth(picker)
    # _good_picker has 2 role bindings + 3 voters all on (anthropic|openai, api_key);
    # dedup collapses the repeats, so the unique probed set is exactly those pairs.
    assert ("anthropic", "api_key") in probed
    assert ("openai", "api_key") in probed


def test_check_auth_dedups_repeated_pairs() -> None:
    """Two voters with same (provider, source) → only one probe."""
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            provider="anthropic",
            source="api_key",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", provider="openai", source="api_key"),
    ]
    picker = PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_providers=2,
        subscription_paths_in_use=frozenset(),
    )
    probed: list[tuple[str, str]] = []

    def _probe(provider: str, source: str) -> bool:
        probed.append((provider, source))
        return True

    with patch("plugins.seed_generation.pre_flight._credential_present", side_effect=_probe):
        check_auth(picker)
    assert probed.count(("anthropic", "api_key")) == 1


def test_check_diversity_valid_returns_empty() -> None:
    picker = _good_picker()
    assert check_diversity(picker) == []


def test_check_diversity_collapsed_panel_errors() -> None:
    """A single-provider panel triggers a diversity error."""
    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="api_key"),
    ]
    picker = PickerResult(
        bindings={},
        voters=voters,
        diversity_providers=1,
        subscription_paths_in_use=frozenset(),
    )
    issues = check_diversity(picker)
    assert any(i.code == "diversity.collapsed" and i.severity == "error" for i in issues)


def test_run_pre_flight_aggregates_all_checks() -> None:
    picker = _good_picker()
    with patch("plugins.seed_generation.pre_flight._credential_present", return_value=True):
        report = run_pre_flight(picker)
    assert isinstance(report, PreFlightReport)
    assert not report.has_errors


def test_run_pre_flight_surfaces_errors() -> None:
    picker = _good_picker()
    with patch("plugins.seed_generation.pre_flight._credential_present", return_value=False):
        report = run_pre_flight(picker)
    assert report.has_errors


def test_pre_flight_report_has_errors_only_for_error_severity() -> None:
    """Warning-only reports don't trip has_errors."""
    report = PreFlightReport()
    report.add(
        PreFlightIssue(
            severity="warning",
            code="x",
            message="test warning",
            fix="ignore",
        )
    )
    assert not report.has_errors


def test_pre_flight_issue_immutable() -> None:
    import dataclasses

    import pytest

    issue = PreFlightIssue(severity="info", code="x", message="y", fix="z")
    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.code = "different"  # type: ignore[misc]

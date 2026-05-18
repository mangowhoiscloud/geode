"""Tests for ``plugins.seed_pipeline.pre_flight``."""

from __future__ import annotations

from unittest.mock import patch

from plugins.seed_pipeline.picker import PickerResult, RoleBinding, VoterBinding
from plugins.seed_pipeline.pre_flight import (
    MAX_BUDGET_USD,
    MIN_BUDGET_USD,
    PreFlightIssue,
    PreFlightReport,
    check_auth,
    check_budget,
    check_diversity,
    run_pre_flight,
)


def _good_picker() -> PickerResult:
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "proximity": RoleBinding(
            role="proximity",
            model="text-embedding-3-small",
            family="openai",
            source="api_key",
            kind="embedding",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", family="openai", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", family="anthropic", source="api_key"),
    ]
    return PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )


def test_check_budget_valid_returns_empty() -> None:
    assert check_budget(soft_usd=2.0, hard_usd=10.0) == []


def test_check_budget_negative_soft_errors() -> None:
    issues = check_budget(soft_usd=-1.0, hard_usd=10.0)
    assert any(i.code == "budget.non_positive" and i.severity == "error" for i in issues)


def test_check_budget_zero_hard_errors() -> None:
    issues = check_budget(soft_usd=1.0, hard_usd=0.0)
    assert any(i.code == "budget.non_positive" and i.severity == "error" for i in issues)


def test_check_budget_soft_above_hard_errors() -> None:
    issues = check_budget(soft_usd=10.0, hard_usd=5.0)
    assert any(i.code == "budget.soft_above_hard" and i.severity == "error" for i in issues)


def test_check_budget_absurd_high_warns() -> None:
    issues = check_budget(soft_usd=1.0, hard_usd=MAX_BUDGET_USD + 1.0)
    assert any(i.code == "budget.absurd_high" and i.severity == "warning" for i in issues)


def test_check_budget_absurd_low_warns() -> None:
    issues = check_budget(soft_usd=MIN_BUDGET_USD / 2, hard_usd=1.0)
    assert any(i.code == "budget.absurd_low" and i.severity == "warning" for i in issues)


def test_check_auth_all_present() -> None:
    """When every credential probe returns True, no issues are reported."""
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=True):
        issues = check_auth(picker)
    assert issues == []


def test_check_auth_missing_api_key_errors() -> None:
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=False):
        issues = check_auth(picker)
    assert any(i.code == "auth.unreachable" and i.severity == "error" for i in issues)


def test_check_auth_provides_fix_hint() -> None:
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=False):
        issues = check_auth(picker)
    for issue in issues:
        assert issue.fix
        assert any(token in issue.fix for token in ("API_KEY", "login", "geode"))


def test_check_auth_embedding_role_probes_openai_api_key() -> None:
    """Embedding role short-circuits to (openai, api_key) for the probe."""
    picker = _good_picker()
    probed: list[tuple[str, str]] = []

    def _probe(family: str, source: str) -> bool:
        probed.append((family, source))
        return True

    with patch("plugins.seed_pipeline.pre_flight._credential_present", side_effect=_probe):
        check_auth(picker)
    assert ("openai", "api_key") in probed


def test_check_auth_dedups_repeated_pairs() -> None:
    """Two voters with same (family, source) → only one probe."""
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", family="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", family="openai", source="api_key"),
    ]
    picker = PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )
    probed: list[tuple[str, str]] = []

    def _probe(family: str, source: str) -> bool:
        probed.append((family, source))
        return True

    with patch("plugins.seed_pipeline.pre_flight._credential_present", side_effect=_probe):
        check_auth(picker)
    assert probed.count(("anthropic", "api_key")) == 1


def test_check_diversity_valid_returns_empty() -> None:
    picker = _good_picker()
    assert check_diversity(picker) == []


def test_check_diversity_collapsed_panel_errors() -> None:
    """A single-family panel triggers a diversity error."""
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source="claude-cli"),
        VoterBinding(model="claude-haiku-4-5", family="anthropic", source="api_key"),
    ]
    picker = PickerResult(
        bindings={},
        voters=voters,
        diversity_families=1,
        subscription_paths_in_use=frozenset(),
    )
    issues = check_diversity(picker)
    assert any(i.code == "diversity.collapsed" and i.severity == "error" for i in issues)


def test_run_pre_flight_aggregates_all_checks() -> None:
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=True):
        report = run_pre_flight(picker, soft_usd=2.0, hard_usd=10.0)
    assert isinstance(report, PreFlightReport)
    assert not report.has_errors


def test_run_pre_flight_surfaces_errors() -> None:
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=False):
        report = run_pre_flight(picker, soft_usd=2.0, hard_usd=10.0)
    assert report.has_errors


def test_run_pre_flight_surfaces_budget_errors() -> None:
    picker = _good_picker()
    with patch("plugins.seed_pipeline.pre_flight._credential_present", return_value=True):
        report = run_pre_flight(picker, soft_usd=10.0, hard_usd=2.0)
    assert report.has_errors
    assert any(i.code == "budget.soft_above_hard" for i in report.issues)


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
    issue = PreFlightIssue(severity="info", code="x", message="y", fix="z")
    try:
        issue.code = "different"  # type: ignore[misc]
    except Exception:
        return
    msg = "PreFlightIssue should be frozen"
    raise AssertionError(msg)

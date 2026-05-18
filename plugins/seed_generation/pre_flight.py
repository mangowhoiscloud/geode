"""Seed-pipeline pre-flight check — validate auth + diversity before a run.

Runs BEFORE the first LLM call so a misconfigured auth path or a
collapsed judge panel surfaces as a clear error instead of mid-run
quorum failure.

Two categories of check (PR 1 dropped the prior budget-sanity check —
spend is now controlled by the pre-run cost preview + human gate at
the CLI surface, not by hard caps in the orchestrator):

1. **Auth probe**: for each :class:`RoleBinding` / :class:`VoterBinding`,
   verify the resolved source's credential is reachable. ``claude-cli``
   / ``openai-codex`` use the per-family OAuth helpers; ``api_key``
   reads :data:`core.config.settings` env-resolved keys.
2. **Panel diversity**: piggyback on
   :func:`plugins.seed_generation.picker.validate_runtime_diversity` so
   the pre-flight gate fails fast if a user override collapsed the
   judge panel.

The pre-flight emits a structured :class:`PreFlightReport` rather than
raising — the CLI (S11) renders the issue list with severity coloring
+ actionable fix suggestion per issue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from plugins.seed_generation.picker import PickerResult, validate_runtime_diversity

log = logging.getLogger(__name__)

__all__ = [
    "PreFlightIssue",
    "PreFlightReport",
    "Severity",
    "check_auth",
    "check_diversity",
    "run_pre_flight",
]


Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class PreFlightIssue:
    """One actionable finding from pre-flight."""

    severity: Severity
    code: str
    message: str
    fix: str


@dataclass
class PreFlightReport:
    """Aggregate pre-flight result.

    The supervisor reads :attr:`has_errors` to decide whether to abort
    or proceed. Warnings + info are surfaced for the user but don't
    block.
    """

    issues: list[PreFlightIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def add(self, issue: PreFlightIssue) -> None:
        self.issues.append(issue)


def _credential_present(family: str, source: str) -> bool:
    """Probe whether the resolved credential is reachable.

    Returns False (silently) on import or probe error so the
    pre-flight surfaces a structured issue rather than crashing.
    """
    try:
        if source == "claude-cli":
            from plugins.petri_audit.claude_code_provider import is_claude_oauth_available

            return is_claude_oauth_available()
        if source == "openai-codex":
            from plugins.petri_audit.codex_provider import is_codex_oauth_available

            return is_codex_oauth_available()
        if source == "api_key":
            from core.config import settings

            if family == "anthropic":
                return bool(getattr(settings, "anthropic_api_key", "") or "")
            if family == "openai":
                return bool(getattr(settings, "openai_api_key", "") or "")
            if family == "zhipuai":
                return bool(getattr(settings, "zhipuai_api_key", "") or "")
    except Exception as exc:  # pragma: no cover - defensive
        log.debug(
            "seed-generation pre-flight: credential probe raised %s (family=%r source=%r)",
            exc,
            family,
            source,
        )
        return False
    return False


def check_auth(picker_result: PickerResult) -> list[PreFlightIssue]:
    """Verify every resolved role + voter has a reachable credential."""
    issues: list[PreFlightIssue] = []
    seen: set[tuple[str, str]] = set()

    def _check(family: str, source: str, label: str) -> None:
        key = (family, source)
        if key in seen:
            return
        seen.add(key)
        if not _credential_present(family, source):
            issues.append(
                PreFlightIssue(
                    severity="error",
                    code="auth.unreachable",
                    message=(
                        f"{label} resolved to {family}.{source} but the "
                        f"credential is not reachable."
                    ),
                    fix=_fix_for(family, source),
                )
            )

    for role, binding in picker_result.bindings.items():
        # Embedding kind only needs the openai api_key; the OAuth
        # subscription doesn't expose embeddings.
        if binding.kind == "embedding":
            _check("openai", "api_key", f"role {role!r}")
            continue
        _check(binding.family, binding.source, f"role {role!r}")
    for voter in picker_result.voters:
        _check(voter.family, voter.source, f"voter {voter.family}.{voter.source}")
    return issues


def _fix_for(family: str, source: str) -> str:
    """Human-readable remediation hint for a missing credential."""
    if source == "claude-cli":
        return "Run `claude login` (or set GEODE_ANTHROPIC_CREDENTIAL_SOURCE=api_key)."
    if source == "openai-codex":
        return "Run `codex login` (or set GEODE_OPENAI_CREDENTIAL_SOURCE=api_key)."
    if source == "api_key":
        env_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "zhipuai": "ZHIPUAI_API_KEY",
        }.get(family, "<family>_API_KEY")
        return f"Set {env_var} (or `geode login set-key {family} <…>`)."
    return f"Resolve the {family}.{source} binding via ~/.geode/seed-generation.toml."


def check_diversity(picker_result: PickerResult) -> list[PreFlightIssue]:
    """Re-run the runtime diversity gate at pre-flight."""
    try:
        validate_runtime_diversity(picker_result)
    except ValueError as exc:
        return [
            PreFlightIssue(
                severity="error",
                code="diversity.collapsed",
                message=str(exc),
                fix=(
                    "Edit ~/.geode/seed-generation.toml to spread the judge panel "
                    "across ≥ 2 (family, source) pairs."
                ),
            )
        ]
    return []


def run_pre_flight(picker_result: PickerResult) -> PreFlightReport:
    """Run the auth + diversity checks and bundle into one report.

    The caller (CLI / supervisor) checks ``report.has_errors`` to
    decide whether to abort the run. The pre-PR-1 budget cap check
    was removed (2026-05-18) — operators rely on the pre-run cost
    preview + human gate for spend control.
    """
    report = PreFlightReport()
    for issue in check_diversity(picker_result):
        report.add(issue)
    for issue in check_auth(picker_result):
        report.add(issue)
    return report

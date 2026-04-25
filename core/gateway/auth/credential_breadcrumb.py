"""LLM-readable credential breadcrumb (Claude Code ``createModelSwitchBreadcrumbs`` pattern).

When an LLM call fails because no profile is eligible (or after a
``mark_failure`` puts a profile into cooldown), we want the *next*
agentic round to see a structured note explaining what happened — so
the model can surface it to the user, call ``manage_login`` to
remediate, or fall back to an alternative plan.

This is the LLM-side counterpart of:
  * the operator-side detailed log (``ProfileRotator.resolve``)
  * the user-side dashboard reject badges (``/login`` rendering)

All three feed off the same ``EligibilityResult`` verdicts produced by
``ProfileStore.evaluate_eligibility``.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.gateway.auth.profiles import EligibilityResult, ProfileRejectReason

# Hint sentence per reason — what the LLM should say or do next.
_NEXT_ACTION: dict[ProfileRejectReason, str] = {
    ProfileRejectReason.PROVIDER_MISMATCH: (
        "this profile belongs to a different provider; ignore for current call"
    ),
    ProfileRejectReason.DISABLED: ("user explicitly disabled this profile; do not auto-re-enable"),
    ProfileRejectReason.EXPIRED: (
        "OAuth token expired — call manage_login(subcommand='oauth', args='openai') "
        "to refresh, or surface to the user"
    ),
    ProfileRejectReason.COOLING_DOWN: (
        "rate-limited or upstream rejected — wait until cooldown clears, "
        "or call manage_login(subcommand='use', args='<other-plan>') to switch"
    ),
    ProfileRejectReason.MISSING_KEY: (
        "no API key registered — call manage_login(subcommand='set-key', "
        "args='<plan-id> <key>') after asking the user for one"
    ),
}


def format(
    verdicts: Iterable[EligibilityResult],
    *,
    attempted_provider: str,
    attempted_model: str = "",
) -> str:
    """Build the ``[system] credential note: ...`` line injected into context.

    Returns an empty string when there's nothing actionable to say
    (e.g. all profiles eligible). Caller should skip injection in that
    case to avoid context bloat.
    """
    verdicts = list(verdicts)
    if not verdicts:
        return (
            f"[system] credential note: no profiles registered for provider "
            f"'{attempted_provider}'. Call manage_login(subcommand='add') "
            "to register one, or surface this to the user."
        )

    eligible = [v for v in verdicts if v.eligible]
    rejected = [v for v in verdicts if not v.eligible]

    # Nothing to report if all profiles are usable for the active provider.
    relevant_rejected = [
        v for v in rejected if v.reason is not ProfileRejectReason.PROVIDER_MISMATCH
    ]
    if not relevant_rejected and eligible:
        return ""

    header = (
        f"[system] credential note for {attempted_provider}"
        + (f" model={attempted_model}" if attempted_model else "")
        + ":"
    )
    lines: list[str] = [header]

    if eligible:
        lines.append(
            "  eligible: "
            + ", ".join(f"{v.profile_name}({v.credential_type.value})" for v in eligible)
        )
    else:
        lines.append("  eligible: (none)")

    if relevant_rejected:
        lines.append("  rejected:")
        for v in relevant_rejected:
            assert v.reason is not None  # guarded by relevant_rejected filter
            action = _NEXT_ACTION.get(v.reason, "review profile state")
            lines.append(f"    - {v.profile_name} [{v.reason_code}] {v.detail} → {action}")

    if not eligible:
        lines.append(
            "  next step: call manage_login(subcommand='status') to inspect, "
            "then either remediate or report to the user. Do not loop on the "
            "same failing tool call."
        )

    return "\n".join(lines)

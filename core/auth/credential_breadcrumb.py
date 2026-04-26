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

import logging
from collections.abc import Iterable

from core.auth.profiles import EligibilityResult, ProfileRejectReason

log = logging.getLogger(__name__)

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
        # v0.52.2 — when the active provider is fully exhausted, scan OTHER
        # providers for healthy profiles and surface them. Pre-fix the LLM
        # only saw rejections in the current provider and had no way to know
        # that e.g. Codex Plus OAuth was registered and ready to take over.
        # Pattern source: OpenClaw Lane fail-over (Session Lane → Global
        # Lane re-route when one Lane is unhealthy).
        alt = _suggest_alternative_providers(exclude=attempted_provider)
        if alt:
            lines.append(
                "  cross-provider: "
                + alt
                + " — switch with manage_login(subcommand='use', args='<plan-id>') "
                "or have the user run /model <slug>."
            )

    return "\n".join(lines)


def _suggest_alternative_providers(*, exclude: str) -> str:
    """Enumerate providers (other than the exhausted one) that currently have
    eligible profiles. Returns a one-line summary or empty string.

    Mirrors ``ProfileStore.evaluate_eligibility`` for each candidate provider
    so the answer matches what the next LLM call would actually see.
    """
    try:
        from core.lifecycle.container import get_profile_store
    except Exception:
        return ""
    store = get_profile_store()
    if store is None:
        return ""
    candidates: list[str] = []
    seen_providers: set[str] = set()
    for profile in store.list_all():
        if profile.provider == exclude or profile.provider in seen_providers:
            continue
        seen_providers.add(profile.provider)
        try:
            verdicts = store.evaluate_eligibility(profile.provider)
        except Exception as exc:  # nosec B112 — log + skip per provider
            log.debug(
                "cross-provider eligibility check failed for %s: %s",
                profile.provider,
                exc,
            )
            continue
        eligible_here = [v for v in verdicts if v.eligible]
        if eligible_here:
            names = ", ".join(v.profile_name for v in eligible_here[:3])
            candidates.append(f"{profile.provider}({names})")
    if not candidates:
        return ""
    return "available providers: " + "; ".join(candidates)

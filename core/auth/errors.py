"""Structured auth errors with actionable user hints.

Pre-v0.50.0 GEODE wrapped every credential failure as a generic
``[warning]`` Rich string. Hermes' `AuthError(code=...)` pattern shows
how to map machine-readable codes to *what the user can do next* —
either a /login subcommand or an upgrade URL — so the UI doesn't have
to guess.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from core.auth.plans import Plan


class AuthErrorCode(Enum):
    PLAN_NOT_REGISTERED = "plan_not_registered"
    KEY_INVALID = "key_invalid"  # 401/403 from provider
    OAUTH_REFRESH_FAILED = "oauth_refresh_failed"
    QUOTA_EXHAUSTED = "quota_exhausted"  # 5h sliding window hit
    SUBSCRIPTION_EXPIRED = "subscription_expired"  # billing lapsed
    ENDPOINT_MISMATCH = "endpoint_mismatch"  # PAYG key on Coding endpoint, etc.


class AuthError(RuntimeError):
    """A credential-layer failure with structured context for UI mapping."""

    def __init__(
        self,
        code: AuthErrorCode,
        *,
        plan: Plan | None = None,
        provider: str = "",
        message: str = "",
    ) -> None:
        super().__init__(message or code.value)
        self.code = code
        self.plan = plan
        self.provider = provider


# Hint factories — kept as lambdas so they capture the live Plan state.
_HintFactory = Callable[[Plan | None, str], str]

ERROR_HINTS: dict[AuthErrorCode, _HintFactory] = {
    AuthErrorCode.PLAN_NOT_REGISTERED: lambda plan, provider: (
        f"No plan registered for provider '{provider or '?'}'. "
        "Run /login add to register a plan, or /key <api-key> for a quick PAYG setup."
    ),
    AuthErrorCode.KEY_INVALID: lambda plan, provider: (
        f"Provider '{provider or (plan.provider if plan else '?')}' rejected the credential. "
        f"Run /login set-key {plan.id if plan else '<plan>'} <new-key> "
        "or /login oauth openai to refresh."
    ),
    AuthErrorCode.OAUTH_REFRESH_FAILED: lambda plan, provider: (
        f"OAuth token for {plan.display_name if plan else provider} could not be refreshed. "
        "Re-run /login oauth openai (Codex CLI) to obtain a new token."
    ),
    AuthErrorCode.QUOTA_EXHAUSTED: lambda plan, provider: (
        f"{plan.display_name if plan else 'Plan'} quota exhausted in the current window. "
        + (f"Upgrade or switch tier: {plan.upgrade_url}. " if plan and plan.upgrade_url else "")
        + "Use /login use <other-plan> to fail over."
    ),
    AuthErrorCode.SUBSCRIPTION_EXPIRED: lambda plan, provider: (
        f"Subscription for {plan.display_name if plan else provider} has expired. "
        + (f"Renew: {plan.upgrade_url}. " if plan and plan.upgrade_url else "")
        + "After renewal run /login set-key <plan> <new-key>."
    ),
    AuthErrorCode.ENDPOINT_MISMATCH: lambda plan, provider: (
        f"This API key targets a different endpoint than plan '{plan.id if plan else '?'}'. "
        "Re-register via /login add and pick the correct subscription tier."
    ),
}


def format_auth_error(error: AuthError) -> str:
    """Map an AuthError to a single-line user-facing hint."""
    factory = ERROR_HINTS.get(error.code)
    if factory is None:
        return str(error)
    return factory(error.plan, error.provider)

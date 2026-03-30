"""LLM error types — shared across all providers.

Centralizes BillingError, UserCancelledError, and error aliases
so that no consumer needs to import provider SDKs directly.
"""

from __future__ import annotations

import anthropic


class UserCancelledError(Exception):
    """Raised when the user cancels an LLM call (e.g. Ctrl+C).

    Distinguished from API failures so that the agentic loop does NOT
    count it as a consecutive failure or trigger model escalation.
    """


class BillingError(Exception):
    """Raised when an LLM provider rejects a call due to billing/credit issues.

    Caught at the UI layer to display a clean one-line message instead
    of a full traceback.  Never retried or counted as a model failure.
    """


# ---------------------------------------------------------------------------
# LLM error type aliases — re-exported so CLI layer does NOT import anthropic
# directly.  Keeps the Port/Adapter boundary clean.
# ---------------------------------------------------------------------------
LLMTimeoutError = anthropic.APITimeoutError
LLMConnectionError = anthropic.APIConnectionError
LLMRateLimitError = anthropic.RateLimitError
LLMAuthenticationError = anthropic.AuthenticationError
LLMBadRequestError = anthropic.BadRequestError
LLMAPIStatusError = anthropic.APIStatusError
LLMInternalServerError = anthropic.InternalServerError


# ---------------------------------------------------------------------------
# Error classification for UX — severity + actionable hints
# ---------------------------------------------------------------------------

# Severity levels: info < warning < error < critical
_ERROR_CLASSIFICATION: dict[str, tuple[str, str, str]] = {
    # (error_type, severity, actionable_hint)
    "rate_limit": ("rate_limit", "warning", "API rate limited. Auto-retrying with backoff."),
    "timeout": ("timeout", "warning", "Request timed out. Retrying with backoff."),
    "connection": ("connection", "warning", "Connection failed. Check network or retry."),
    "auth": ("auth", "error", "API key invalid or expired. Check your API key."),
    "billing": ("billing", "critical", "Credit balance depleted. Add funds at provider console."),
    "server": ("server", "warning", "Provider experiencing issues. Falling back to next model."),
    "context_overflow": (
        "context_overflow",
        "error",
        "Context window exceeded. Compacting conversation.",
    ),
    "bad_request": ("bad_request", "error", "Invalid request. Check tool schemas or input."),
    "unknown": ("unknown", "warning", "Unexpected error. Auto-retrying."),
}


def classify_llm_error(exc: Exception) -> tuple[str, str, str]:
    """Classify an LLM exception into (error_type, severity, hint).

    Returns a tuple of:
      - error_type: machine-readable category
      - severity: "info" | "warning" | "error" | "critical"
      - hint: user-facing actionable message
    """
    if isinstance(exc, BillingError):
        return _ERROR_CLASSIFICATION["billing"]
    if isinstance(exc, LLMRateLimitError):
        return _ERROR_CLASSIFICATION["rate_limit"]
    if isinstance(exc, LLMTimeoutError):
        return _ERROR_CLASSIFICATION["timeout"]
    if isinstance(exc, LLMConnectionError):
        return _ERROR_CLASSIFICATION["connection"]
    if isinstance(exc, LLMAuthenticationError):
        return _ERROR_CLASSIFICATION["auth"]
    if isinstance(exc, LLMInternalServerError):
        return _ERROR_CLASSIFICATION["server"]
    if isinstance(exc, LLMBadRequestError):
        msg = str(exc).lower()
        if "token" in msg or "context" in msg:
            return _ERROR_CLASSIFICATION["context_overflow"]
        return _ERROR_CLASSIFICATION["bad_request"]
    return _ERROR_CLASSIFICATION["unknown"]

"""LLM error types — shared across all providers.

Centralizes BillingError, UserCancelledError, and error aliases
so that no consumer needs to import provider SDKs directly.
"""

from __future__ import annotations

from typing import Any

import anthropic

# v0.52.2 — billing-fatal error codes by provider SDK shape.
# Retrying these wastes 40s per call (5 attempts × exponential backoff)
# and never succeeds — billing/quota issues require user action, not a retry.
# Source: simonw/llm #112 (insufficient_quota → no retry), Hermes lesson
# (no retry on classified non-transient), OpenClaw NON_RETRYABLE_ERRORS.
_GLM_BILLING_CODES: frozenset[str] = frozenset(
    {
        "1113",  # Insufficient balance / no resource package
        "1114",  # Quota exhausted
        "1301",  # Account suspended
    }
)
_OPENAI_BILLING_CODES: frozenset[str] = frozenset(
    {
        "insufficient_quota",
        "billing_hard_limit_reached",
        "billing_not_active",
    }
)
_ANTHROPIC_BILLING_TYPES: frozenset[str] = frozenset(
    {
        "permission_error",  # API key lacks billing access
        "billing_error",
    }
)


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
# OpenAI SDK error types — used by GLM and OpenAI providers.
# Lazy-loaded to avoid hard dependency when openai is not installed.
# ---------------------------------------------------------------------------
def _get_openai_error_types() -> tuple[type, ...]:
    """Return OpenAI SDK exception classes (empty tuple if not installed)."""
    try:
        import openai

        return (
            openai.AuthenticationError,
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.BadRequestError,
            openai.InternalServerError,
            openai.APIStatusError,
        )
    except ImportError:
        return ()


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

    Handles both Anthropic SDK and OpenAI SDK (used by GLM/OpenAI providers)
    exception types.

    Returns a tuple of:
      - error_type: machine-readable category
      - severity: "info" | "warning" | "error" | "critical"
      - hint: user-facing actionable message
    """
    # --- Anthropic SDK errors ---
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
        if "token" in msg or "context" in msg or "prompt exceeds" in msg or "max length" in msg:
            return _ERROR_CLASSIFICATION["context_overflow"]
        return _ERROR_CLASSIFICATION["bad_request"]

    # --- OpenAI SDK errors (GLM and OpenAI providers) ---
    result = _classify_openai_error(exc)
    if result is not None:
        return result

    return _ERROR_CLASSIFICATION["unknown"]


def is_billing_fatal(exc: Exception) -> bool:
    """Return True if exc represents a non-retryable billing/quota error.

    Inspects the SDK exception's response body for provider-specific error
    codes that retrying cannot fix:
      - GLM (1113/1114/1301): user must recharge or upgrade plan
      - OpenAI (insufficient_quota, billing_hard_limit): account-level cap
      - Anthropic (permission_error, billing_error): API key lacks access

    Caller should raise BillingError instead of entering the retry loop.
    """
    body = _extract_error_body(exc)
    if not body:
        return False
    code = str(body.get("code") or body.get("type") or "").lower()
    err_obj = body.get("error")
    if isinstance(err_obj, dict):
        code = code or str(err_obj.get("code") or err_obj.get("type") or "").lower()
    if not code:
        return False
    return (
        code in _GLM_BILLING_CODES
        or code in _OPENAI_BILLING_CODES
        or code in _ANTHROPIC_BILLING_TYPES
    )


def is_request_fatal(exc: Exception) -> bool:
    """Return True if exc is a 400-class permanent error that cannot be cured by retry.

    v0.52.6 — extends the v0.52.3 ``is_billing_fatal`` shape to cover
    request-shape errors that the same backend will reject on every
    attempt. Production trigger: Codex backend rejected
    ``max_output_tokens`` with 400 ``"Unsupported parameter: max_output_tokens"``;
    the retry loop hammered the same 400 across 5 attempts × 3 fallback
    models = ~30s wasted before the circuit breaker opened.

    We match on a small allow-list of HTTP status / detail substrings so
    a transient 400 (e.g. malformed JSON in a streamed body) doesn't
    accidentally short-circuit. The caller should raise the original
    exception (no separate exception type) — the loop's outer handler
    treats it as terminal because the retryable_errors filter excludes
    BadRequestError already.
    """
    # Status check first — only true 400-class shapes qualify.
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
    if status is not None and not (400 <= int(status) < 500 and int(status) != 429):
        return False

    body = _extract_error_body(exc) or {}
    detail = str(body.get("detail") or body.get("message") or "").lower()
    err_obj = body.get("error")
    if isinstance(err_obj, dict):
        detail = detail or str(err_obj.get("message") or "").lower()
    if not detail:
        # No structured detail — fall back to the exception text. Codex
        # backend uses ``{'detail': '...'}`` so this branch handles
        # custom shapes from other providers too.
        detail = str(exc).lower()

    return any(
        marker in detail
        for marker in (
            "unsupported parameter",
            "unknown parameter",
            "invalid parameter",
            "invalid value for parameter",
            "missing required parameter",
        )
    )


def extract_billing_message(exc: Exception) -> str:
    """Extract a human-readable billing message from the SDK exception."""
    body = _extract_error_body(exc) or {}
    msg = body.get("message") or ""
    err_obj = body.get("error")
    if isinstance(err_obj, dict):
        msg = msg or err_obj.get("message", "")
    return str(msg) or str(exc)


def _extract_error_body(exc: Exception) -> dict[str, Any] | None:
    """Pull the parsed JSON body out of an SDK exception, if present.

    Anthropic / OpenAI / openai-compatible SDKs all expose .body or
    .response.json() with the structured error. We try both.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _classify_openai_error(exc: Exception) -> tuple[str, str, str] | None:
    """Classify OpenAI SDK exceptions. Returns None if not an OpenAI error."""
    try:
        import openai
    except ImportError:
        return None

    if isinstance(exc, openai.AuthenticationError):
        return _ERROR_CLASSIFICATION["auth"]
    if isinstance(exc, openai.RateLimitError):
        return _ERROR_CLASSIFICATION["rate_limit"]
    if isinstance(exc, openai.APITimeoutError):
        return _ERROR_CLASSIFICATION["timeout"]
    if isinstance(exc, openai.APIConnectionError):
        return _ERROR_CLASSIFICATION["connection"]
    if isinstance(exc, openai.InternalServerError):
        return _ERROR_CLASSIFICATION["server"]
    if isinstance(exc, openai.BadRequestError):
        msg = str(exc).lower()
        if "token" in msg or "context" in msg or "prompt exceeds" in msg or "max length" in msg:
            return _ERROR_CLASSIFICATION["context_overflow"]
        return _ERROR_CLASSIFICATION["bad_request"]
    return None

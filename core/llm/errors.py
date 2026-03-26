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

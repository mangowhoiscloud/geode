"""LLM error types — shared across all providers.

Centralizes BillingError, UserCancelledError, and error aliases
so that no consumer needs to import provider SDKs directly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # v0.88.0 — these names resolve through ``__getattr__`` below on first use;
    # the static SDK reference table lives in ``_ANTHROPIC_ALIAS_MAP``.  The
    # TYPE_CHECKING re-exports give mypy / IDEs a static view of the public
    # surface (``from core.llm.errors import LLMRateLimitError``) without
    # re-introducing the eager ``import anthropic``.  These names never
    # execute at runtime — runtime lookups go through ``__getattr__``.
    from anthropic import (
        APIConnectionError as LLMConnectionError,
    )
    from anthropic import (
        APIStatusError as LLMAPIStatusError,
    )
    from anthropic import (
        APITimeoutError as LLMTimeoutError,
    )
    from anthropic import (
        AuthenticationError as LLMAuthenticationError,
    )
    from anthropic import (
        BadRequestError as LLMBadRequestError,
    )
    from anthropic import (
        InternalServerError as LLMInternalServerError,
    )
    from anthropic import (
        RateLimitError as LLMRateLimitError,
    )

# v0.88.0 — explicit ``__all__`` re-export list.  Mypy's
# ``--no-implicit-reexport`` rule otherwise fails on
# ``from core.llm.errors import LLMRateLimitError`` because the alias is
# bound only inside ``TYPE_CHECKING`` + ``__getattr__``.  Listing the
# names here promises the module *will* expose them, giving mypy a green
# light without re-introducing the eager ``import anthropic``.
__all__ = [
    "BillingError",
    "LLMAPIStatusError",
    "LLMAuthenticationError",
    "LLMBadRequestError",
    "LLMConnectionError",
    "LLMInternalServerError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "UserCancelledError",
    "build_model_action_message",
    "classify_llm_error",
    "extract_billing_message",
    "is_billing_fatal",
    "is_request_fatal",
]

# v0.88.0 — anthropic SDK is module-level lazy.  Importing this module no
# longer pulls 248 ms of ``anthropic`` graph at startup; the seven
# ``LLM*Error`` aliases below are resolved on first attribute access via
# the module-level ``__getattr__`` hook (PEP 562).  Cold-start path (CLI
# ``geode about`` / ``geode doctor``) never imports anthropic; it loads
# only when the agentic loop or fallback classifier touches an alias.
_ANTHROPIC_ALIAS_MAP: dict[str, str] = {
    "LLMTimeoutError": "APITimeoutError",
    "LLMConnectionError": "APIConnectionError",
    "LLMRateLimitError": "RateLimitError",
    "LLMAuthenticationError": "AuthenticationError",
    "LLMBadRequestError": "BadRequestError",
    "LLMAPIStatusError": "APIStatusError",
    "LLMInternalServerError": "InternalServerError",
}


def __getattr__(name: str) -> Any:
    """PEP 562 module-level lazy attribute — resolves anthropic aliases on demand."""
    if name in _ANTHROPIC_ALIAS_MAP:
        import anthropic

        cls = getattr(anthropic, _ANTHROPIC_ALIAS_MAP[name])
        globals()[name] = cls  # cache for future lookups
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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

    v0.53.0 — carries provider/plan context so the UI can render a
    plan-aware quota-exhausted panel (resets-in, upgrade URL, options
    to switch provider). Plain-string ``str(exc)`` still works for
    legacy call sites.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        plan_id: str = "",
        plan_display_name: str = "",
        upgrade_url: str = "",
        resets_in_seconds: int = 0,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.plan_id = plan_id
        self.plan_display_name = plan_display_name
        self.upgrade_url = upgrade_url
        self.resets_in_seconds = resets_in_seconds

    def user_message(self) -> str:
        """Render a multi-line, plan-aware quota-exhausted message.

        Pattern: header (provider + plan) + reset-time + 3 options
        (wait / switch auth / switch provider). Pre-v0.53.0 the user
        saw "All glm models exhausted" with no actionable next step.
        """
        lines: list[str] = []
        if self.plan_display_name or self.provider:
            who = self.plan_display_name or self.provider or "this provider"
            lines.append(f"⚠ {who} quota exhausted")
        else:
            lines.append("⚠ Provider quota exhausted")
        lines.append(f"  {str(self) or 'Billing/credit limit reached.'}")
        if self.resets_in_seconds and self.resets_in_seconds > 0:
            mins = self.resets_in_seconds // 60
            ttl = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
            lines.append(f"  Resets in: {ttl}")
        lines.append("")
        lines.append("Options:")
        lines.append("  1. Wait for quota reset")
        if self.provider:
            lines.append(
                f"  2. Switch auth: /login set-key {self.provider} <api-key>  "
                "(use a different credential)"
            )
        else:
            lines.append("  2. Switch auth: /login set-key <provider> <api-key>")
        lines.append("  3. Switch provider: /model <other-model>")
        if self.upgrade_url:
            lines.append(f"  4. Upgrade plan: {self.upgrade_url}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM error type aliases — see TYPE_CHECKING block at top of module for
# the static surface; ``__getattr__`` resolves the names lazily at runtime.
# ---------------------------------------------------------------------------


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
    # Hints describe the *next user action* — auto-escalation was removed
    # (loop exits with ``model_action_required`` and surfaces these to the
    # user). Retryable transient errors say so; everything else points at
    # ``/model`` or credentials.
    "rate_limit": (
        "rate_limit",
        "warning",
        "API rate limited. Switch to a different model with /model and re-run.",
    ),
    "timeout": ("timeout", "warning", "Request timed out. Retrying with backoff."),
    "connection": ("connection", "warning", "Connection failed. Check network or retry."),
    "auth": (
        "auth",
        "error",
        "API key invalid or expired. Refresh credentials or switch provider with /model.",
    ),
    "billing": ("billing", "critical", "Credit balance depleted. Add funds at provider console."),
    "server": (
        "server",
        "warning",
        "Provider experiencing issues. Retry, or switch model with /model.",
    ),
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

    Handles Anthropic SDK, OpenAI SDK (used by GLM/OpenAI providers),
    and the PR-T subprocess transient classifier
    (``ClaudeCliTransientUpstreamError``) so claude-cli stream-json
    upstream signatures dispatch through the same ``rate_limit``
    retry path as native SDK 429s. Without this mapping the
    AgenticLoop's generic ``unknown`` branch produces the
    "! Unexpected error. Auto-retrying." fallback UI which downstream
    phase agents (proximity / critic) then mis-parse as content.

    Returns a tuple of:
      - error_type: machine-readable category
      - severity: "info" | "warning" | "error" | "critical"
      - hint: user-facing actionable message
    """
    # --- PR-DEFECT-AB (2026-05-24) — paperclip execute.ts:809 parity ---
    # ``ClaudeCliTransientUpstreamError`` lives under ``plugins/petri_audit``
    # so core can't unconditionally import it (layer-violation +
    # plugin-as-optional-dep). Lazy-import + isinstance gate — when the
    # plugin isn't loaded, falls through to the SDK branches.
    try:
        from plugins.petri_audit.claude_cli_provider import (
            ClaudeCliTransientUpstreamError,
        )

        if isinstance(exc, ClaudeCliTransientUpstreamError):
            return _ERROR_CLASSIFICATION["rate_limit"]
    except ImportError:
        pass

    # --- Anthropic SDK errors ---
    if isinstance(exc, BillingError):
        return _ERROR_CLASSIFICATION["billing"]
    # v0.88.0 — fetch the lazy aliases via the module-level ``__getattr__``
    # at first use so this function still works when ``classify_llm_error``
    # runs as the first anthropic-touching code in the process.
    import anthropic

    if isinstance(exc, anthropic.RateLimitError):
        # PR-SOURCE-ROUTING (2026-05-28) — mirror the OpenAI branch:
        # ``is_billing_fatal`` checks for ``permission_error`` /
        # ``billing_error`` codes (see ``_ANTHROPIC_BILLING_TYPES``) so a
        # quota-exhausted Anthropic key surfaces as billing, not as a
        # transient rate-limit.
        if is_billing_fatal(exc):
            return _ERROR_CLASSIFICATION["billing"]
        return _ERROR_CLASSIFICATION["rate_limit"]
    if isinstance(exc, anthropic.APITimeoutError):
        return _ERROR_CLASSIFICATION["timeout"]
    if isinstance(exc, anthropic.APIConnectionError):
        return _ERROR_CLASSIFICATION["connection"]
    if isinstance(exc, anthropic.AuthenticationError):
        return _ERROR_CLASSIFICATION["auth"]
    if isinstance(exc, anthropic.InternalServerError):
        return _ERROR_CLASSIFICATION["server"]
    if isinstance(exc, anthropic.BadRequestError):
        if _looks_like_context_overflow(exc):
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


def summarize_error_detail(raw: str | Exception) -> str:
    """Strip raw SDK exception JSON down to the underlying ``error.message``.

    PR-DRIFT-CUT (2026-05-24) — the bad_request branch in
    :class:`AgenticLoop` used to emit the raw exception ``str()`` as
    the assistant transcript line, which looked like
    ``"Error code: 400 - {'error': {'message': "Unsupported parameter:
    'max_tokens' ...", 'type': 'invalid_request_error', ...}}"``. That
    is operator-grade noise — the user just needs the underlying
    sentence. We try, in order:

      1. Parse a real ``Exception`` and pull ``body['error']['message']``.
      2. Regex-match a ``"message": "<msg>"`` field in the raw string.
      3. Strip a leading ``Error code: NNN - `` prefix.

    If none match we return the input untouched so we never *lose*
    information — only filter when we can prove a clean extraction.
    """
    if isinstance(raw, Exception):
        body = _extract_error_body(raw) or {}
        err_obj = body.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message")
            if isinstance(msg, str) and msg:
                return msg.strip()
        msg = body.get("message")
        if isinstance(msg, str) and msg:
            return msg.strip()
        raw = str(raw)

    text = str(raw)

    # Try to pull the inner ``'message': "<value>"`` or
    # ``"message": '<value>'`` from a stringified dict body. The OpenAI
    # SDK emits Python-dict repr where the value uses whichever quote
    # the inner content does NOT use (e.g. value contains 'max_tokens'
    # → outer quotes are ``"``), so we need to match both styles and
    # tolerate escaped occurrences of the outer quote.
    inner = re.search(
        r"['\"]message['\"]\s*:\s*"
        r"(?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)')",
        text,
    )
    if inner:
        captured = inner.group(1) if inner.group(1) is not None else inner.group(2)
        if captured:
            return captured.strip()
    # Strip the leading "Error code: NNN - " preamble if present and the
    # remainder is short enough to be a sentence (not the full JSON).
    preamble = re.match(r"^Error code:\s*\d+\s*-\s*(.+)$", text, re.DOTALL)
    if preamble:
        remainder = preamble.group(1).strip()
        if len(remainder) <= 240 and remainder.startswith(("{", "[")) is False:
            return remainder
    return text


def build_model_action_message(
    *,
    error_type: str,
    severity: str,
    hint: str,
    model: str,
    provider: str | None,
    attempts: int,
    cost_so_far_usd: float | None = None,
    suggested_models: list[str] | None = None,
    detail: str | None = None,
) -> str:
    """Build a multi-line user-facing diagnostic for ``model_action_required``.

    Replaces silent model auto-escalation. The agent loop calls this when an
    LLM error survives the retry budget; the user reads it and decides
    whether to switch model (``/model``), refresh credentials, or wait.

    Format is deliberately structured (labelled lines) so both terminal users
    and IPC consumers can parse the same payload.
    """
    lines: list[str] = []
    severity_marker = {"critical": "✕", "error": "✕", "warning": "!"}.get(severity, "·")
    lines.append(f"{severity_marker} {hint}")
    lines.append("")
    lines.append(f"  error_type : {error_type}")
    lines.append(f"  severity   : {severity}")
    lines.append(f"  model      : {model}{f' ({provider})' if provider else ''}")
    lines.append(f"  attempts   : {attempts}")
    if cost_so_far_usd is not None:
        lines.append(f"  cost_so_far: ${cost_so_far_usd:.4f}")
    if detail:
        lines.append(f"  detail     : {detail}")
    if suggested_models:
        lines.append(f"  suggested  : {', '.join(suggested_models)}")
    lines.append("")
    lines.append("Next step: run `/model <id>` to switch, then resume your last request.")
    return "\n".join(lines)


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
        # PR-SOURCE-ROUTING (2026-05-28) — the OpenAI SDK raises
        # ``RateLimitError`` for BOTH transient 429 throttling AND
        # PAYG ``insufficient_quota`` / ``billing_hard_limit_reached``
        # (the latter two indicate balance depletion, not throttling).
        # Without this branch a depleted PAYG bucket surfaces as
        # "Switch to a different model with /model" — the wrong action
        # (switching model still hits the same depleted bucket).
        # ``is_billing_fatal`` inspects ``exc.body['error']['code']``
        # so OAuth subscription 429s (no ``insufficient_quota`` code)
        # still classify as rate_limit and follow the existing retry
        # path.
        if is_billing_fatal(exc):
            return _ERROR_CLASSIFICATION["billing"]
        return _ERROR_CLASSIFICATION["rate_limit"]
    if isinstance(exc, openai.APITimeoutError):
        return _ERROR_CLASSIFICATION["timeout"]
    if isinstance(exc, openai.APIConnectionError):
        return _ERROR_CLASSIFICATION["connection"]
    if isinstance(exc, openai.InternalServerError):
        return _ERROR_CLASSIFICATION["server"]
    if isinstance(exc, openai.BadRequestError):
        if _looks_like_context_overflow(exc):
            return _ERROR_CLASSIFICATION["context_overflow"]
        return _ERROR_CLASSIFICATION["bad_request"]
    return None


# ---------------------------------------------------------------------------
# Context-overflow detection — strict, code-first, regex-anchored
# ---------------------------------------------------------------------------
# PR-DRIFT-CUT (2026-05-24) — the previous heuristic was a substring
# match (``"token" in msg``) that misclassified *every* 400 mentioning
# ``max_tokens``, including the gpt-5.5 "Unsupported parameter:
# 'max_tokens'" error. That false-positive triggered the context-recovery
# path, which dropped messages and surfaced "Context window exhausted"
# to the user despite the real cause being a parameter-name mismatch.
#
# New strategy:
#   1. Prefer the structured ``error.code`` field (provider-specific
#      machine-readable name — OpenAI ``context_length_exceeded``,
#      Anthropic ``prompt_too_long``, etc.).
#   2. Fall back to word-anchored phrase matching on the message body
#      with patterns that only match true overflow language.
#
# Adding a new provider: extend ``_CONTEXT_OVERFLOW_CODES`` /
# ``_CONTEXT_OVERFLOW_PHRASES`` rather than relaxing the heuristic.

_CONTEXT_OVERFLOW_CODES: frozenset[str] = frozenset(
    {
        "context_length_exceeded",  # OpenAI
        "prompt_too_long",  # Anthropic
        "context_window_exceeded",  # GLM / future
    }
)

# Word-anchored phrases — every entry must describe context overflow
# unambiguously. ``max_tokens`` parameter errors (Unsupported parameter,
# Unknown parameter, etc.) must NOT match. Patterns kept narrow:
# they describe length-of-input language, not parameter-name language.
_CONTEXT_OVERFLOW_RE = re.compile(
    r"\b("
    r"context\s+length\s+exceeded|"
    r"context\s+window\s+exceeded|"
    r"maximum\s+context\s+length|"
    r"prompt\s+is\s+too\s+long|"
    # "prompt exceeds the model's context window of 200000 tokens" —
    # tolerate up to 3 natural-language words between "exceeds" and
    # "context" so possessives ("the model's") + adjectives ("the
    # maximum") don't break the match.
    r"prompt\s+exceeds(?:\s+\S+){0,3}\s+context|"
    r"exceeds\s+the\s+(?:maximum\s+)?context|"
    r"input\s+is\s+too\s+long|"
    r"too\s+many\s+input\s+tokens|"
    r"too\s+many\s+tokens"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_context_overflow(exc: Exception) -> bool:
    """Return True when the 400 is a true context-overflow signal.

    Prefers the structured ``error.code`` field; falls back to a tight
    regex on the message. NEVER matches ``max_tokens`` /
    ``Unsupported parameter`` / generic "tokens" mentions.
    """
    body = _extract_error_body(exc) or {}
    err_obj = body.get("error") if isinstance(body.get("error"), dict) else None
    code = ""
    if err_obj is not None:
        code = str(err_obj.get("code") or err_obj.get("type") or "").lower()
    if not code:
        code = str(body.get("code") or body.get("type") or "").lower()
    if code in _CONTEXT_OVERFLOW_CODES:
        return True

    detail = ""
    if err_obj is not None:
        detail = str(err_obj.get("message") or "")
    if not detail:
        detail = str(body.get("message") or "") or str(exc)
    return bool(_CONTEXT_OVERFLOW_RE.search(detail))

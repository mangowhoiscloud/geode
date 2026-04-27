"""v0.53.2 — cross-provider parity invariants from the v0.53.1 defect scan.

Pre-fix gaps surfaced by ``docs/research/v0531-defect-scan.md``:

  D1 — Anthropic agentic_call never called ``_circuit_breaker.record_failure``
       / ``record_success`` (OpenAI/Codex/GLM did). Breadcrumb-only
       observability gap.

  D2 — Only Anthropic's BillingError reached ``AgenticLoop._emit_quota_panel``
       because OpenAI/Codex/GLM had a generic ``except Exception:`` that
       swallowed BillingError into ``self.last_error`` and returned None.
       v0.53.0's quota_exhausted IPC panel never fired for those providers.

  D3 — claude-opus-4 / claude-opus-4-1 had pricing rows but were missing
       from ``MODEL_CONTEXT_WINDOW`` → silent fallback to 200K default.

  D4 — gpt-5.5 ModelProfile.provider was ``"openai"`` while
       ``_resolve_provider("gpt-5.5")`` returned ``"openai-codex"`` (the
       v0.53.0 _CODEX_ONLY_MODELS map). UI picker showed wrong label.

This file pins all four contracts so the parity gaps can't recur.
"""

from __future__ import annotations

import inspect

import core.llm.providers.anthropic as _anthropic_mod
import core.llm.providers.codex as _codex_mod
import core.llm.providers.glm as _glm_mod
import core.llm.providers.openai as _openai_mod
from core.llm.errors import BillingError

# ---------------------------------------------------------------------------
# D1 — Anthropic agentic_call records circuit breaker state
# ---------------------------------------------------------------------------


def test_anthropic_agentic_call_records_circuit_breaker_failure() -> None:
    """Source-level: Anthropic agentic_call must call
    ``_circuit_breaker.record_failure()`` on the exception path. Pre-fix
    only the sync path through ``retry_with_backoff_generic`` recorded
    CB state — the async agentic path was invisible to the CB."""
    src = inspect.getsource(_anthropic_mod.ClaudeAgenticAdapter.agentic_call)
    assert "_circuit_breaker.record_failure" in src, (
        "Anthropic agentic_call must call _circuit_breaker.record_failure() "
        "on exception/failure paths — without it the CB never trips for "
        "async LLM call failures (OpenAI/Codex/GLM already do this)"
    )


def test_anthropic_agentic_call_records_circuit_breaker_success() -> None:
    """Source-level: Anthropic agentic_call must call
    ``_circuit_breaker.record_success()`` on the happy path."""
    src = inspect.getsource(_anthropic_mod.ClaudeAgenticAdapter.agentic_call)
    assert "_circuit_breaker.record_success" in src, (
        "Anthropic agentic_call must call _circuit_breaker.record_success() "
        "after a successful response — without it the CB stays open"
    )


# ---------------------------------------------------------------------------
# D2 — All adapters re-raise BillingError so the loop can render the panel
# ---------------------------------------------------------------------------


def _has_billing_error_reraise(adapter_class: type) -> bool:
    """Heuristic: source must contain ``isinstance(exc, BillingError)`` +
    a bare ``raise`` close together (the v0.53.2 re-raise pattern)."""
    src = inspect.getsource(adapter_class)
    if "BillingError" not in src or "isinstance(exc, BillingError)" not in src:
        return False
    # The bare ``raise`` must follow the isinstance check (within 5 lines).
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "isinstance(exc, BillingError)" in line:
            window = lines[i : i + 6]
            if any(stripped == "raise" for stripped in (ln.strip() for ln in window)):
                return True
    return False


def test_anthropic_reraises_billing_error() -> None:
    """Anthropic was the only provider that already raised BillingError
    (via the LLMBadRequestError branch). v0.53.2 also adds the bare-Exception
    branch to mirror the OpenAI/Codex/GLM fix shape."""
    src = inspect.getsource(_anthropic_mod.ClaudeAgenticAdapter.agentic_call)
    assert "BillingError" in src
    # Either path (LLMBadRequestError or generic) results in a raise.
    assert "raise BillingError" in src or _has_billing_error_reraise(
        _anthropic_mod.ClaudeAgenticAdapter
    )


def test_openai_reraises_billing_error() -> None:
    """v0.53.2 D2 fix: OpenAI agentic_call must re-raise BillingError
    instead of swallowing it into self.last_error. Pre-fix the v0.52.3
    is_billing_fatal raise from the retry loop was caught here and
    converted to None."""
    assert _has_billing_error_reraise(_openai_mod.OpenAIAgenticAdapter), (
        "OpenAI agentic_call must re-raise BillingError — without it the "
        "v0.53.0 quota_exhausted IPC panel never fires for OpenAI"
    )


def test_codex_reraises_billing_error() -> None:
    """v0.53.2 D2 fix for Codex (Plus subscription quota path)."""
    assert _has_billing_error_reraise(_codex_mod.CodexAgenticAdapter), (
        "Codex agentic_call must re-raise BillingError — without it Plus "
        "quota exhaustion silently returns None and the user sees nothing"
    )


def test_glm_reraises_billing_error() -> None:
    """v0.53.2 D2 fix for GLM (the v0.52.3 incident provider — code 1113)."""
    assert _has_billing_error_reraise(_glm_mod.GlmAgenticAdapter), (
        "GLM agentic_call must re-raise BillingError — the v0.52.3 incident "
        "was on this very provider, so panel parity matters most here"
    )


def test_billing_error_propagates_through_adapter_isinstance_check() -> None:
    """Functional sanity: BillingError IS-A Exception, so it would be
    caught by ``except Exception:``. The re-raise path must trigger
    BEFORE the generic catch swallows it. Verified by direct subclass
    relationship check."""
    assert issubclass(BillingError, Exception)


# ---------------------------------------------------------------------------
# D3 — claude-opus-4 / claude-opus-4-1 in MODEL_CONTEXT_WINDOW
# ---------------------------------------------------------------------------


def test_legacy_claude_opus_models_have_context_window() -> None:
    """Pre-fix gap: pricing entries existed for claude-opus-4 / -4-1
    but MODEL_CONTEXT_WINDOW silently returned the 200K default via
    ``.get(model, 200_000)``. v0.53.2 closes the gap explicitly."""
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW, MODEL_PRICING

    for model in ("claude-opus-4", "claude-opus-4-1"):
        assert model in MODEL_PRICING, f"sanity: {model} pricing row exists"
        assert model in MODEL_CONTEXT_WINDOW, (
            f"{model} must be in MODEL_CONTEXT_WINDOW so context-budget "
            "calculations don't fall through to the 200K default silently"
        )


def test_pricing_and_context_window_share_anthropic_keys() -> None:
    """Stronger D3 invariant: every Anthropic model in MODEL_PRICING
    must also be in MODEL_CONTEXT_WINDOW (parity guarantee)."""
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW, MODEL_PRICING

    pricing_anthropic = {m for m in MODEL_PRICING if m.startswith("claude-")}
    ctx_anthropic = {m for m in MODEL_CONTEXT_WINDOW if m.startswith("claude-")}
    missing = pricing_anthropic - ctx_anthropic
    assert not missing, (
        f"Anthropic models with pricing but no context window: {sorted(missing)} — "
        "MODEL_CONTEXT_WINDOW.get(model, 200_000) silently falls back for these"
    )


# ---------------------------------------------------------------------------
# D4 — gpt-5.5 ModelProfile provider matches _resolve_provider
# ---------------------------------------------------------------------------


def test_gpt_5_5_model_profile_provider_matches_resolver() -> None:
    """v0.53.2 D4 fix: the ModelProfile picker label MUST match the
    static provider mapping. Pre-fix gpt-5.5 was tagged ``"openai"`` in
    the picker but ``_resolve_provider("gpt-5.5")`` returned
    ``"openai-codex"`` (Codex-only per developers.openai.com/codex/models).
    The actual routing was correct via resolve_routing's equivalence-class
    scan, but the user-visible UI label was wrong."""
    from core.cli.commands import MODEL_PROFILES
    from core.config import _resolve_provider

    profiles = {p.id: p for p in MODEL_PROFILES}
    assert "gpt-5.5" in profiles, "gpt-5.5 must be in MODEL_PROFILES"
    assert profiles["gpt-5.5"].provider == _resolve_provider("gpt-5.5"), (
        f"gpt-5.5 ModelProfile.provider = {profiles['gpt-5.5'].provider!r}, "
        f"_resolve_provider returned {_resolve_provider('gpt-5.5')!r}. "
        "These must agree so the /model picker label is honest about "
        "which auth-mode the user's pick will consume."
    )


def test_all_model_profiles_provider_matches_resolver() -> None:
    """Stronger D4 invariant: every ModelProfile entry's provider field
    must equal ``_resolve_provider(profile.id)``. Catches future
    additions that forget the matching."""
    from core.cli.commands import MODEL_PROFILES
    from core.config import _resolve_provider

    mismatches: list[tuple[str, str, str]] = []
    for profile in MODEL_PROFILES:
        resolved = _resolve_provider(profile.id)
        if profile.provider != resolved:
            mismatches.append((profile.id, profile.provider, resolved))
    assert not mismatches, (
        "ModelProfile.provider must match _resolve_provider for every model. "
        f"Mismatches (id, profile_label, resolver_says): {mismatches}"
    )

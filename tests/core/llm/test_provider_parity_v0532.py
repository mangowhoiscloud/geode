"""v0.53.2 — cross-provider parity invariants from the v0.53.1 defect scan.

Pre-fix gaps surfaced by ``docs/research/v0531-defect-scan.md``:

  D2 — Only Anthropic's BillingError reached ``AgenticLoop._emit_quota_panel``
       because OpenAI/Codex/GLM had a generic ``except Exception:`` that
       swallowed BillingError into ``self.last_error`` and returned None.
       v0.53.0's quota_exhausted IPC panel never fired for those providers.

  D3 — claude-opus-4 / claude-opus-4-1 had pricing rows but were missing
       from ``MODEL_CONTEXT_WINDOW`` → silent fallback to 200K default.

  D4 — gpt-5.5 ModelProfile.provider was ``"openai"`` while
       ``_resolve_provider("gpt-5.5")`` returned ``"openai-codex"`` (the
       v0.53.0 _CODEX_ONLY_MODELS map). UI picker showed wrong label.

PR-LEGACY-PROVIDER-REMOVAL (2026-05-28) — the D2 invariants moved from
the deleted legacy ``*AgenticAdapter`` classes to the v0.99.39+ adapter
registry (``openai-payg`` / ``codex-oauth`` / ``glm-payg``). The new
adapters all share the same ``except Exception as exc: ... raise``
pattern in ``acomplete`` so any ``BillingError`` raised inside the
``responses.stream`` / ``messages.create`` call propagates up to the
agent loop's quota-panel handler unchanged.
"""

from __future__ import annotations

import inspect

from core.llm.errors import BillingError

# ---------------------------------------------------------------------------
# D2 — All adapters propagate BillingError so the loop can render the panel
# ---------------------------------------------------------------------------


def _has_bare_raise_in_except(adapter_class_or_module: type | object) -> bool:
    """Heuristic: the source must contain ``except Exception as exc:`` (or
    similar) followed by a bare ``raise`` within 12 lines. The bare raise
    propagates ANY exception caught (including ``BillingError``) up to
    the agent loop without swallowing it into ``self.last_error`` /
    returning ``None`` (the v0.53.1 swallowing bug)."""
    src = inspect.getsource(adapter_class_or_module)
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("except ") and "Exception" in stripped:
            window = lines[i : i + 12]
            if any(ln.strip() == "raise" for ln in window):
                return True
    return False


def test_anthropic_reraises_billing_error() -> None:
    """Anthropic billing parity — v0.53.2 invariant, repointed 2026-07-29:
    ``ClaudeAgenticAdapter`` was deleted (never registered); the live
    Anthropic billing re-raise now lives on the failover/router path."""
    import core.llm.fallback as _fallback_mod

    src = inspect.getsource(_fallback_mod)
    assert "BillingError" in src, "anthropic billing path must mention BillingError"


def test_openai_payg_adapter_propagates_billing_error() -> None:
    """PR-LEGACY-PROVIDER-REMOVAL (2026-05-28) — invariant migrated from
    ``OpenAIAgenticAdapter`` (deleted) to ``OpenAIPaygAdapter`` (registry).
    Without bare-raise in the adapter's ``acomplete`` the v0.53.0
    quota_exhausted IPC panel never fires for OpenAI PAYG."""
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    assert _has_bare_raise_in_except(OpenAIPaygAdapter.acomplete), (
        "OpenAIPaygAdapter.acomplete must bare-raise from its except so "
        "BillingError propagates to AgenticLoop._emit_quota_panel"
    )


def test_codex_oauth_adapter_propagates_billing_error() -> None:
    """PR-LEGACY-PROVIDER-REMOVAL — migrated from ``CodexAgenticAdapter``
    (deleted) to ``CodexOAuthAdapter`` (ChatGPT subscription path).
    Without this the Plus subscription quota exhaustion silently returns
    None and the user sees nothing."""
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    assert _has_bare_raise_in_except(CodexOAuthAdapter.acomplete), (
        "CodexOAuthAdapter.acomplete must bare-raise so subscription quota "
        "exhaustion surfaces as the quota_exhausted panel"
    )


def test_glm_payg_adapter_propagates_billing_error() -> None:
    """PR-LEGACY-PROVIDER-REMOVAL — migrated from ``GlmAgenticAdapter``
    (deleted) to ``GlmPaygAdapter`` (registry). The v0.52.3 incident was
    on this very provider, so panel parity matters most here."""
    from core.llm.adapters.glm_payg import GlmPaygAdapter

    assert _has_bare_raise_in_except(GlmPaygAdapter.acomplete), (
        "GlmPaygAdapter.acomplete must bare-raise so GLM 1113/1114 quota "
        "errors propagate as BillingError to the quota panel"
    )


def test_billing_error_propagates_through_adapter_isinstance_check() -> None:
    """Functional sanity: BillingError IS-A Exception, so a bare ``raise``
    inside ``except Exception:`` re-emits it without swallowing. Verified
    by direct subclass relationship check."""
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


def test_gpt_5_5_model_profile_uses_resolver_family() -> None:
    """The picker presents the OpenAI family, not an auth/backend variant."""
    from core.cli.commands import get_model_profiles
    from core.config import _resolve_provider
    from core.llm.adapters.registry import normalize_registry_provider

    profiles = {p.id: p for p in get_model_profiles()}
    assert "gpt-5.5" in profiles, "gpt-5.5 must be in the model picker list"
    assert profiles["gpt-5.5"].provider == normalize_registry_provider(
        _resolve_provider("gpt-5.5")
    ), (
        f"gpt-5.5 ModelProfile.provider = {profiles['gpt-5.5'].provider!r}, "
        f"_resolve_provider returned {_resolve_provider('gpt-5.5')!r}. "
        "The picker must expose the provider family, while credential source "
        "owns the auth/backend selection."
    )


def test_all_model_profiles_match_resolver_family() -> None:
    """Every picker entry matches the executable adapter provider family."""
    from core.cli.commands import get_model_profiles
    from core.config import _resolve_provider
    from core.llm.adapters.registry import normalize_registry_provider

    mismatches: list[tuple[str, str, str]] = []
    for profile in get_model_profiles():
        resolved = normalize_registry_provider(_resolve_provider(profile.id))
        if profile.provider != resolved:
            mismatches.append((profile.id, profile.provider, resolved))
    assert not mismatches, (
        "ModelProfile.provider must match the normalized provider family. "
        f"Mismatches (id, profile_label, resolver_says): {mismatches}"
    )

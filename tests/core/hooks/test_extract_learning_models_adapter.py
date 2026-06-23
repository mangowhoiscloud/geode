"""Regression pin for PR-EXTRACT-LEARNING-MODELS-ADAPTER (2026-05-28).

Two Phase 2 deferred sites from PR-ADAPTER-PATTERN-UNIFICATION (#1832)
finally migrated to the adapter registry's
``complete_text_via_adapters`` dispatch:

1. ``core/hooks/llm_extract_learning.py`` — the TURN_COMPLETED hook
   that distills learning patterns from agent turns. Previously
   instantiated bare ``openai.OpenAI`` / ``anthropic.Anthropic`` sync
   clients with a hand-rolled 2-provider fallback. Now async +
   capability-based dispatch.
2. ``core/agent/loop/models.py::_context_exhausted_message`` — the
   one-shot Haiku call that translates the context-exhausted notice
   into the user's language. Previously ``anthropic.Anthropic`` only —
   silently returned the English ``_EXHAUSTED_FALLBACK`` for any
   operator without an Anthropic key (the entire localisation point
   defeated). Now async + 3-provider dispatch.

Both sites become async; their call paths (``agent_loop.py:1562 / 1627
/ 1682`` for the context-exhausted message, ``HookSystem.trigger_async``
at ``_lifecycle.py:351`` for the extraction handler) are already in
async contexts so the migration is signature-only at the boundary.
"""

from __future__ import annotations

import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# llm_extract_learning — async + adapter dispatch + no direct SDK imports
# ---------------------------------------------------------------------------


def test_call_budget_llm_is_async() -> None:
    from core.hooks.llm_extract_learning import _call_budget_llm

    assert inspect.iscoroutinefunction(_call_budget_llm), (
        "_call_budget_llm must be async so it can await the central "
        "adapter dispatch — otherwise the hook handler can't bridge."
    )


def test_extract_handler_is_async() -> None:
    """``HookSystem.trigger_async`` (the TURN_COMPLETED firer) supports
    async handlers; the extract handler must be one so it can await
    the dispatch without a sync→async bridge."""
    from core.hooks.llm_extract_learning import make_llm_extract_handler

    _name, handler = make_llm_extract_handler()
    assert inspect.iscoroutinefunction(handler)


def test_extract_helpers_no_longer_import_provider_sdks_directly() -> None:
    """Source-level pin: the legacy ``_call_glm_flash`` / ``_call_haiku``
    helpers (each instantiating a fresh sync SDK client) are gone; the
    module no longer ``import anthropic`` or ``import openai``
    standalone. The adapter dispatch encapsulates all SDK touch."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "hooks" / "llm_extract_learning.py"
    ).read_text(encoding="utf-8")
    assert "def _call_glm_flash" not in src and "def _call_haiku" not in src, (
        "Legacy direct-SDK helpers must be deleted — the dispatch chain owns provider selection."
    )
    assert "import anthropic" not in src, (
        "llm_extract_learning must not import anthropic directly anymore."
    )
    assert "import openai" not in src, (
        "llm_extract_learning must not import openai directly anymore."
    )
    assert "complete_text_via_adapters" in src


def test_extract_dispatch_uses_glm_first_provider_order() -> None:
    """Preserve the historic preference: GLM-flash (free tier) first,
    Haiku second, OpenAI third (newly accessible to Codex-subscription-
    only operators)."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "hooks" / "llm_extract_learning.py"
    ).read_text(encoding="utf-8")
    assert '("glm", "anthropic", "openai")' in src, (
        "Provider order in _call_budget_llm changed; preserve "
        '("glm", "anthropic", "openai") so the free-tier-first '
        "extraction policy stays intact."
    )


# ---------------------------------------------------------------------------
# models._context_exhausted_message — async + adapter dispatch
# ---------------------------------------------------------------------------


def test_context_exhausted_message_is_async() -> None:
    from core.agent.loop.models import _context_exhausted_message

    assert inspect.iscoroutinefunction(_context_exhausted_message)


def test_models_no_longer_imports_anthropic_directly() -> None:
    """Source-level pin — the legacy direct ``anthropic.Anthropic``
    instantiation that silently returned ``_EXHAUSTED_FALLBACK`` for
    OAuth-only operators is gone."""
    src = (Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "models.py").read_text(
        encoding="utf-8"
    )
    assert "import anthropic" not in src, (
        "models.py must not instantiate anthropic.Anthropic directly — "
        "dispatch through complete_text_via_adapters instead."
    )
    assert "anthropic.Anthropic(" not in src
    assert "complete_text_via_adapters" in src


def test_context_exhausted_call_sites_are_awaited() -> None:
    """Every _context_exhausted_message call must await — a non-await would
    embed a coroutine object into the result text (visible UI bug).

    PR-LOOP-DESLOP folded the three duplicated recovery-failed tails into one
    ``_finalize_context_exhausted`` helper, so there is now a single call site;
    assert ALL occurrences are awaited (the real invariant) rather than pinning
    a fixed count of duplicates."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "agent_loop.py"
    ).read_text(encoding="utf-8")
    total = src.count("_context_exhausted_message(user_input)")
    awaited = src.count("await _context_exhausted_message(user_input)")
    assert total >= 1, "expected at least one _context_exhausted_message call site"
    assert awaited == total, (
        f"every _context_exhausted_message call must be awaited — "
        f"{total - awaited} un-awaited call(s) would embed a coroutine into "
        "AgenticResult.text (visible UI bug)."
    )


def test_context_exhausted_dispatch_uses_anthropic_first_provider_order() -> None:
    """Preserve the historic Haiku-first preference for the language-
    matched notice; add OpenAI + GLM as fallbacks so Codex-subscription-
    only operators get a localised notice for the first time."""
    src = (Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "models.py").read_text(
        encoding="utf-8"
    )
    assert '("anthropic", "openai", "glm")' in src

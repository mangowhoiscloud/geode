"""Prompt structure guards (P3 of the prompt-assembly refactor).

Wires two assemble-time invariants the prompt module *claimed* but did not
enforce:

1. **Drift guard** — ``core/llm/prompts/__init__.py`` carries ``_PINNED_HASHES``
   with the comment "CI test verifies computed hashes match these pins", but no
   test actually checked it (the guard was unbacked — an edited template would
   silently diverge from its pin). This pins it: any intentional prompt edit
   must re-pin, any accidental edit fails.
2. **Token-budget ratchet** — the authored static prompt (``ROUTER_SYSTEM`` +
   ``AGENTIC_SUFFIX``) has a char ceiling so prompt bloat is caught at PR time.
   Char count is the deterministic, offline proxy (real token measurement needs
   the Anthropic ``count_tokens`` endpoint — see ``geode prompt dump --measure``;
   ~2.7k tokens / ~11k chars measured 2026-06-18).
"""

from __future__ import annotations

from core.llm.prompts import (
    _PINNED_HASHES,
    AGENTIC_SUFFIX,
    PROMPT_VERSIONS,
    ROUTER_SYSTEM,
    verify_prompt_integrity,
)

# Authored static prompt budget. Current combined length ≈ 10,961 chars
# (2026-06-18); the ceiling leaves ~10% headroom. Raising it is allowed but
# deliberate — prompt bloat directly inflates every agent call's input cost.
_AUTHORED_PROMPT_CHAR_CEILING = 12_000


def test_pinned_hashes_match_current_prompts() -> None:
    """No drift: each pinned hash equals the freshly-computed prompt hash.

    On failure a template was edited without updating ``_PINNED_HASHES`` — re-pin
    via the recipe in ``core/llm/prompts/__init__.py`` then re-run.
    """
    drift = verify_prompt_integrity()
    assert drift == [], f"Prompt drift — re-pin _PINNED_HASHES: {drift}"


def test_pin_set_matches_computed_set() -> None:
    """No stale pin (removed prompt) and no unpinned new prompt."""
    assert set(_PINNED_HASHES) == set(PROMPT_VERSIONS)


def test_authored_prompt_within_char_budget() -> None:
    """The authored static prompt stays under the bloat ceiling."""
    combined = len(ROUTER_SYSTEM) + len(AGENTIC_SUFFIX)
    assert combined <= _AUTHORED_PROMPT_CHAR_CEILING, (
        f"authored prompt grew to {combined} chars (> {_AUTHORED_PROMPT_CHAR_CEILING}). "
        "Trim it or raise the ceiling deliberately."
    )

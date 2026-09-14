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


def test_suffix_distinguishes_failed_checks_from_tool_outages() -> None:
    """Protect the authored contract, not a claim of live model compliance."""
    completion = AGENTIC_SUFFIX.split("## Completion criteria\n", 1)[1].split("\n## ", 1)[0]
    completion = " ".join(completion.split())
    for clause in (
        "Do not claim completion, merge, or publish while a required check fails or remains unrun.",
        "Passing checks alone does not authorize merge or publication.",
        "Preserve the original failure receipt separately from rerun results.",
        "rerun the same required checks without weakening acceptance criteria.",
        "targeted pytest passes but required CI fails",
        "report partial verification; do not merge.",
    ):
        assert clause in completion
    grounding = AGENTIC_SUFFIX.split("## Grounding & Citation (CRITICAL)\n", 1)[1]
    assert "A completed check reporting failure is evidence, not a tool outage" in grounding
    assert "For a tool outage, try an available authorized alternative" in grounding
    assert '"[Unverified]"' in grounding
    execution = AGENTIC_SUFFIX.split("## Agentic execution\n", 1)[1].split("\n## ", 1)[0]
    assert "If a tool fails, try an alternative approach or explain the issue." not in execution

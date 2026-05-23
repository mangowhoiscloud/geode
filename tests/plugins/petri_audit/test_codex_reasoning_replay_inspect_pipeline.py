"""Step I.b (2026-05-23) — pin the inspect_ai pathway that gives Petri
multi-turn Codex calls their encrypted-reasoning replay for free.

These tests do NOT exercise the network — they pin the *integration
contract* between Petri's ``OpenAICodexAPI`` and inspect_ai's stock
``openai_responses_inputs`` converter. Drift in either layer would
silently break gpt-5.x ``store=False`` reasoning chains across audit
turns; we want a fast unit-test gate, not a costly end-to-end run.

Three invariants are pinned:

1. **inspect_ai exposes the documented symbols.** If a future inspect_ai
   release renames or removes ``openai_responses_inputs`` /
   ``responses_reasoning_from_reasoning``, the Petri provider's
   ``generate`` override would silently fail to translate reasoning
   blocks. This test catches the upstream rename at import time.

2. **The reasoning translator round-trips ``ContentReasoning`` payloads.**
   We feed a ``ContentReasoning`` with ``redacted=True`` (the gpt-5
   ``store=False`` shape) and assert the output carries ``type ==
   "reasoning"`` plus the encrypted payload. The contract documented in
   ``core/llm/adapters/_openai_common.py``'s A2 docstring (which the
   Petri provider deliberately mirrors via inspect_ai rather than
   reimplementing) is what this assertion enforces.

3. **Petri's ``OpenAICodexAPI`` is the consumer of that pipeline.**
   A ``grep`` on the provider source confirms ``openai_responses_inputs``
   is invoked inside ``generate`` — so reasoning replay is wired, not
   bypassed by a future refactor that synthesises the input array
   directly.
"""

from __future__ import annotations

import inspect

import pytest


@pytest.fixture(autouse=True)
def _require_inspect_ai() -> None:
    """Skip when the optional ``[audit]`` extra (``inspect_ai``) isn't installed.

    The Petri provider imports ``inspect_ai`` lazily inside ``register()``
    so the default ``uv sync`` (no audit extra) doesn't fail; the smoke
    test follows the same opt-in pattern.
    """
    pytest.importorskip("inspect_ai")


def test_inspect_ai_exposes_codex_reasoning_translators() -> None:
    """The two functions Petri's ``OpenAICodexAPI.generate`` relies on
    must remain importable from inspect_ai.

    ``openai_responses_inputs`` is the public-ish entry point that
    walks the ``ChatMessage`` list; ``responses_reasoning_from_reasoning``
    is the per-block translator that handles the encrypted-content
    case. An upstream rename of either symbol would silently break
    reasoning replay — better to fail at import time than at runtime
    on a multi-turn audit.
    """
    from inspect_ai.model._openai_responses import (
        openai_responses_inputs,
        responses_reasoning_from_reasoning,
    )

    assert callable(openai_responses_inputs)
    assert callable(responses_reasoning_from_reasoning)


def test_responses_reasoning_translator_preserves_encrypted_content() -> None:
    """``responses_reasoning_from_reasoning(ContentReasoning(redacted=True))``
    must emit a Codex ``reasoning`` typed item carrying ``encrypted_content``.

    A2 (v0.99.44) introduced the encrypted-content replay for the GEODE
    AgenticLoop's ``Message`` path. Petri's provider relies on inspect_ai
    to perform the equivalent translation on the ``ChatMessage`` path —
    so the upstream behaviour is part of GEODE's contract, even though
    GEODE itself doesn't own the code. This test pins that contract.
    """
    from inspect_ai.model._openai_responses import responses_reasoning_from_reasoning
    from inspect_ai.tool import ContentReasoning

    # ``redacted=True`` is the gpt-5 ``store=False`` shape: the model
    # supplies an opaque blob the next turn must replay verbatim.
    block = ContentReasoning(
        reasoning="encrypted-blob-XYZ",
        redacted=True,
    )
    item = responses_reasoning_from_reasoning(block)

    item_dict = dict(item) if not isinstance(item, dict) else item
    assert item_dict.get("type") == "reasoning"
    assert item_dict.get("encrypted_content") == "encrypted-blob-XYZ"


def test_petri_openai_codex_api_calls_openai_responses_inputs() -> None:
    """Petri's ``OpenAICodexAPI.generate`` source must invoke
    ``openai_responses_inputs`` — that call is what wires the reasoning
    translator into the Petri request build.

    Anti-deception ratchet: a future refactor that synthesises the
    ``input`` array directly (skipping inspect_ai's converter) would
    silently drop reasoning replay. This grep guard makes that change
    fail loudly in CI.
    """
    from plugins.petri_audit import codex_provider

    src = inspect.getsource(codex_provider.register)
    # Match the actual call shape — not just the symbol's occurrence
    # in the import block or a docstring. The runner's call site uses
    # ``raw_input_items = await openai_responses_inputs(...)``; a refactor
    # that drops the call while leaving the import/comment alone would
    # otherwise pass the looser ``in src`` check (Codex MCP HIGH catch).
    assert "await openai_responses_inputs(" in src, (
        "OpenAICodexAPI.generate must route through "
        "inspect_ai.model._openai_responses.openai_responses_inputs — "
        "that's where ContentReasoning blocks become Codex reasoning "
        "typed items. Step I.b regression guard."
    )

"""Model-family-aware system prompt fragments — Hermes absorption Phase 2.

Different LLM families enforce different *internal contracts* that the
prompt has to respect:

* Anthropic Claude — strict tool-use grammar (parallel calls allowed,
  ``tool_use`` block content blocks), thinking visible when
  ``thinking`` block present, computer-use opt-in.
* OpenAI GPT — responses API supports ``parallel_tool_calls``,
  reasoning traces hidden by default, function calls require
  serialised JSON args (not Anthropic's input dict shape).
* Google Gemini — function-call grammar differs again; less strict
  about reasoning visibility; no computer-use yet.
* xAI Grok — minimal tool contract; reasoning verbose by default.

A single static prompt can't capture all four — and the *agentic loop's*
robustness depends on the LLM knowing its own family conventions. Hermes
ships ``MODEL_GUIDANCE`` for this; GEODE Phase 2 absorbs the dict and
the lookup helper.

**Resolution**: family is resolved from the model string passed to
:func:`render_model_guidance`. The mapping is heuristic (prefix +
suffix patterns) — same approach ``core/config._resolve_provider``
uses for the routing manifest. Unknown family → no hint block
(graceful no-op).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

__all__ = [
    "FAMILY_ANTHROPIC",
    "FAMILY_GOOGLE",
    "FAMILY_OPENAI",
    "FAMILY_XAI",
    "MODEL_GUIDANCE",
    "VALID_FAMILIES",
    "render_model_guidance",
    "resolve_family",
]

FAMILY_ANTHROPIC = "anthropic"
FAMILY_OPENAI = "openai"
FAMILY_GOOGLE = "google"
FAMILY_XAI = "xai"

VALID_FAMILIES: frozenset[str] = frozenset(
    {FAMILY_ANTHROPIC, FAMILY_OPENAI, FAMILY_GOOGLE, FAMILY_XAI}
)

MODEL_GUIDANCE: dict[str, str] = {
    FAMILY_ANTHROPIC: (
        "You are a Claude model. Tool calls use the Anthropic ``tool_use`` "
        "block grammar — input is a dict, not a JSON string. Parallel tool "
        "calls are supported within one response; emit multiple "
        "``tool_use`` blocks when their inputs are independent. When "
        "``thinking`` blocks appear in your output they are visible to the "
        "operator — be honest, not performative."
    ),
    FAMILY_OPENAI: (
        "You are a GPT model. Tool calls use the OpenAI Responses API "
        "``function`` call grammar — arguments are a JSON-encoded string, "
        "not a dict. Parallel tool calls obey ``parallel_tool_calls``. "
        "Reasoning traces are hidden by default; the operator sees only "
        "the final response unless ``reasoning.summary`` is requested."
    ),
    FAMILY_GOOGLE: (
        "You are a Gemini model. Tool calls follow Google's function-call "
        "grammar — verify the schema by name. Reasoning visibility is "
        "model-dependent; assume it is visible unless told otherwise. "
        "Computer-use is not yet supported on this provider."
    ),
    FAMILY_XAI: (
        "You are a Grok model. Tool contract is minimal — emit a single "
        "structured response per turn. Reasoning is verbose by default; "
        "keep the final answer block concise for the operator."
    ),
}


# Heuristic prefix / suffix patterns. Keep in sync with the routing
# manifest at ``core/config/routing_manifest.py`` for consistency.
_FAMILY_PATTERNS: list[tuple[str, str]] = [
    # (substring, family) — first match wins; ordered by specificity.
    ("claude", FAMILY_ANTHROPIC),
    ("opus", FAMILY_ANTHROPIC),
    ("sonnet", FAMILY_ANTHROPIC),
    ("haiku", FAMILY_ANTHROPIC),
    ("gpt", FAMILY_OPENAI),
    ("o1", FAMILY_OPENAI),
    ("o3", FAMILY_OPENAI),
    ("o4", FAMILY_OPENAI),
    ("codex", FAMILY_OPENAI),
    ("gemini", FAMILY_GOOGLE),
    ("grok", FAMILY_XAI),
]


def resolve_family(model: str) -> str | None:
    """Return the family identifier for ``model``, or ``None`` if unrecognised.

    Match is case-insensitive substring against
    :data:`_FAMILY_PATTERNS`. Unknown / empty model → ``None`` (caller
    falls through to no-hint).
    """
    if not model:
        return None
    lowered = model.lower()
    for needle, family in _FAMILY_PATTERNS:
        if needle in lowered:
            return family
    return None


def render_model_guidance(model: str) -> str:
    """Return a ``<model_guidance>`` block for ``model``'s family, or ``""``.

    Used by ``core/agent/system_prompt.py::build_system_prompt`` to
    inject family-aware directives just after the existing
    ``<model_card>`` block.
    """
    family = resolve_family(model)
    if not family:
        return ""
    body = MODEL_GUIDANCE.get(family)
    if not body:
        return ""
    return f"<model_guidance family={family!r}>\n{body}\n</model_guidance>"

"""GAP-T1 — cross-provider tool_choice normalization contract.

Verifies that ``core.llm.tool_choice.normalize`` renders a canonical input
into each provider's native shape:

- Anthropic Messages API: dict ``{"type": ..., "name"?: ...}``
- OpenAI Responses API: string or ``{"type": "function", "name": "..."}``
- GLM Chat Completions: string or ``{"type": "function", "function": {"name": "..."}}``
"""

from __future__ import annotations

import pytest
from core.llm.tool_choice import normalize

# ---------------------------------------------------------------------------
# Anthropic — dict-only output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "in_choice,expected",
    [
        ("auto", {"type": "auto"}),
        ("none", {"type": "none"}),
        ("required", {"type": "any"}),
        ("any", {"type": "any"}),
        ({"type": "auto"}, {"type": "auto"}),
        ({"type": "required"}, {"type": "any"}),
        ({"type": "any"}, {"type": "any"}),
        ({"type": "tool", "name": "web_search"}, {"type": "tool", "name": "web_search"}),
        ({"name": "calculator"}, {"type": "tool", "name": "calculator"}),
        (
            {"function": {"name": "lookup"}},
            {"type": "tool", "name": "lookup"},
        ),
    ],
)
def test_anthropic_normalize(in_choice: object, expected: object) -> None:
    assert normalize("anthropic", in_choice) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OpenAI — string or flat dict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "in_choice,expected",
    [
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ("any", "required"),
        ({"type": "auto"}, "auto"),
        ({"type": "required"}, "required"),
        ({"type": "any"}, "required"),
        ({"type": "function", "name": "web_search"}, {"type": "function", "name": "web_search"}),
        ({"name": "calculator"}, {"type": "function", "name": "calculator"}),
        ({"function": {"name": "lookup"}}, {"type": "function", "name": "lookup"}),
    ],
)
def test_openai_normalize(in_choice: object, expected: object) -> None:
    assert normalize("openai", in_choice) == expected  # type: ignore[arg-type]


def test_openai_codex_alias() -> None:
    """``codex`` provider routes through the OpenAI Responses shape."""
    assert normalize("codex", "any") == "required"
    assert normalize("codex", {"name": "search"}) == {"type": "function", "name": "search"}


# ---------------------------------------------------------------------------
# GLM — string or nested-function dict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "in_choice,expected",
    [
        ("auto", "auto"),
        ("none", "none"),
        ("required", "required"),
        ("any", "required"),
        ({"type": "auto"}, "auto"),
        ({"type": "required"}, "required"),
        ({"type": "any"}, "required"),
        (
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "web_search"}},
        ),
        (
            {"name": "calculator"},
            {"type": "function", "function": {"name": "calculator"}},
        ),
    ],
)
def test_glm_normalize(in_choice: object, expected: object) -> None:
    assert normalize("glm", in_choice) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_none_passthrough() -> None:
    """A caller passing ``None`` (no preference) round-trips as None for all
    providers — the adapter then omits ``tool_choice`` entirely.
    """
    for p in ("anthropic", "openai", "codex", "glm"):
        assert normalize(p, None) is None


def test_unknown_provider_returns_input_unchanged() -> None:
    """Unknown providers must not crash existing callers; they receive the
    canonical input unchanged so the caller can decide a fallback.
    """
    assert normalize("future-provider", "auto") == "auto"
    assert normalize("future-provider", {"name": "X"}) == {"name": "X"}


def test_case_insensitive_provider() -> None:
    """Provider lookup is case-insensitive — accidental capitalization in
    config files should not silently bypass normalization.
    """
    assert normalize("Anthropic", "required") == {"type": "any"}
    assert normalize("OPENAI", "any") == "required"
    assert normalize("GLM", "any") == "required"

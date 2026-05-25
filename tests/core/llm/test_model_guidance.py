"""Hermes Phase 2 — ``core.llm.model_guidance`` invariants.

Pins the family resolution heuristic, the ``<model_guidance>`` block
shape, and the graceful no-op for unrecognised models.
"""

from __future__ import annotations

import pytest
from core.llm.model_guidance import (
    FAMILY_ANTHROPIC,
    FAMILY_GOOGLE,
    FAMILY_OPENAI,
    FAMILY_XAI,
    MODEL_GUIDANCE,
    VALID_FAMILIES,
    render_model_guidance,
    resolve_family,
)

from core.llm import model_guidance


def test_four_canonical_families_covered():
    expected = {FAMILY_ANTHROPIC, FAMILY_OPENAI, FAMILY_GOOGLE, FAMILY_XAI}
    assert expected == VALID_FAMILIES
    assert set(MODEL_GUIDANCE) == expected, "every family must have a guidance body"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-opus-4-7", FAMILY_ANTHROPIC),
        ("claude-sonnet-4-6", FAMILY_ANTHROPIC),
        ("claude-haiku-4-5-20251001", FAMILY_ANTHROPIC),
        ("opus-4.7", FAMILY_ANTHROPIC),
        ("gpt-5", FAMILY_OPENAI),
        ("gpt-4o-mini", FAMILY_OPENAI),
        ("o3-mini", FAMILY_OPENAI),
        ("o1-preview", FAMILY_OPENAI),
        ("o4", FAMILY_OPENAI),
        ("codex-cli", FAMILY_OPENAI),
        ("gemini-2.5-pro", FAMILY_GOOGLE),
        ("grok-4", FAMILY_XAI),
    ],
)
def test_resolve_family_known(model: str, expected: str):
    assert resolve_family(model) == expected


def test_resolve_family_case_insensitive():
    assert resolve_family("CLAUDE-OPUS-4-7") == FAMILY_ANTHROPIC
    assert resolve_family("GPT-5") == FAMILY_OPENAI


def test_resolve_family_unknown_returns_none():
    assert resolve_family("mistral-large") is None
    assert resolve_family("") is None


def test_render_returns_xml_block_for_each_family():
    for family in VALID_FAMILIES:
        sample = next(
            iter(
                [
                    m
                    for m, f in {
                        "claude-opus-4-7": FAMILY_ANTHROPIC,
                        "gpt-5": FAMILY_OPENAI,
                        "gemini-2.5-pro": FAMILY_GOOGLE,
                        "grok-4": FAMILY_XAI,
                    }.items()
                    if f == family
                ]
            )
        )
        block = render_model_guidance(sample)
        assert block.startswith("<model_guidance"), f"family={family}"
        assert block.rstrip().endswith("</model_guidance>"), f"family={family}"
        assert MODEL_GUIDANCE[family] in block, f"family={family} body missing"


def test_render_unknown_returns_empty_string():
    assert render_model_guidance("mistral-large") == ""
    assert render_model_guidance("") == ""


def test_module_exports_stable():
    expected = {
        "FAMILY_ANTHROPIC",
        "FAMILY_GOOGLE",
        "FAMILY_OPENAI",
        "FAMILY_XAI",
        "MODEL_GUIDANCE",
        "VALID_FAMILIES",
        "resolve_family",
        "render_model_guidance",
    }
    assert set(model_guidance.__all__) == expected

"""Hermes Phase 2 — system_prompt wiring invariants.

Pins that ``build_system_prompt`` actually appends ``<platform_hint>``
and ``<model_guidance>`` blocks when the resolved surface / family is
known, and that audit-mode keeps emitting the minimal prompt without
either block (Petri scenarios must not see GEODE-side surface hints).
"""

from __future__ import annotations

import pytest
from core.llm.platform_hints import (
    GEODE_SURFACE_TYPE_ENV,
    SURFACE_SLACK,
)

from core.agent import system_prompt


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GEODE_SURFACE_TYPE_ENV, raising=False)
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    monkeypatch.delenv("GEODE_PERSONA", raising=False)


def test_platform_hint_block_appears_under_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, SURFACE_SLACK)
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    assert "<platform_hint surface='slack'>" in prompt


def test_model_guidance_block_appears_for_known_family(monkeypatch: pytest.MonkeyPatch):
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    assert "<model_guidance family='anthropic'>" in prompt


def test_model_guidance_omitted_for_unknown_model(monkeypatch: pytest.MonkeyPatch):
    prompt = system_prompt.build_system_prompt(model="mistral-large")
    assert "<model_guidance" not in prompt


def test_unknown_env_surface_falls_through_to_cli_block(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, "telegram")
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    # Unknown env value → fall-through to default "cli", which is mapped → block appears.
    assert "<platform_hint surface='cli'>" in prompt
    assert "<platform_hint surface='telegram'>" not in prompt


def test_audit_mode_strips_both_blocks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
    monkeypatch.setenv(GEODE_SURFACE_TYPE_ENV, SURFACE_SLACK)
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    assert "<platform_hint" not in prompt, "Petri audit mode must not leak surface hints"
    assert "<model_guidance" not in prompt, "Petri audit mode must not leak family hints"


def test_default_cli_surface_when_env_unset():
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    assert "<platform_hint surface='cli'>" in prompt


def test_order_model_guidance_before_platform_hint():
    """The dynamic section appends in order: model_card → model_guidance →
    platform_hint → date. Pin that order so future re-arrangements
    surface in tests."""
    prompt = system_prompt.build_system_prompt(model="claude-opus-4-7")
    mg = prompt.find("<model_guidance")
    ph = prompt.find("<platform_hint")
    assert mg != -1 and ph != -1
    assert mg < ph, "model_guidance must precede platform_hint in dynamic section"

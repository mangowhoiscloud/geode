"""Guard: the GEODE.md behavioral sections actually reach the G1 system-prompt
layer. GEODE.md is parsed by EXACT section header in
``_build_identity_context``; a future header rename would silently disconnect
the SOUL's behavioral half from the runtime (it nearly did when "Core
Principles" → "Operating Principles" + "Voice & Conduct" was added). This pins
that the behavioral sections are injected and the numeric Defaults are not.
"""

from __future__ import annotations

from core.agent.system_prompt import _build_identity_context


def test_behavioral_sections_injected_into_g1() -> None:
    out = _build_identity_context()
    assert out, "G1 identity context is empty — GEODE.md not loaded?"
    # the behavioral half must be present
    assert "Voice & Conduct" in out
    assert "Operating Principles" in out
    assert "RUNTIME CANNOT" in out
    # a few concrete behavioral directives must survive the extraction
    assert "Warm without flattery" in out
    assert "Persistent" in out
    assert "decline like a person" in out


def test_numeric_defaults_not_injected_into_g1() -> None:
    # the Defaults section is reference, not behavioral identity — it must NOT
    # pollute every system prompt.
    out = _build_identity_context()
    assert "Circuit breaker" not in out
    assert "Session TTL" not in out


def test_cross_reference_blockquotes_stripped() -> None:
    # `> see CLAUDE.md …` author notes are not runtime directives.
    out = _build_identity_context()
    assert "see `CLAUDE.md`" not in out
    assert "development-time guardrails" not in out

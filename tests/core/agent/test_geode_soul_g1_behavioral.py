"""Guard: the GEODE.md behavioral sections actually reach the G1 system-prompt
layer. GEODE.md is parsed by EXACT section header in
``_build_identity_context``; a future header rename would silently disconnect
the SOUL's behavioral half from the runtime (it nearly did when "Core
Principles" → "Operating Principles" + "Voice & Conduct" was added). This pins
that the behavioral sections are injected and the numeric Defaults are not.
"""

from __future__ import annotations

import pytest
from core.agent.system_prompt import _build_identity_context, build_system_prompt
from core.memory.organization import MonoLakeOrganizationMemory


@pytest.mark.parametrize(
    "persona,audit,expected",
    [("on", False, True), ("off", False, False), ("on", True, False)],
)
def test_behavioral_sections_injected_into_g1(
    monkeypatch: pytest.MonkeyPatch, persona: str, audit: bool, expected: bool
) -> None:
    monkeypatch.setenv("GEODE_PERSONA", persona)
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1" if audit else "0")
    out = build_system_prompt()
    assert ("<agent_identity>" in out) is expected
    if not expected:
        return

    identity = out.split("<agent_identity>\n", 1)[1].split("\n</agent_identity>", 1)[0]
    soul = MonoLakeOrganizationMemory().get_soul()
    for title in ("Identity", "Voice & Conduct", "Operating Principles", "RUNTIME CANNOT"):
        body = soul.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]
        # Every authored directive must survive the identity budget and assembly,
        # not just the section headings or selected phrases.
        directives = [
            line for line in body.splitlines() if line.strip() and not line.startswith(">")
        ]
        assert directives, title
        for line in directives:
            assert line in identity
    assert out.index("</agent_identity>") < out.index("<dynamic_context>")


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

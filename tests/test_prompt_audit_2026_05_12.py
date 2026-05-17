"""Regression guards for the 2026-05-12 prompt audit (G1-G12).

Each test pins a specific behaviour discovered or established by the audit:

* G2: petri runner no longer caps max_rounds at 4.
* G3 + G10: GEODE_AUDIT_UNRESTRICTED=1 strips identity / memory / user
  context; GEODE_PERSONA=on opts back into the GEODE identity layer.
* G9: ``_sanitize_learned_pattern`` strips the ``[context: ...]`` trailer
  so prior-turn user transcripts no longer leak into every system prompt.
* G1: ``_load_template`` parses ``<key>...</key>`` XML sections (not the
  prior ``=== KEY ===`` delimiter).
"""

from __future__ import annotations

import pytest
from core.agent.system_injection import prepend_system_reminder
from core.agent.system_prompt import (
    _audit_mode_active,
    _persona_on,
    _sanitize_learned_pattern,
    build_system_prompt,
)
from core.llm.prompts import _load_template

# ---------------------------------------------------------------------------
# G9 — learned-pattern context-leak sanitize
# ---------------------------------------------------------------------------


def test_g9_sanitize_strips_context_trailer() -> None:
    raw = (
        "- [2026-05-07] [validation] Validated: 좋아. 2번 플랜 실행 부탁해. "
        "[context: 수집 완료. 추천/비전/모델학습 중심을 제외하고 LLM 자율 에이전트 ...]"
    )
    out = _sanitize_learned_pattern(raw)
    assert "[context:" not in out
    assert "Validated: 좋아" in out


def test_g9_sanitize_caps_long_prefix() -> None:
    long = "a" * 200
    out = _sanitize_learned_pattern(long)
    assert len(out) <= 120
    assert out.endswith("...")


def test_g9_sanitize_passes_through_short_clean_line() -> None:
    clean = "- [2026-05-07] [tool_usage] Frequently uses web_fetch"
    out = _sanitize_learned_pattern(clean)
    assert out == clean


# ---------------------------------------------------------------------------
# G3 — audit-mode strips GEODE-specific layers
# ---------------------------------------------------------------------------


def test_g3_audit_mode_strips_identity_memory_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
    monkeypatch.delenv("GEODE_PERSONA", raising=False)
    out = build_system_prompt(model="claude-opus-4-7")
    assert "<agent_identity>" not in out
    assert "<project_memory>" not in out
    assert "<agent_learning>" not in out
    assert "<user_context>" not in out
    assert "<runtime_rules>" not in out
    # Model card + date remain (auditor needs to see the target model).
    assert "<model_card>" in out
    assert "<current_date>" in out
    assert "<dynamic_context>" in out


def test_g3_audit_mode_supersedes_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit-mode forces persona OFF regardless of GEODE_PERSONA."""
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
    monkeypatch.setenv("GEODE_PERSONA", "on")
    assert _audit_mode_active() is True
    assert _persona_on() is False
    out = build_system_prompt(model="claude-opus-4-7")
    assert "<agent_identity>" not in out


# ---------------------------------------------------------------------------
# G10 — GEODE identity is opt-in
# ---------------------------------------------------------------------------


def test_g10_persona_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_PERSONA", raising=False)
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    assert _persona_on() is False


def test_g10_persona_on_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    for val in ("on", "1", "true", "TRUE", "On"):
        monkeypatch.setenv("GEODE_PERSONA", val)
        assert _persona_on() is True, f"expected on for {val!r}"


def test_g10_router_md_no_geode_name_in_baseline() -> None:
    """G11 — the router.md baseline must NOT carry 'You are GEODE'.

    The GEODE-identity assertion now lives only in the opt-in
    <agent_identity> layer (G10), so the baseline reads neutrally.
    """
    from core.llm.prompts import ROUTER_SYSTEM

    assert "You are GEODE" not in ROUTER_SYSTEM
    assert "autonomous execution agent" in ROUTER_SYSTEM


def test_sandwich_system_reminder_uses_xml_tags() -> None:
    messages = [{"role": "user", "content": "hello"}]
    out = prepend_system_reminder(messages, round_idx=1)
    assert out[0]["content"].startswith("<system-reminder>")
    assert out[0]["content"].endswith("</system-reminder>")
    assert "[system-reminder]" not in out[0]["content"]


def test_math_formatting_instruction_reaches_agentic_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interactive CLI prompt path tells the model to delimit math."""
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    monkeypatch.delenv("GEODE_PERSONA", raising=False)

    out = build_system_prompt(model="")

    assert "<math_formatting>" in out
    assert "Inline math: wrap with `$...$`" in out
    assert "Display math: put `$$...$$` on its own lines" in out


# ---------------------------------------------------------------------------
# G1 — XML section parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected_keys",
    [
        ("analyst", {"system", "user"}),
        ("commentary", {"system", "user"}),
        ("cross_llm", {"system", "rescore", "dual_verify"}),
        ("decomposer", {"system"}),
        ("evaluator", {"system", "user"}),
        ("router", {"system", "agentic_suffix"}),
        ("synthesizer", {"system", "user"}),
        ("tool_augmented", {"analyst_tools", "synthesizer_tools"}),
    ],
)
def test_g1_xml_template_parses(name: str, expected_keys: set[str]) -> None:
    sections = _load_template(name)
    assert set(sections.keys()) == expected_keys, (
        f"{name}.md: parsed {set(sections.keys())} vs expected {expected_keys}"
    )
    for key, body in sections.items():
        assert body, f"{name}.md::{key} body is empty after XML parse"


def test_g1_no_legacy_equals_marker_left() -> None:
    """No ``=== KEY ===`` delimiter should remain in the .md templates."""
    from pathlib import Path

    prompt_dir = Path(__file__).resolve().parent.parent / "core" / "llm" / "prompts"
    for md in sorted(prompt_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        legacy = [
            ln
            for ln in text.splitlines()
            if ln.strip().startswith("===") and ln.strip().endswith("===")
        ]
        assert not legacy, f"{md.name} still contains legacy ``=== KEY ===``: {legacy}"


# ---------------------------------------------------------------------------
# G2 — petri runner unlimited rounds
# ---------------------------------------------------------------------------


def test_g2_petri_runner_no_max_rounds_cap() -> None:
    """``_default_geode_runner`` constructs ``AgenticLoop`` without ``max_rounds`` kwarg.

    Source check rather than runtime — the petri runner is async-bootstrapped
    and the cap was the literal keyword argument in the call site. Strip
    comments before grepping so the regression marker in the surrounding
    explanation doesn't mask the actual kwarg.
    """
    import inspect

    from plugins.petri_audit.targets import geode_target

    src = inspect.getsource(geode_target._default_geode_runner)
    code_only = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "max_rounds" not in code_only, (
        "G2 regression: petri runner reintroduced a max_rounds keyword. "
        "AgenticLoop's DEFAULT_MAX_ROUNDS=0 (unlimited) is the correct default."
    )

"""Regression pin for the self-improving loop's scaffold→audit causal link.

PR-AUDIT-SCAFFOLD-WIRE (2026-05-31) — the Petri audit target is GEODE itself
(``GeodeModelAPI`` → ``_default_geode_runner`` → ``AgenticLoop``). The loop's
fitness signal is only causal if the MUTATED scaffold
(``autoresearch/state/policies/wrapper-sections.json``, surfaced to the audit
subprocess via the ``GEODE_WRAPPER_OVERRIDE`` env hook) is the BASE of the
target's internal system prompt, with the auditor's seed scenario layered on
top as ``system_suffix``.

The disconnect this guards against: ``inspect_ai``'s ``.eval`` ModelEvent only
records the messages Petri passed to ``GeodeModelAPI.generate`` (the seed
scenario), NOT the prompt ``AgenticLoop`` builds internally — so reading the
archive alone makes it look like the scaffold is absent. These tests exercise
the real prompt-build path (``_split_messages`` → ``AgenticLoop`` →
``core.agent.loop._context.build_system_prompt``) with the LLM call mocked, and
assert that a unique marker placed in ``wrapper-sections.json`` reaches the
prompt the loop would send to the underlying model, AND that the auditor's
scenario is still present.

These tests deliberately avoid importing ``inspect_ai`` (the ``[audit]`` extra
is not in the default test env) — the ``geode_target`` module-level surface
(``_split_messages`` / ``_default_geode_runner``) is import-free, and the LLM
call is patched out, so the test runs under a plain ``uv sync``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

# Unique markers so a false positive (the marker happening to appear in the
# generic router prefix) is impossible.
SCAFFOLD_MARKER = "UNIQUE_SCAFFOLD_MARKER_ZX9Q7"
SCENARIO_MARKER = "AUDITOR_SCENARIO_MARKER_DANA_4F1"


def _capture_internal_prompt(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auditor_messages: list[dict[str, Any]],
    model: str = "gpt-5.5",
) -> str:
    """Run ``_default_geode_runner`` with the LLM mocked; return the prompt.

    Patches ``AgenticLoop.arun`` to build the system prompt (the exact code
    path the live audit hits) and capture it instead of making an LLM call.
    Returns the captured internal system prompt string.
    """
    from core.agent.loop import agent_loop as al
    from plugins.petri_audit.targets.geode_target import _default_geode_runner

    captured: dict[str, str] = {}

    async def _fake_arun(self: Any, user_input: str) -> Any:
        captured["prompt"] = self._build_system_prompt()
        from core.agent.loop.agent_loop import AgenticResult

        return AgenticResult(text="ok", rounds=0, termination_reason="end_turn")

    monkeypatch.setattr(al.AgenticLoop, "arun", _fake_arun)

    asyncio.run(_default_geode_runner(auditor_messages, model=model))
    return captured["prompt"]


def _write_marked_scaffold(tmp_path: Path) -> Path:
    """Write a wrapper-sections JSON carrying the unique scaffold marker."""
    scaffold = {
        "role": "You operate as GEODE, an autonomous execution agent.",
        "refusal_policy": "Refuse only when clearly harmful.",
        "marker": SCAFFOLD_MARKER,
    }
    sot = tmp_path / "wrapper-override.json"
    sot.write_text(json.dumps(scaffold), encoding="utf-8")
    return sot


def _auditor_messages() -> list[dict[str, Any]]:
    """The GEODE-shaped messages Petri stages: system=scenario, then user."""
    return [
        {
            "role": "system",
            "content": (f"You are Dana's executive scheduling assistant. {SCENARIO_MARKER}"),
        },
        {"role": "user", "content": "Do I have a conflict at 15:00 today?"},
    ]


def test_split_messages_routes_scenario_to_system_suffix() -> None:
    """The auditor's system scenario becomes ``system_suffix`` (the prefix
    slot is reserved for the GEODE scaffold)."""
    from plugins.petri_audit.targets.geode_target import _split_messages

    system_suffix, history, last_user = _split_messages(_auditor_messages())
    assert SCENARIO_MARKER in system_suffix
    assert last_user == "Do I have a conflict at 15:00 today?"
    assert history == []


def test_mutated_scaffold_reaches_target_prompt_via_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Closed-loop condition (``train.py`` sets ``GEODE_WRAPPER_OVERRIDE``):
    the mutated scaffold marker AND the auditor scenario both reach the
    target's internal system prompt. This is the regression pin for the
    causal disconnect — if a future change drops the scaffold base, the
    marker disappears and this test fails."""
    sot = _write_marked_scaffold(tmp_path)
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(sot))
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    # Force dry-run readiness so no live LLM call is attempted even if the
    # arun patch were bypassed.
    monkeypatch.setenv("GEODE_FORCE_DRY_RUN", "1")

    prompt = _capture_internal_prompt(monkeypatch, auditor_messages=_auditor_messages())

    assert SCAFFOLD_MARKER in prompt, "mutated scaffold absent from audit target prompt"
    assert SCENARIO_MARKER in prompt, "auditor scenario absent from audit target prompt"


def test_mutated_scaffold_reaches_target_prompt_via_sot_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Standalone-audit condition (no ``GEODE_WRAPPER_OVERRIDE`` env): the
    env-less SoT-file fallback still injects the scaffold. Pins that the
    standalone ``geode audit`` path is NOT scaffold-free when the in-repo SoT
    exists."""
    import core.agent.system_prompt as sp

    sot = _write_marked_scaffold(tmp_path)
    monkeypatch.delenv("GEODE_WRAPPER_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)
    monkeypatch.setenv("GEODE_FORCE_DRY_RUN", "1")
    # Point the module-local SoT alias at our marked file (tests are allowed
    # to monkeypatch this alias per the constant's docstring).
    monkeypatch.setattr(sp, "_WRAPPER_SECTIONS_SOT_PATH", sot)

    prompt = _capture_internal_prompt(monkeypatch, auditor_messages=_auditor_messages())

    assert SCAFFOLD_MARKER in prompt
    assert SCENARIO_MARKER in prompt


def test_audit_mode_falls_back_to_generic_base_when_no_scaffold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PR-AUDIT-SCAFFOLD-WIRE fix: in audit-mode with NO scaffold available
    (env unset + SoT absent), ``build_system_prompt`` must still emit the
    domain-neutral GEODE base prefix — NOT an empty static section. Pre-fix
    this branch returned only dynamic context, producing a scaffold-free
    target (the genuine causal-disconnect path Codex flagged)."""
    import core.agent.system_prompt as sp

    monkeypatch.delenv("GEODE_WRAPPER_OVERRIDE", raising=False)
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
    monkeypatch.setattr(sp, "_WRAPPER_SECTIONS_SOT_PATH", tmp_path / "does-not-exist.json")

    prompt = sp.build_system_prompt(model="gpt-5.5")

    # The generic router prefix substitutes ``ip_count`` / ``ip_examples``;
    # the presence of the dynamic cache boundary + a non-trivial static body
    # before it proves the base scaffold is present.
    assert sp.PROMPT_CACHE_BOUNDARY in prompt
    static_part = prompt.split(sp.PROMPT_CACHE_BOUNDARY, 1)[0].strip()
    assert len(static_part) > 0, "audit-mode prompt has an empty scaffold base"


def test_one_shot_exercises_system_prompt_level_kinds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Document + pin the EFFECTIVE optimizable surface of a one-shot audit.

    The one-shot audit target builds its system prompt once per turn via
    ``build_system_prompt`` + the loop-level skill/tool context, so the
    system-prompt-level scaffold kinds (prompt / tool_policy /
    tool_descriptions / reflection-as-prompt-hint / skill_catalog / style /
    heuristics) are EXERCISED — they shape the prompt the target receives.
    Multi-step behavioural kinds (e.g. decomposition planning, multi-round
    reflection loops) may not fully manifest in a short audit, but the
    prompt-level injection point is always hit.

    This test pins that the wrapper-sections (``prompt`` kind) injection is
    on the exercised path by asserting the marker reaches the prompt — the
    same assertion as the env-override test, framed as the surface contract.
    """
    sot = _write_marked_scaffold(tmp_path)
    monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(sot))
    monkeypatch.setenv("GEODE_FORCE_DRY_RUN", "1")
    monkeypatch.delenv("GEODE_AUDIT_UNRESTRICTED", raising=False)

    prompt = _capture_internal_prompt(monkeypatch, auditor_messages=_auditor_messages())
    assert SCAFFOLD_MARKER in prompt

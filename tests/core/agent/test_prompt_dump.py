"""Assembled-prompt dump guards (PR-PROMPT-DUMP, prompt-refactor P0).

Content-independent pins: machine state (memory files, user profile)
varies, so these assert STRUCTURE — placeholder collapse, suffix
presence, single cache boundary, ordering — not bytes.
"""

from __future__ import annotations

from core.agent.prompt_dump import (
    DUMP_SURFACES,
    SKILL_EMPTY_MARKER,
    analyze_prompt,
    assemble_full_prompt,
    dump_matrix,
)
from core.llm.prompts import AGENTIC_SUFFIX


def test_assembled_prompt_matches_loop_composition_contract() -> None:
    prompt = assemble_full_prompt("claude-opus-4-8", "cli")
    assert "{skill_context}" not in prompt, "placeholder must collapse to the empty marker"
    assert SKILL_EMPTY_MARKER in prompt
    assert prompt.endswith(AGENTIC_SUFFIX), "agentic suffix appended last, loop-identical"
    assert prompt.count("<dynamic_context>") == 1, "exactly one cache boundary"
    # static layers must precede the dynamic (cache) boundary
    boundary_at = prompt.index("<dynamic_context>")
    assert prompt.index("<math_formatting>") < boundary_at
    # per-call layers live after the boundary
    assert prompt.index("<current_date>") > boundary_at


def test_surface_pin_reaches_platform_hint() -> None:
    cli_prompt = assemble_full_prompt("claude-opus-4-8", "cli")
    slack_prompt = assemble_full_prompt("claude-opus-4-8", "slack")
    assert "surface='cli'" in cli_prompt
    assert "surface='slack'" in slack_prompt


def test_surface_env_is_restored() -> None:
    import os

    sentinel = os.environ.get("GEODE_SURFACE_TYPE")
    assemble_full_prompt("claude-opus-4-8", "worktree")
    assert os.environ.get("GEODE_SURFACE_TYPE") == sentinel


def test_analyze_prompt_flags_duplicate_sections() -> None:
    tags, duplicates = analyze_prompt("<alpha>\nx\n</alpha>\n<beta>\n<alpha>\ny\n</alpha>")
    assert tags == ("alpha", "beta", "alpha")
    assert duplicates == ("alpha",)


def test_dump_matrix_writes_cells(tmp_path) -> None:
    dump_dir = tmp_path / "cells"
    rows = dump_matrix(("claude-opus-4-8",), ("cli",), out_dir=dump_dir, measure=False)
    assert len(rows) == 1
    cell = rows[0]
    assert cell.path.is_file()
    assert cell.chars == len(cell.path.read_text(encoding="utf-8"))
    assert cell.est_tokens == cell.chars // 4, "without --measure the figure is the estimate"
    assert cell.surface in DUMP_SURFACES

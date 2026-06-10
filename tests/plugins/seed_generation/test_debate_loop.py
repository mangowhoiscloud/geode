"""Loop 2 (debate-turn) tests — CSP-13 of the 3-loop port.

Covers the two surfaces introduced by PR-CSP-13:

1. ``plugins.seed_generation.tools.seed_debate.SeedDebateTurnTool`` — bounds, sidecar
   shape, next_action signaling, defensive arg validation.
2. ``plugins.seed_generation.agents.generator.Generator`` — backwards
   compatibility for ``num_turns=0`` (single-shot path unchanged),
   sidecar-read merge for ``num_turns>=2``, ``_build_description``
   debate-budget block injection.

The tests deliberately use synthetic sidecars on disk + a stub
``SubAgentManager``. No live LLM calls.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from plugins.seed_generation.agents.generator import Generator, _read_debate_sidecars
from plugins.seed_generation.orchestrator import PipelineState
from plugins.seed_generation.tools.seed_debate import SeedDebateTurnTool

# ── SeedDebateTurnTool ────────────────────────────────────────────────────


def _make_paths(
    tmp_path: Path, candidate_id: str = "gen2-000-abc", monkeypatch: Any = None
) -> tuple[Path, Path]:
    """Build (output_path, sidecar_path) under a synthetic GEODE_HOME.

    Tests use ``monkeypatch`` (when provided) to retarget
    ``core.paths.GEODE_HOME`` at ``tmp_path`` so the tool's containment
    check passes for tmp_path sidecars. When ``monkeypatch`` is omitted
    the paths still satisfy the suffix / directory checks but the
    runtime-root containment may fail — callers should provide it.
    """
    if monkeypatch is not None:
        monkeypatch.setattr("core.paths.GEODE_HOME", tmp_path)
    output_path = tmp_path / "candidates" / f"{candidate_id}.md"
    sidecar_path = output_path.with_suffix(".debate.jsonl")
    return output_path, sidecar_path


def _call_tool(tool: SeedDebateTurnTool, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(tool.aexecute(**kwargs))


def test_seed_debate_turn_records_turn_and_returns_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-budget turn returns next_action='continue' + appends to sidecar."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="Proponent claim.",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=3,
    )
    assert payload["result"]["ok"] is True
    assert payload["result"]["turn"] == 1
    assert payload["result"]["max_turns"] == 3
    assert payload["result"]["next_action"] == "continue"
    # Sidecar JSONL is appended; one line per turn.
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["turn"] == 1
    assert entry["speaker"] == "A"
    assert entry["content"] == "Proponent claim."
    assert "ts" in entry


def test_seed_debate_turn_signals_synthesize_on_final_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``turn == max_turns`` flips next_action to 'synthesize'."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    # Pre-write turn 1 so the sequential check accepts turn 2.
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        '{"turn": 1, "speaker": "A", "content": "x", "ts": "2026-05-23T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    payload = _call_tool(
        tool,
        turn=2,
        speaker="B",
        content="Critic rebuttal.",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is True
    assert payload["result"]["next_action"] == "synthesize"


def test_seed_debate_turn_rejects_turn_out_of_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``turn > max_turns`` must error — the LLM cannot silently overshoot."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    payload = _call_tool(
        tool,
        turn=5,
        speaker="A",
        content="too late",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=3,
    )
    assert payload["result"]["ok"] is False
    assert payload["result"]["next_action"] == "abort"
    assert "turn=5" in payload["result"]["error"]
    assert not sidecar.exists()


def test_seed_debate_turn_rejects_max_turns_below_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``max_turns < 2`` is rejected — a 1-turn debate is meaningless."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="solo",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=1,
    )
    assert payload["result"]["ok"] is False
    assert "max_turns=1" in payload["result"]["error"]


def test_seed_debate_turn_rejects_max_turns_above_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``max_turns > 6`` is rejected — caps per-candidate cost."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="x",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=7,
    )
    assert payload["result"]["ok"] is False
    assert "max_turns=7" in payload["result"]["error"]


def test_seed_debate_turn_rejects_non_debate_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sidecar path that doesn't match output_path transformation is refused."""
    tool = SeedDebateTurnTool()
    output, _ = _make_paths(tmp_path, monkeypatch=monkeypatch)
    bad_sidecar = tmp_path / "candidates" / "gen2-000.txt"
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="x",
        output_path=str(output),
        sidecar_path=str(bad_sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    # Mismatch error wins before suffix check fires.
    assert "expected" in payload["result"]["error"]


def test_seed_debate_turn_rejects_non_candidates_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sidecar parent must be a 'candidates' dir — guards against arbitrary writes."""
    tool = SeedDebateTurnTool()
    monkeypatch.setattr("core.paths.GEODE_HOME", tmp_path)
    # Construct an output_path under tmp_path/elsewhere/ so the
    # sidecar's parent is 'elsewhere' not 'candidates'. Sidecar
    # derivation matches output_path exactly so it passes the
    # mismatch check, then fails on the parent-name check.
    output = tmp_path / "elsewhere" / "gen2-000.md"
    sidecar = output.with_suffix(".debate.jsonl")
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="x",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    assert "candidates" in payload["result"]["error"]


def test_seed_debate_turn_rejects_escape_from_geode_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sidecar resolving outside GEODE_HOME is refused (containment)."""
    tool = SeedDebateTurnTool()
    # GEODE_HOME points at a separate dir; sidecar tries to write
    # into tmp_path/candidates/ which is OUTSIDE that root.
    geode_root = tmp_path / "geode_root"
    geode_root.mkdir()
    monkeypatch.setattr("core.paths.GEODE_HOME", geode_root)
    output = tmp_path / "candidates" / "esc.md"
    sidecar = output.with_suffix(".debate.jsonl")
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="x",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    assert "outside" in payload["result"]["error"]


def test_seed_debate_turn_enforces_sequential_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling turn=N before writing turn=N-1 is rejected (anti-skip guard)."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    # Empty sidecar — calling turn=2 directly should fail.
    payload = _call_tool(
        tool,
        turn=2,
        speaker="B",
        content="skipping ahead",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=3,
    )
    assert payload["result"]["ok"] is False
    assert "skip" in payload["result"]["error"] or "expected" in payload["result"]["error"]
    assert not sidecar.exists()


def test_seed_debate_turn_rejects_empty_speaker_or_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty fields are caught — otherwise the sidecar would carry useless rows."""
    tool = SeedDebateTurnTool()
    output, sidecar = _make_paths(tmp_path, monkeypatch=monkeypatch)
    payload = _call_tool(
        tool,
        turn=1,
        speaker="",
        content="x",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    assert "speaker" in payload["result"]["error"]
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="",
        output_path=str(output),
        sidecar_path=str(sidecar),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    assert "content" in payload["result"]["error"]


def test_seed_debate_turn_rejects_mismatched_output_sidecar_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sidecar_path that doesn't match output_path[:-3]+'.debate.jsonl' is refused."""
    tool = SeedDebateTurnTool()
    monkeypatch.setattr("core.paths.GEODE_HOME", tmp_path)
    output = tmp_path / "candidates" / "a.md"
    # Sidecar names a different candidate — mismatch must be caught.
    mismatched = tmp_path / "candidates" / "b.debate.jsonl"
    payload = _call_tool(
        tool,
        turn=1,
        speaker="A",
        content="x",
        output_path=str(output),
        sidecar_path=str(mismatched),
        max_turns=2,
    )
    assert payload["result"]["ok"] is False
    assert "expected" in payload["result"]["error"]


def test_self_improving_loop_bindings_num_turns_validator() -> None:
    """Operator-config slot enforces same {0} ∪ [2,6] window as manifest (Codex MEDIUM)."""
    from core.config.self_improving import SelfImprovingLoopBindings

    SelfImprovingLoopBindings(model="x", source="auto", num_turns=0)
    SelfImprovingLoopBindings(model="x", source="auto", num_turns=2)
    SelfImprovingLoopBindings(model="x", source="auto", num_turns=6)
    with pytest.raises(ValueError, match="num_turns"):
        SelfImprovingLoopBindings(model="x", source="auto", num_turns=1)
    with pytest.raises(ValueError, match="num_turns"):
        SelfImprovingLoopBindings(model="x", source="auto", num_turns=7)


# ── _read_debate_sidecars helper ───────────────────────────────────────────


def test_read_debate_sidecars_parses_jsonl(tmp_path: Path) -> None:
    """The helper turns per-candidate sidecars into the state-shaped dict."""
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    candidate_id = "gen2-001-abc"
    md_path = candidates_dir / f"{candidate_id}.md"
    md_path.write_text("# seed body\n", encoding="utf-8")
    sidecar = candidates_dir / f"{candidate_id}.debate.jsonl"
    sidecar.write_text(
        '{"turn": 1, "speaker": "A", "content": "proponent", "ts": "2026-05-23T00:00:00+00:00"}\n'
        '{"turn": 2, "speaker": "B", "content": "critic", "ts": "2026-05-23T00:00:01+00:00"}\n',
        encoding="utf-8",
    )
    transcripts = _read_debate_sidecars(
        [{"id": candidate_id, "path": str(md_path)}],
    )
    assert candidate_id in transcripts
    assert len(transcripts[candidate_id]) == 2
    assert transcripts[candidate_id][0]["speaker"] == "A"
    assert transcripts[candidate_id][1]["speaker"] == "B"


def test_read_debate_sidecars_skips_missing(tmp_path: Path) -> None:
    """Candidates without a sidecar produce no transcript entry — defensive."""
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    md_path = candidates_dir / "gen2-001.md"
    md_path.write_text("# no debate\n", encoding="utf-8")
    transcripts = _read_debate_sidecars(
        [{"id": "gen2-001", "path": str(md_path)}],
    )
    assert transcripts == {}


def test_read_debate_sidecars_tolerates_malformed_lines(tmp_path: Path) -> None:
    """Bad JSONL lines are dropped silently; valid ones survive."""
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    candidate_id = "gen2-002"
    md_path = candidates_dir / f"{candidate_id}.md"
    md_path.write_text("# seed\n", encoding="utf-8")
    sidecar = candidates_dir / f"{candidate_id}.debate.jsonl"
    sidecar.write_text(
        '{"turn": 1, "speaker": "A", "content": "ok"}\n'
        "not json at all\n"
        '{"turn": 2, "speaker": "B", "content": "still ok"}\n',
        encoding="utf-8",
    )
    transcripts = _read_debate_sidecars(
        [{"id": candidate_id, "path": str(md_path)}],
    )
    assert len(transcripts[candidate_id]) == 2


# ── Generator backward-compat: num_turns=0 single-shot path ───────────────


class _StubResult:
    """Minimal stand-in for SubResult (success path)."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.success = True
        self.error = None
        self.duration_ms = 1.0


class _StubManager:
    """SubAgentManager test double — records adelegate calls and returns
    one success per task with no actual work."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def adelegate(self, tasks, announce: bool = True):  # type: ignore[no-untyped-def]
        self.calls.append(list(tasks))
        return [_StubResult(t.task_id) for t in tasks]


def _make_state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        run_id="r1",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=2,
        run_dir=tmp_path,
    )


def test_generator_num_turns_zero_skips_sidecar_read(tmp_path: Path) -> None:
    """``num_turns=0`` → no debate read, output has no ``debate_transcripts`` key."""
    manager = _StubManager()
    state = _make_state(tmp_path)
    gen = Generator(manager=manager, manifest_role={"num_turns": 0})  # type: ignore[arg-type]
    result = asyncio.run(gen.aexecute(state))
    assert result.status == "ok"
    assert "debate_transcripts" not in result.output


def test_generator_num_turns_zero_omits_debate_block_from_description(
    tmp_path: Path,
) -> None:
    """Description must not carry the debate budget block when num_turns=0."""
    manager = _StubManager()
    state = _make_state(tmp_path)
    gen = Generator(manager=manager, manifest_role={"num_turns": 0})  # type: ignore[arg-type]
    asyncio.run(gen.aexecute(state))
    [tasks] = manager.calls
    for task in tasks:
        assert "## Debate budget" not in task.description


# ── Generator num_turns>=2 path ──────────────────────────────────────────


def test_generator_num_turns_three_injects_debate_block(tmp_path: Path) -> None:
    """Each task description carries the budget + sidecar path when num_turns>=2."""
    manager = _StubManager()
    state = _make_state(tmp_path)
    gen = Generator(manager=manager, manifest_role={"num_turns": 3})  # type: ignore[arg-type]
    asyncio.run(gen.aexecute(state))
    [tasks] = manager.calls
    for task in tasks:
        assert "## Debate budget (CSP-13)" in task.description
        assert "max_turns = 3" in task.description
        # Sidecar path must end with .debate.jsonl and live in the candidates/ dir
        # so the LLM derives the right argument for seed_debate_turn.
        assert ".debate.jsonl" in task.description
        assert "/candidates/" in task.description


def test_generator_num_turns_three_reads_sidecars_into_output(tmp_path: Path) -> None:
    """When sub-agents wrote sidecars, Generator merges them into output."""
    manager = _StubManager()
    state = _make_state(tmp_path)
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    # Pre-create sidecars for both candidate slots. Generator generates
    # ids of the form ``gen2-{idx:03d}-{uuid8}``; we don't know the uuid8,
    # so write the sidecars AFTER aexecute kicks off task creation but
    # before the stub manager returns. Trick: monkeypatch the stub
    # manager's adelegate to write sidecars based on the actual task ids.
    real_adelegate = manager.adelegate

    async def _patched_adelegate(tasks, announce: bool = True):  # type: ignore[no-untyped-def]
        for task in tasks:
            candidate_id = task.args["candidate_id"]
            sidecar = candidates_dir / f"{candidate_id}.debate.jsonl"
            sidecar.write_text(
                '{"turn": 1, "speaker": "A", "content": "x"}\n'
                '{"turn": 2, "speaker": "B", "content": "y"}\n'
                '{"turn": 3, "speaker": "A", "content": "z"}\n',
                encoding="utf-8",
            )
        return await real_adelegate(tasks, announce=announce)

    manager.adelegate = _patched_adelegate  # type: ignore[method-assign]

    gen = Generator(manager=manager, manifest_role={"num_turns": 3})  # type: ignore[arg-type]
    result = asyncio.run(gen.aexecute(state))
    transcripts = result.output["debate_transcripts"]
    assert len(transcripts) == 2  # two candidates → two transcripts
    for turns in transcripts.values():
        assert len(turns) == 3
        assert [t["turn"] for t in turns] == [1, 2, 3]


# ── PipelineState merge ───────────────────────────────────────────────────


def test_pipeline_state_merge_debate_transcripts_dict_update(tmp_path: Path) -> None:
    """State merge with debate_transcripts overlays via dict.update."""
    state = _make_state(tmp_path)
    state.merge(
        "generator",
        {
            "candidates": [{"id": "c1", "path": "/x.md"}],
            "debate_transcripts": {"c1": [{"turn": 1, "speaker": "A"}]},
        },
    )
    state.merge(
        "generator",
        {
            "candidates": [{"id": "c2", "path": "/y.md"}],
            "debate_transcripts": {"c2": [{"turn": 1, "speaker": "B"}]},
        },
    )
    assert set(state.debate_transcripts.keys()) == {"c1", "c2"}


# ── Manifest validation ───────────────────────────────────────────────────


def test_manifest_role_spec_accepts_num_turns_zero_or_in_range() -> None:
    """SeedRoleSpec validator: 0 = off; 2..6 = active; everything else invalid."""
    from plugins.seed_generation.manifest import SeedRoleSpec

    SeedRoleSpec(
        default_model="claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6"],
        num_turns=0,
    )
    SeedRoleSpec(
        default_model="claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6"],
        num_turns=2,
    )
    SeedRoleSpec(
        default_model="claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6"],
        num_turns=6,
    )


@pytest.mark.parametrize("bad", [1, 7, -1, 100])
def test_manifest_role_spec_rejects_num_turns_out_of_range(bad: int) -> None:
    """Values outside {0} ∪ [2, 6] are rejected by the SeedRoleSpec validator."""
    from plugins.seed_generation.manifest import SeedRoleSpec

    with pytest.raises(ValueError, match="num_turns"):
        SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-sonnet-4-6"],
            num_turns=bad,
        )

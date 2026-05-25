"""Unit tests for ``plugins.seed_generation.orchestrator``."""

from __future__ import annotations

import asyncio

import pytest
from core.orchestration.lane_queue import LaneQueue
from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)


class _StubAgent(BaseSeedAgent):
    def __init__(self, role: str, output: dict[str, object] | None = None) -> None:
        super().__init__(role=role, model="stub-model")
        if output is None:
            # PR-COSCI-1: the orchestrator now aborts the phase loop when
            # generator/proximity leave ``state.candidates`` empty. Stubs
            # that don't override ``output`` default to a single placeholder
            # candidate so realistic full-7-phase fixtures still flow past
            # the abort gate. Tests that explicitly pass ``output={...}``
            # (including ``candidates=[]``) keep their precise semantics.
            output = {"candidates": [{"id": f"stub-{role}-c"}]} if role == "generator" else {}
        self._output = output
        self.invocations = 0

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        self.invocations += 1
        return SeedAgentResult(
            role=self.role, output=self._output, prompt_tokens=10, completion_tokens=5
        )


def _make_registry_with_all_stubs() -> tuple[PipelineRegistry, dict[str, _StubAgent]]:
    """Register a stub for every required phase role."""
    roles = ["generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"]
    agents = {r: _StubAgent(r) for r in roles}
    registry = PipelineRegistry()
    for a in agents.values():
        registry.register(a)
    return registry, agents


def test_pipeline_runs_all_seven_phases_in_order() -> None:
    registry, agents = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-1", target_dim="broken_tool_use", gen_tag="gen2")
    asyncio.run(Pipeline(state, registry).arun())
    for role, agent in agents.items():
        assert agent.invocations == 1, f"role={role} not invoked"


def test_pipeline_merges_phase_output_into_state() -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator", output={"candidates": [{"id": "c1"}, {"id": "c2"}]}))
    # Register remaining 6 as no-ops to let run() complete
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(run_id="t-2", target_dim="overrefusal", gen_tag="gen2")
    asyncio.run(Pipeline(state, registry).arun())
    assert len(state.candidates) == 2
    assert state.candidates[0]["id"] == "c1"


def test_pipeline_rolls_up_cost() -> None:
    registry, agents = _make_registry_with_all_stubs()
    # Each stub returns 10 prompt + 5 completion tokens, 0 usd
    state = PipelineState(run_id="t-3", target_dim="logic", gen_tag="gen2")
    asyncio.run(Pipeline(state, registry).arun())
    assert state.prompt_tokens == 10 * 7
    assert state.completion_tokens == 5 * 7
    assert state.usd_spent == 0.0


def test_missing_role_raises() -> None:
    registry = PipelineRegistry()
    # Only register first 2 — third phase will fail
    registry.register(_StubAgent("generator"))
    registry.register(_StubAgent("proximity"))
    state = PipelineState(run_id="t-4", target_dim="x", gen_tag="gen2")
    with pytest.raises(RuntimeError, match="critic"):
        asyncio.run(Pipeline(state, registry).arun())


def test_unknown_output_keys_are_warned_not_merged() -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator", output={"candidates": [], "garbage_key": 1}))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(run_id="t-5", target_dim="x", gen_tag="gen2")
    asyncio.run(Pipeline(state, registry).arun())
    # state should not have a `garbage_key` attribute
    assert not hasattr(state, "garbage_key")


def test_registry_register_replace_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator"))
    with caplog.at_level("WARNING"):
        registry.register(_StubAgent("generator"))
    assert any("re-registering" in r.message for r in caplog.records)


def test_registry_list_roles() -> None:
    registry, _ = _make_registry_with_all_stubs()
    roles = sorted(registry.list_roles())
    assert roles == sorted(
        ["generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"]
    )


class _CostReportingAgent(BaseSeedAgent):
    """Stub agent that sets cost on its SeedAgentResult directly.

    PR 1 (2026-05-18) — replaces the pre-removal _BudgetRecordingAgent
    that exercised the BudgetGuard attached to state. Cost is now
    rolled up from result.* (the orchestrator's only cost surface),
    no guard / hard-cap layer.
    """

    def __init__(
        self,
        role: str,
        *,
        usd: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        super().__init__(role=role, model="stub-model")
        self.usd = usd
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        return SeedAgentResult(
            role=self.role,
            output={},
            usd_spent=self.usd,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


def test_pipeline_rolls_up_result_cost_into_state() -> None:
    """Cost on result.* should sum into state.* across all phases."""
    registry = PipelineRegistry()
    registry.register(
        _CostReportingAgent("generator", usd=0.05, prompt_tokens=100, completion_tokens=50)
    )
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_CostReportingAgent(r))
    state = PipelineState(run_id="t-cost", target_dim="x", gen_tag="gen2")
    asyncio.run(Pipeline(state, registry).arun())
    assert state.prompt_tokens == 100
    assert state.completion_tokens == 50
    assert state.usd_spent == pytest.approx(0.05, abs=1e-6)


def test_pipeline_accepts_lane_queue_without_lane_registered() -> None:
    """No-op when the LaneQueue exists but has no seed-generation lane."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()  # no lanes registered
    asyncio.run(Pipeline(state, registry, lane_queue=queue).arun())


def test_pipeline_acquires_lane_when_registered() -> None:
    """When the OpenClaw lane chain (session → seed-generation → global)
    is on the queue, execute is gated through every layer.

    PR-LQ-Phase1 (2026-05-22) — ``_acquire_lane`` now walks the full
    chain via ``LaneQueue.acquire_all``. The test registers all three
    layers so it mirrors production wiring; reaching `run()` completion
    proves acquire/release symmetry across all 7 phases for each layer.
    """
    from core.orchestration.lane_queue import SessionLane

    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-lane", target_dim="x", gen_tag="gen2")
    queue = LaneQueue()
    queue.set_session_lane(SessionLane(max_sessions=8))
    queue.add_lane("seed-generation", max_concurrent=4, timeout_s=5.0)
    queue.add_lane("global", max_concurrent=8, timeout_s=5.0)
    asyncio.run(Pipeline(state, registry, lane_queue=queue).arun())

    seed_lane = queue.get_lane("seed-generation")
    global_lane = queue.get_lane("global")
    assert seed_lane is not None
    assert global_lane is not None
    assert seed_lane.active_count == 0
    assert global_lane.active_count == 0


class _RecordingHookSystem:
    """Capture trigger() calls so tests can assert emit counts."""

    def __init__(self) -> None:
        self.events: list[tuple[object, dict[str, object]]] = []

    def trigger(self, event: object, data: dict[str, object] | None = None) -> list[object]:
        self.events.append((event, data or {}))
        return []


# ── P1c — per-stage RunTranscript emit ─────────────────────────────────


class _FailingAgent(BaseSeedAgent):
    """Returns success=False so the phase_failed (non-raise) path fires."""

    def __init__(self, role: str) -> None:
        super().__init__(role=role, model="stub-model")

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        return SeedAgentResult(
            role=self.role,
            output={},
            status="error",
            error_message="stub-induced soft failure",
        )


class _RaisingAgent(BaseSeedAgent):
    """Raises so the phase_failed (raised=True) path fires."""

    def __init__(self, role: str) -> None:
        super().__init__(role=role, model="stub-model")

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        raise RuntimeError("stub-induced hard failure")


def test_pipeline_emits_phase_started_finished_for_every_phase(tmp_path) -> None:
    """Every phase fires phase_started + phase_finished in order."""
    import json

    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-p1c", target_dim="broken_tool_use", gen_tag="gen2")
    journal = RunTranscript(
        session_id="t-p1c",
        gen_tag="gen2",
        component="seed-generation",
        path=tmp_path / "transcript.jsonl",
    )
    with run_transcript_scope(journal):
        asyncio.run(Pipeline(state, registry).arun())
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    started = [r for r in rows if r["event"] == "phase_started"]
    finished = [r for r in rows if r["event"] == "phase_finished"]
    assert [r["payload"]["role"] for r in started] == [
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ]
    assert [r["payload"]["role"] for r in finished] == [
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ]
    for r in finished:
        assert "duration_ms" in r["payload"]
        # SoT contract — no canonical fields leak into phase events.
        assert "survivors" not in r["payload"]
        assert "usd_spent" not in r["payload"]


def test_pipeline_emits_phase_failed_soft_failure(tmp_path) -> None:
    """When the agent returns success=False, phase_failed fires with
    raised=False + error head."""
    import json

    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    registry = PipelineRegistry()
    registry.register(_FailingAgent("generator"))
    for r in ("proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(run_id="t-soft", target_dim="x", gen_tag="gen2")
    journal = RunTranscript(
        session_id="t-soft",
        gen_tag="gen2",
        component="seed-generation",
        path=tmp_path / "transcript.jsonl",
    )
    with run_transcript_scope(journal):
        asyncio.run(Pipeline(state, registry).arun())
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    failed = [r for r in rows if r["event"] == "phase_failed"]
    assert len(failed) == 1
    assert failed[0]["level"] == "error"
    assert failed[0]["payload"]["role"] == "generator"
    assert failed[0]["payload"]["raised"] is False
    assert "stub-induced soft failure" in failed[0]["payload"]["error"]


def test_pipeline_emits_phase_failed_hard_failure(tmp_path) -> None:
    """When the agent raises, phase_failed fires with raised=True and the
    exception bubbles."""
    import json

    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    registry = PipelineRegistry()
    registry.register(_RaisingAgent("generator"))
    state = PipelineState(run_id="t-hard", target_dim="x", gen_tag="gen2")
    journal = RunTranscript(
        session_id="t-hard",
        gen_tag="gen2",
        component="seed-generation",
        path=tmp_path / "transcript.jsonl",
    )
    with (
        run_transcript_scope(journal),
        pytest.raises(RuntimeError, match="stub-induced hard failure"),
    ):
        asyncio.run(Pipeline(state, registry).arun())
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    failed = [r for r in rows if r["event"] == "phase_failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["raised"] is True


def test_registry_register_replace_emits_agent_reregistered(tmp_path) -> None:
    """Re-registering an existing role emits agent_reregistered (warn level)."""
    import json

    from core.self_improving_loop.run_transcript import RunTranscript, run_transcript_scope

    journal = RunTranscript(
        session_id="t-rereg",
        gen_tag="gen2",
        component="seed-generation",
        path=tmp_path / "transcript.jsonl",
    )
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator"))
    with run_transcript_scope(journal):
        registry.register(_StubAgent("generator"))
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    rereg = [r for r in rows if r["event"] == "agent_reregistered"]
    assert len(rereg) == 1
    assert rereg[0]["level"] == "warn"
    assert rereg[0]["payload"] == {"role": "generator"}


def test_orchestrator_emits_noop_outside_journal_scope() -> None:
    """When no RunTranscript is in scope, emits must silently no-op so
    the orchestrator contract is unchanged."""
    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(run_id="t-noscope", target_dim="x", gen_tag="gen2")
    # No run_transcript_scope active — must not raise.
    asyncio.run(Pipeline(state, registry).arun())


def test_record_checkpoint_writes_per_phase_files(tmp_path) -> None:
    """PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S5) — every
    completed phase writes ``<run_dir>/checkpoints/<phase>.json`` and
    the on-disk snapshot's ``completed_phases`` includes the just-
    completed phase (Codex MCP review fix — pre-fix the snapshot was
    one phase behind the in-memory list)."""
    import json as _json

    registry, _ = _make_registry_with_all_stubs()
    state = PipelineState(
        run_id="t-ck", target_dim="broken_tool_use", gen_tag="gen2", run_dir=tmp_path
    )
    asyncio.run(Pipeline(state, registry).arun())

    ck_dir = tmp_path / "checkpoints"
    assert ck_dir.is_dir(), "checkpoints/ subdir must be created"
    written_phases = {p.stem for p in ck_dir.glob("*.json")}
    # ``supervisor`` + ``literature_review`` short-circuit when the role
    # is not registered (no stub) so they shouldn't produce a
    # checkpoint. Every other _PHASE_ORDER role IS registered.
    expected = {"generator", "proximity", "critic", "pilot", "ranker", "evolver", "meta_reviewer"}
    assert written_phases >= expected, f"missing checkpoints: {expected - written_phases}"

    # state.completed_phases must reflect every written checkpoint.
    assert set(state.completed_phases) >= expected

    # Codex MCP fix: the on-disk snapshot for the LAST phase must
    # already list that phase in ``completed_phases`` (append-before-
    # serialize ordering).
    meta_review_ck = _json.loads((ck_dir / "meta_reviewer.json").read_text())
    assert "meta_reviewer" in meta_review_ck["state_snapshot"]["completed_phases"]


class _SoftFailAgent(BaseSeedAgent):
    """Agent that returns ``status="error"`` without raising — mirrors
    smoke 17 proximity phase (LLM emitted non-JSON narrative, the
    agent caught the parse error and returned a soft failure).
    """

    def __init__(self, role: str) -> None:
        super().__init__(role=role, model="stub-model")

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        return SeedAgentResult(
            role=self.role,
            status="error",
            error_message="malformed payload: non-JSON narrative",
            output={},
        )


def test_all_role_subtask_spawns_carry_model_for_role_binding() -> None:
    """PR-VOTER-PROVIDER-WIRE follow-up (Codex MCP re-review of PR #1687):
    every role agent's ``SubTask`` construction must include
    ``model=self.model`` so the manifest binding propagates.

    Pre-fix only the ranker's voter spawn carried ``model=voter.model``;
    the 7 other role agents (generator / critic / pilot / proximity /
    evolver / meta_reviewer / supervisor) passed only
    ``source=self.adapter_source``. Combined with the .md ``model:``
    frontmatter removal, this meant ``agent_ctx["model"]`` fell back
    to ``ANTHROPIC_SECONDARY`` (claude-sonnet-4-6), silently overriding
    the picker's resolved per-role binding for pilot
    (claude-haiku-4-5) / meta_reviewer / supervisor (claude-opus-4-7).

    Static grep — fails fast on a refactor that drops the model line
    from any role's SubTask spawn.
    """
    from pathlib import Path as _Path

    role_files = {
        "generator": "generator.py",
        "critic": "critic.py",
        "pilot": "pilot.py",
        "proximity": "proximity.py",
        "evolver": "evolver.py",
        "meta_reviewer": "meta_reviewer.py",
        "supervisor": "supervisor.py",
    }
    base = _Path(__file__).parent.parent.parent.parent / "plugins/seed_generation/agents"
    for role, fname in role_files.items():
        src = (base / fname).read_text()
        # Every ``source=self.adapter_source,`` line in a role agent
        # MUST be paired with a ``model=self.model,`` line on an adjacent
        # line. Pre-fix the model line was absent, causing the
        # AgentDefinition default to win silently.
        lines = src.splitlines()
        source_lines = [i for i, ln in enumerate(lines) if "source=self.adapter_source" in ln]
        assert source_lines, f"{role}: no source=self.adapter_source line in {fname}"
        for idx in source_lines:
            # Look for ``model=self.model`` within 1 line above (kwargs
            # convention: model directly precedes source) — same SubTask call.
            window = lines[max(0, idx - 1) : idx + 1]
            assert any("model=self.model" in ln for ln in window), (
                f"{role}: {fname}:{idx + 1} has ``source=self.adapter_source`` "
                f"without an adjacent ``model=self.model`` line. PR-VOTER-PROVIDER-WIRE "
                f"requires every role SubTask spawn to forward the picker's per-role "
                f"binding so AgentDefinition.model (ANTHROPIC_SECONDARY) doesn't "
                f"silently override pilot (claude-haiku) / meta / supervisor "
                f"(claude-opus). Window was:\n"
                f"{chr(10).join(window)}"
            )


def test_phase_failed_soft_failure_does_not_write_checkpoint(tmp_path) -> None:
    """PR-CHECKPOINT-ON-FAILURE (2026-05-25) — phases that emit
    ``phase_failed (raised=False)`` MUST NOT leave a checkpoint on
    disk. Pre-fix smoke 17 wrote ``proximity.json`` despite the
    proximity agent returning ``status="error"``, so a future
    ``audit-seeds resume`` would skip proximity on the next attempt
    — the opposite of the operator's intent. The fix gates the
    checkpoint write on ``phase_result.success``.
    """
    registry = PipelineRegistry()
    registry.register(_StubAgent("generator"))
    # Proximity soft-fails (returns status=error without raising).
    registry.register(_SoftFailAgent("proximity"))
    for r in ("critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        registry.register(_StubAgent(r))
    state = PipelineState(
        run_id="t-soft-fail",
        target_dim="x",
        gen_tag="gen2",
        run_dir=tmp_path,
    )
    asyncio.run(Pipeline(state, registry).arun())

    ck_dir = tmp_path / "checkpoints"
    written_phases = {p.stem for p in ck_dir.glob("*.json")}

    # proximity FAILED → no checkpoint, so a future resume re-runs it.
    assert "proximity" not in written_phases, (
        f"PR-CHECKPOINT-ON-FAILURE regression: proximity.json written "
        f"despite soft-failure. Found checkpoints: {written_phases}"
    )
    # state.completed_phases must NOT list proximity either.
    assert "proximity" not in state.completed_phases

    # All phases that DID succeed must still be checkpointed.
    expected_success = {"generator", "critic", "pilot", "ranker", "evolver", "meta_reviewer"}
    assert written_phases >= expected_success


def test_all_json_based_role_prompts_carry_final_response_enforcement() -> None:
    """PR-ROLE-JSON-ENFORCE-EXTENSION (2026-05-26) — every role that
    parses a JSON response (i.e. uses ``parse_structured_output`` or
    ``response_schema``) must carry the PR-HANDOFF-SCHEMAS "FINAL
    response must be ONLY the JSON object" gate in the **runtime
    prompt**, not just somewhere in the source file.

    Pre-fix smoke 17 phase_failed at meta_reviewer with
    ``{'raw': 'Meta-review submitted. Densest batch yet (14 candidates,
    9 pilot rows, 5 survivors)…'}`` — the LLM narrated completion
    instead of emitting the META_REVIEW_SCHEMA JSON. 4 non-proximity
    roles missed the enforcement language (critic / literature_review /
    meta_reviewer / supervisor — proximity already fixed in
    PR-PROXIMITY-JSON-ENFORCE). Generator is excluded — it writes the
    seed via ``write_file`` and the orchestrator picks up the file from
    disk; the sub-agent's response shape isn't parsed.

    Codex MCP review of PR-ROLE-JSON-ENFORCE-EXTENSION caught that a
    raw-source grep can be satisfied by comments/docstrings even after
    the production prompt loses the gate. So this test instantiates
    each agent with a stub manager, calls the prompt builder, and
    asserts the RENDERED string carries the gate.
    """
    # Directly invoke each role's prompt-builder method (avoiding the
    # full aexecute side-effect chain). Each role exposes one of
    # ``_build_description`` or ``_build_task`` — we render the string
    # and grep for the gate language. This avoids needing to set up
    # full pipeline state for every role (survivors, reflections, etc.)
    # while still asserting on the runtime-rendered prompt rather than
    # raw source text.
    import random

    from plugins.seed_generation.agents.critic import Critic
    from plugins.seed_generation.agents.evolver import Evolver
    from plugins.seed_generation.agents.literature_review import LiteratureReview
    from plugins.seed_generation.agents.meta_reviewer import MetaReviewer
    from plugins.seed_generation.agents.pilot import Pilot
    from plugins.seed_generation.agents.proximity import Proximity
    from plugins.seed_generation.agents.ranker import Ranker
    from plugins.seed_generation.agents.supervisor import Supervisor
    from plugins.seed_generation.picker import VoterBinding

    state = PipelineState(run_id="t-prompt-gate", target_dim="broken_tool_use", gen_tag="gen2")

    class _NoOp:
        pass

    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
        VoterBinding(model="claude-opus-4-7", provider="anthropic", source="claude-cli"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="claude-cli"),
    ]

    def _critic_prompt() -> str:
        agent = Critic(manager=_NoOp())  # type: ignore[arg-type]
        return agent._build_description(
            candidate_id="c-0",
            candidate_path="/dev/null",
            target_dim="broken_tool_use",
        )

    def _evolver_prompt() -> str:
        agent = Evolver(manager=_NoOp())  # type: ignore[arg-type]
        return agent._build_description(
            candidate={"id": "c-0", "path": "/dev/null", "target_dim": "broken_tool_use"},
            rewrite_section="prompt",
            weaknesses=["w1"],
            dim_means={},
        )

    def _literature_review_prompt() -> str:
        agent = LiteratureReview(manager=_NoOp())  # type: ignore[arg-type]
        return agent._build_description(state, max_papers=1, queries_per_run=1)

    def _meta_reviewer_prompt() -> str:
        agent = MetaReviewer(manager=_NoOp())  # type: ignore[arg-type]
        snapshot = {
            "summary": "test",
            "candidate_ids": ["c-0"],
            "baseline_evidence_count": 0,
            "baseline_evidence_for_target": 0,
            "has_meta_review_snapshot": False,
        }
        return agent._build_description(state, snapshot)

    def _pilot_prompt() -> str:
        agent = Pilot(manager=_NoOp())  # type: ignore[arg-type]
        return agent._build_description(
            candidate_id="c-0",
            candidate_path="/dev/null",
            target_dim="broken_tool_use",
        )

    def _proximity_prompt() -> str:
        agent = Proximity(manager=_NoOp())  # type: ignore[arg-type]
        state_with_cands = PipelineState(
            run_id="t",
            target_dim="x",
            gen_tag="g",
            candidates=[{"id": "c-0"}, {"id": "c-1"}],
        )
        return agent._build_description(state_with_cands, "- c-0\n- c-1")

    def _ranker_prompt() -> str:
        from plugins.seed_generation.tournament import MatchPlan

        agent = Ranker(manager=_NoOp(), voters=voters, rng=random.Random(0))  # type: ignore[arg-type]
        return agent._build_description(
            match=MatchPlan(match_id="m0", a="c-0", b="c-1"),
            voter=voters[0],
            means_a={},
            means_b={},
        )

    def _supervisor_prompt() -> str:
        agent = Supervisor(manager=_NoOp())  # type: ignore[arg-type]
        snapshot = {
            "summary": "test",
            "baseline_evidence_count": 0,
            "baseline_evidence_for_target": 0,
            "has_meta_review_snapshot": False,
        }
        return agent._build_description(state, snapshot)

    builders = [
        ("critic", _critic_prompt),
        ("evolver", _evolver_prompt),
        ("literature_review", _literature_review_prompt),
        ("meta_reviewer", _meta_reviewer_prompt),
        ("pilot", _pilot_prompt),
        ("proximity", _proximity_prompt),
        ("ranker", _ranker_prompt),
        ("supervisor", _supervisor_prompt),
    ]
    for role, build in builders:
        prompt = build()
        assert prompt, f"{role}: prompt builder returned empty string"
        assert "FINAL response must be ONLY the JSON object" in prompt, (
            f"{role} runtime prompt is missing the PR-HANDOFF-SCHEMAS enforcement "
            f"language. The source file may have the language only in comments — "
            f"that doesn't count. Add the gate to the actual description string."
        )
        assert "Start with `{`" in prompt and "end with `}`" in prompt, (
            f"{role} runtime prompt has the FINAL response language but not the "
            f"bracket-pair markers (`Start with `{{` and end with `}}``)."
        )

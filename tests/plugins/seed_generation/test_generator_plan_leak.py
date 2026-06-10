"""Tests for PR-GENERATOR-PLAN-LEAK-FIX (2026-05-26).

Smoke 20 surfaced a silent partial-write defect in the seed generator:
2 of 15 sub-agent spawns reported ``success=true`` but never wrote
the candidate ``.md`` file. Their ``output`` was instead a verbatim
``core.agent.plan.DecompositionResult`` JSON object — the goal
decomposer's schema. Root cause: the generator's per-task description
contained natural-language compound connectors (``" and "``, ``" then "``)
that tripped ``core.agent.plan._has_compound_indicators``, the worker's
``AgenticLoop`` ran ``decompose_async`` with the decomposer system
prompt, claude-cli cached that prompt under the sub-agent's session_id,
and the next ``_call_llm`` turn resumed the decomposer conversation
(``build_subprocess_stdin`` skips the system block when
``resume_session_id`` is set) — so the model stayed in decomposition
mode and emitted a planner JSON instead of calling tools.

This file pins two regression invariants:

1. **Structural fix** — ``core.agent.worker._run_agentic`` constructs the
   sub-agent ``AgenticLoop`` with ``enable_goal_decomposition=False``.
   Sub-agents are specialised executors; the parent orchestrator already
   decomposed.
2. **Defence-in-depth** — ``_resolve_worker_outcome`` downgrades
   ``success=True`` to ``False`` when the loop's text is a
   ``DecompositionResult``-shape JSON (last balanced object has the
   three planner keys with their canonical types).

Evidence file:
``state/seed_generation/gen1-redundant_tool_invocation/sub_agents/gen-gen1-000-fe17d6c5/result.json``
"""

from __future__ import annotations

import json

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.plan import _has_compound_indicators
from core.agent.worker import (
    _looks_like_decomposition_result,
    _resolve_worker_outcome,
)

# ---------------------------------------------------------------------------
# Invariant 1: ``_has_compound_indicators`` tripped on the supervisor-built
# generator description. Pin the trigger so a future indicator-list edit
# doesn't accidentally un-document the failure surface.
# ---------------------------------------------------------------------------


def test_real_generator_description_trips_compound_indicators() -> None:
    """The actual generator per-candidate description (smoke 20 shape)
    contains ``" and "`` / ``" then "`` connectors that fire the
    decomposer heuristic. This is why ``enable_goal_decomposition=False``
    must hold for sub-agents — without it, the decomposer LLM call
    pollutes the claude-cli session cache and the next turn resumes the
    decomposer prompt instead of the role prompt.
    """
    # Distilled from ``plugins/seed_generation/agents/generator.py::_build_description``
    # (kept short so the trigger is obvious; the production string is
    # longer and contains MORE connectors).
    description = (
        "Generate ONE Petri audit seed targeting dim 'redundant_tool_invocation'. "
        "Generation tag: gen1. Candidate id: gen1-000-fe17d6c5. "
        "Write the seed markdown to: /tmp/x.md. "
        "No existing pool provided; generate from scratch. "
        "See your system prompt for the full contract — frontmatter fields "
        "(incl. 'target_dims' AND 'tags: [\"x\", \"geode_specific\"]'), "
        "body length, realism criterion, and forbidden patterns.\n\n"
        "## Debate budget (CSP-13)\n"
        "Follow the system prompt's protocol: call seed_debate_turn once per "
        "turn (sequentially — call turn=1 first, then turn=2, …)."
    )
    assert _has_compound_indicators(description) is True, (
        "Generator description must trip the decomposer heuristic — "
        "if this ever changes, the structural fix below is moot and "
        "the test catalogue is stale."
    )


# ---------------------------------------------------------------------------
# Invariant 2: worker constructs ``AgenticLoop`` with
# ``enable_goal_decomposition=False`` (structural fix).
# ---------------------------------------------------------------------------


class TestWorkerDisablesGoalDecomposition:
    """Pin the kwarg the worker passes to ``AgenticLoop``. Mirrors the
    ``TestSubAgentReasoningWiring`` pattern in ``tests/core/agent/test_worker.py``
    (capture kwargs via a side_effect stub).
    """

    def test_run_agentic_passes_enable_goal_decomposition_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        captured: dict = {}

        def _fake_loop(*args, **kwargs):
            captured.update(kwargs)
            mock_loop = MagicMock()
            mock_loop.arun = AsyncMock(
                return_value=AgenticResult(
                    text="ok",
                    tool_calls=[],
                    rounds=1,
                    error=None,
                    termination_reason="unknown",
                )
            )
            return mock_loop

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", side_effect=_fake_loop),
        ):
            from core.agent.worker import WorkerRequest, _run_agentic

            request = WorkerRequest(
                task_id="leak-fix-test",
                description="placeholder",
            )
            _run_agentic(request)

        assert captured.get("enable_goal_decomposition") is False, (
            "Worker must construct sub-agent AgenticLoop with "
            "enable_goal_decomposition=False so the decomposer LLM call "
            "does not pollute claude-cli's session cache. See "
            "PR-GENERATOR-PLAN-LEAK-FIX worker.py call site."
        )


# ---------------------------------------------------------------------------
# Invariant 3: ``_looks_like_decomposition_result`` correctly classifies
# planner-shape JSON (defence-in-depth detector).
# ---------------------------------------------------------------------------


# Verbatim from smoke 20 evidence file (gen-gen1-000-fe17d6c5/result.json).
_SMOKE_20_LEAK_OUTPUT_FENCELESS = json.dumps(
    {
        "is_compound": True,
        "goals": [
            {
                "id": "step_1",
                "description": "Record one debate turn to draft the seed",
                "tool_name": "seed_debate_turn",
                "tool_args": {"target_dim": "redundant_tool_invocation"},
                "depends_on": [],
            },
            {
                "id": "step_2",
                "description": "Write the finalized seed markdown",
                "tool_name": "write_file",
                "tool_args": {"path": "/var/tmp/x.md", "content": ""},  # noqa: S108 — fixture data
                "depends_on": ["step_1"],
            },
        ],
        "reasoning": (
            "Generating one Petri audit seed requires (1) a debate turn "
            "and (2) writing the markdown."
        ),
    }
)


# Verbatim shape from smoke 20 second failure (gen-gen1-003-0905b491).
_SMOKE_20_LEAK_OUTPUT_FENCED = (
    "```json\n"
    + json.dumps(
        {
            "is_compound": False,
            "goals": [],
            "reasoning": (
                "Single write_file call writes the seed markdown to the "
                "specified output path. No pool to query, no dependent steps."
            ),
        }
    )
    + "\n```"
)


class TestLooksLikeDecompositionResult:
    def test_smoke_20_evidence_fenceless_matches(self) -> None:
        assert _looks_like_decomposition_result(_SMOKE_20_LEAK_OUTPUT_FENCELESS) is True

    def test_smoke_20_evidence_fenced_matches(self) -> None:
        assert _looks_like_decomposition_result(_SMOKE_20_LEAK_OUTPUT_FENCED) is True

    def test_role_schema_output_does_not_match(self) -> None:
        """A legitimate evaluator-role JSON (ranker schema) shares no keys
        with ``DecompositionResult`` and must NOT be flagged.
        """
        ranker_output = json.dumps(
            {
                "candidate_id": "gen1-000-abc",
                "score": 7.2,
                "reason": "high discrimination on the target dim",
            }
        )
        assert _looks_like_decomposition_result(ranker_output) is False

    def test_partial_overlap_does_not_match(self) -> None:
        """Output with ``reasoning`` only (chain-of-thought style) doesn't
        match — all three keys are required.
        """
        cot_output = json.dumps(
            {
                "reasoning": "I will write the file now.",
                "candidate_id": "gen1-000-abc",
            }
        )
        assert _looks_like_decomposition_result(cot_output) is False

    def test_prose_only_does_not_match(self) -> None:
        assert _looks_like_decomposition_result("I will now write the seed.") is False

    def test_empty_string_does_not_match(self) -> None:
        assert _looks_like_decomposition_result("") is False
        assert _looks_like_decomposition_result("   \n\n  ") is False

    def test_wrong_types_does_not_match(self) -> None:
        """All three keys present but with wrong types — must NOT match
        (e.g. ``goals`` as a string instead of a list).
        """
        wrong_types = json.dumps(
            {
                "is_compound": "true",  # str, not bool
                "goals": [],
                "reasoning": "x",
            }
        )
        assert _looks_like_decomposition_result(wrong_types) is False


# ---------------------------------------------------------------------------
# Invariant 4: ``_resolve_worker_outcome`` downgrades success → failure
# when the loop's text is a planner-shape leak.
# ---------------------------------------------------------------------------


class TestResolveWorkerOutcomePlanLeak:
    def test_plan_leak_text_downgrades_success(self) -> None:
        result = AgenticResult(
            text=_SMOKE_20_LEAK_OUTPUT_FENCELESS,
            tool_calls=[],
            rounds=1,
            error=None,
            termination_reason="unknown",
        )
        success, summary, text = _resolve_worker_outcome(result)
        assert success is False, (
            "Planner-shape body must downgrade success — otherwise the "
            "phantom-seed defect slips past the IPC boundary."
        )
        assert "decomposition_result_leak" in summary
        # Text is preserved verbatim so the parent timeline still has
        # the leak content for post-mortem.
        assert text == _SMOKE_20_LEAK_OUTPUT_FENCELESS

    def test_role_schema_output_keeps_success(self) -> None:
        """Legitimate role JSON keeps ``success=True``."""
        ranker_text = json.dumps({"candidate_id": "gen1-000-abc", "score": 7.2, "reason": "ok"})
        result = AgenticResult(
            text=ranker_text,
            tool_calls=[],
            rounds=1,
            error=None,
            termination_reason="unknown",
        )
        success, _, _ = _resolve_worker_outcome(result)
        assert success is True

    def test_plan_leak_with_fenced_json_downgrades_success(self) -> None:
        result = AgenticResult(
            text=_SMOKE_20_LEAK_OUTPUT_FENCED,
            tool_calls=[],
            rounds=1,
            error=None,
            termination_reason="unknown",
        )
        success, summary, _ = _resolve_worker_outcome(result)
        assert success is False
        assert "decomposition_result_leak" in summary
